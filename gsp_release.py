#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GSP发布与智能回滚自动化平台 - 主入口脚本
药品批发 GSP 管理系统版本发布与智能回滚自动化平台

用法:
    python gsp_release.py pre-check --version 2.0.0 --data-file release_data.json
    python gsp_release.py approval create --release-id REL-20240101 --channel normal
    python gsp_release.py gray start --gray-id GRY-xxxx
    python gsp_release.py report review --release-id REL-20240101
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.common.utils import (
    ConfigManager,
    setup_logger,
    generate_release_id,
    format_datetime,
    load_json,
    save_json,
    ensure_dir
)
from src.pre_check.engine import PreCheckEngine
from src.approval.engine import ApprovalEngine, ReleaseChannel
from src.gray_release.gray_engine import GrayReleaseEngine
from src.gray_release.circuit_breaker import CircuitBreakerEngine
from src.audit.engine import AuditLogger, ReportEngine


class GSPReleasePlatform:
    """GSP发布平台主类"""

    def __init__(self, config_path: str = None):
        self.config = ConfigManager(config_path).get_all()
        self.logger = setup_logger(
            "gsp_release",
            log_level=self.config.get("system", {}).get("log_level", "INFO"),
            log_dir=self.config.get("system", {}).get("log_path", "./logs")
        )

        self.pre_check_engine = PreCheckEngine(self.config)
        self.approval_engine = ApprovalEngine(self.config)
        self.gray_engine = GrayReleaseEngine(self.config)
        self.circuit_breaker = CircuitBreakerEngine(self.config)
        self.audit_logger = AuditLogger(self.config)
        self.report_engine = ReportEngine(self.config)

        self.data_path = self.config.get("system", {}).get("data_path", "./data")
        ensure_dir(self.data_path)

    def run_pre_check(self, version: str, data_file: str = None,
                     release_id: str = None) -> dict:
        """执行发布前置校验"""
        self.logger.info(f"开始发布前置校验 - 版本: {version}")

        if release_id is None:
            release_id = generate_release_id()

        check_data = {}
        if data_file and os.path.exists(data_file):
            check_data = load_json(data_file) or {}

        release_request = {
            "release_id": release_id,
            "version": version,
            "check_data": check_data
        }

        result = self.pre_check_engine.run_pre_check(release_request)

        self.audit_logger.log(
            log_type="quality_gate",
            action="pre_check",
            operator="system",
            target=release_id,
            detail={
                "version": version,
                "passed": result["overall_pass"],
                "block_level": result["block_level"]
            }
        )

        return result

    def create_approval(self, release_id: str, channel: str = "normal",
                       emergency_reason: str = "", requester: str = "system") -> dict:
        """创建审批流"""
        self.logger.info(f"创建审批流 - 发布: {release_id}, 通道: {channel}")

        flow = self.approval_engine.create_approval_flow(
            release_id=release_id,
            channel=channel,
            emergency_reason=emergency_reason
        )

        self.audit_logger.log(
            log_type="release_operation",
            action="create_approval",
            operator=requester,
            target=release_id,
            detail={
                "flow_id": flow.flow_id,
                "channel": channel,
                "emergency_reason": emergency_reason
            }
        )

        return flow.to_dict()

    def approve(self, flow_id: str, node_id: str, approver: str,
               comment: str = "") -> dict:
        """审批通过"""
        self.logger.info(f"审批通过 - 流程: {flow_id}, 节点: {node_id}, 审批人: {approver}")

        result = self.approval_engine.approve(flow_id, node_id, approver, comment)

        if result.get("success"):
            self.audit_logger.log(
                log_type="release_operation",
                action="approve",
                operator=approver,
                target=flow_id,
                detail={"node_id": node_id, "comment": comment}
            )

        return result

    def reject(self, flow_id: str, node_id: str, approver: str,
              reject_reason: str = "") -> dict:
        """审批驳回"""
        self.logger.info(f"审批驳回 - 流程: {flow_id}, 节点: {node_id}, 审批人: {approver}")

        result = self.approval_engine.reject(flow_id, node_id, approver, reject_reason)

        if result.get("success"):
            self.audit_logger.log(
                log_type="release_operation",
                action="reject",
                operator=approver,
                target=flow_id,
                detail={"node_id": node_id, "reason": reject_reason}
            )

        return result

    def start_gray_release(self, release_id: str, version: str,
                          target_version: str = "") -> dict:
        """启动灰度发布"""
        self.logger.info(f"启动灰度发布 - 发布: {release_id}, 版本: {version}")

        gray_release = self.gray_engine.create_gray_release(
            release_id=release_id,
            version=version,
            target_version=target_version
        )

        result = self.gray_engine.start_release(gray_release["gray_id"])

        self.audit_logger.log(
            log_type="release_operation",
            action="start_gray_release",
            operator="system",
            target=release_id,
            detail={
                "gray_id": gray_release["gray_id"],
                "version": version
            }
        )

        return result

    def advance_gray_stage(self, gray_id: str) -> dict:
        """推进灰度阶段"""
        self.logger.info(f"推进灰度阶段 - 灰度ID: {gray_id}")

        result = self.gray_engine.advance_stage(gray_id)

        if result.get("success"):
            self.audit_logger.log(
                log_type="release_operation",
                action="advance_stage",
                operator="system",
                target=gray_id,
                detail={"current_stage": result.get("current_stage")}
            )

        return result

    def trigger_circuit_break(self, gray_id: str, reason: str,
                             rollback_level: str = "warehouse",
                             target_version: str = "") -> dict:
        """触发熔断与回滚"""
        self.logger.warning(f"触发熔断 - 灰度ID: {gray_id}, 原因: {reason}")

        cb_record = self.circuit_breaker.trigger_circuit_break(
            gray_id=gray_id,
            reason=reason,
            rollback_level=rollback_level
        )

        rollback_result = self.circuit_breaker.execute_rollback(
            cb_id=cb_record["circuit_breaker_id"],
            rollback_level=rollback_level,
            target_version=target_version
        )

        verify_result = self.circuit_breaker.verify_rollback(
            cb_record["circuit_breaker_id"]
        )

        self.audit_logger.log(
            log_type="abnormal_event",
            action="circuit_break",
            operator="system",
            target=gray_id,
            detail={
                "cb_id": cb_record["circuit_breaker_id"],
                "reason": reason,
                "rollback_level": rollback_level,
                "rollback_success": rollback_result.get("success", False)
            }
        )

        return {
            "circuit_breaker": cb_record,
            "rollback": rollback_result,
            "verification": verify_result
        }

    def generate_review_report(self, release_id: str,
                               pre_check_result: dict = None,
                               approval_flow: dict = None,
                               gray_release: dict = None,
                               circuit_breaker: dict = None) -> dict:
        """生成发布复盘报告"""
        self.logger.info(f"生成发布复盘报告 - 发布: {release_id}")

        report = self.report_engine.generate_release_review_report(
            release_id=release_id,
            pre_check_result=pre_check_result,
            approval_flow=approval_flow,
            gray_release=gray_release,
            circuit_breaker=circuit_breaker
        )

        self.audit_logger.log(
            log_type="release_operation",
            action="generate_report",
            operator="system",
            target=release_id,
            detail={"report_id": report["report_id"]}
        )

        return report

    def query_audit_logs(self, log_type: str = None, start_date: str = None,
                        end_date: str = None, operator: str = None) -> list:
        """查询审计日志"""
        return self.audit_logger.query_logs(
            log_type=log_type,
            start_date=start_date,
            end_date=end_date,
            operator=operator
        )

    def generate_monthly_report(self, year_month: str = None) -> dict:
        """生成月度报表"""
        return self.report_engine.generate_monthly_success_rate_report(year_month)

    def generate_gsp_report(self, period: str = "quarter") -> dict:
        """生成GSP合规报表"""
        return self.report_engine.generate_gsp_compliance_report(period)


def main():
    parser = argparse.ArgumentParser(
        description="GSP发布与智能回滚自动化平台",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 前置校验
  python gsp_release.py pre-check --version 2.0.0 --data-file sample_data.json

  # 审批流程
  python gsp_release.py approval create --release-id REL-20240101 --channel normal
  python gsp_release.py approval approve --flow-id APV-xxx --node quality_manager --approver 张三

  # 灰度发布
  python gsp_release.py gray start --release-id REL-20240101 --version 2.0.0
  python gsp_release.py gray advance --gray-id GRY-xxx

  # 熔断回滚
  python gsp_release.py rollback --gray-id GRY-xxx --reason "单据异常率过高" --level warehouse

  # 报表
  python gsp_release.py report review --release-id REL-20240101
  python gsp_release.py report monthly --month 2024-01
  python gsp_release.py report gsp --period quarter

  # 审计
  python gsp_release.py audit query --start-date 2024-01-01
        """
    )

    parser.add_argument("--config", type=str, default=None,
                       help="配置文件路径")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    pre_check_parser = subparsers.add_parser("pre-check", help="发布前置校验")
    pre_check_parser.add_argument("--version", required=True, help="发布版本号")
    pre_check_parser.add_argument("--data-file", type=str, help="校验数据文件(JSON)")
    pre_check_parser.add_argument("--release-id", type=str, help="发布ID(可选)")

    approval_parser = subparsers.add_parser("approval", help="审批管理")
    approval_sub = approval_parser.add_subparsers(dest="approval_action")

    approval_create = approval_sub.add_parser("create", help="创建审批流")
    approval_create.add_argument("--release-id", required=True, help="发布ID")
    approval_create.add_argument("--channel", choices=["normal", "hotfix"],
                                default="normal", help="发布通道")
    approval_create.add_argument("--emergency-reason", type=str, default="",
                                help="紧急原因(hotfix通道必填)")
    approval_create.add_argument("--requester", type=str, default="system",
                                help="申请人")

    approval_approve = approval_sub.add_parser("approve", help="审批通过")
    approval_approve.add_argument("--flow-id", required=True, help="审批流ID")
    approval_approve.add_argument("--node", required=True, help="审批节点ID")
    approval_approve.add_argument("--approver", required=True, help="审批人")
    approval_approve.add_argument("--comment", type=str, default="", help="审批意见")

    approval_reject = approval_sub.add_parser("reject", help="审批驳回")
    approval_reject.add_argument("--flow-id", required=True, help="审批流ID")
    approval_reject.add_argument("--node", required=True, help="审批节点ID")
    approval_reject.add_argument("--approver", required=True, help="审批人")
    approval_reject.add_argument("--reason", type=str, default="", help="驳回原因")

    approval_status = approval_sub.add_parser("status", help="查看审批状态")
    approval_status.add_argument("--flow-id", required=True, help="审批流ID")

    gray_parser = subparsers.add_parser("gray", help="灰度发布管理")
    gray_sub = gray_parser.add_subparsers(dest="gray_action")

    gray_start = gray_sub.add_parser("start", help="启动灰度发布")
    gray_start.add_argument("--release-id", required=True, help="发布ID")
    gray_start.add_argument("--version", required=True, help="发布版本")
    gray_start.add_argument("--target-version", type=str, default="",
                           help="目标版本(用于回滚)")

    gray_advance = gray_sub.add_parser("advance", help="推进灰度阶段")
    gray_advance.add_argument("--gray-id", required=True, help="灰度发布ID")

    gray_status = gray_sub.add_parser("status", help="查看灰度状态")
    gray_status.add_argument("--gray-id", required=True, help="灰度发布ID")

    rollback_parser = subparsers.add_parser("rollback", help="熔断回滚")
    rollback_parser.add_argument("--gray-id", required=True, help="灰度发布ID")
    rollback_parser.add_argument("--reason", required=True, help="熔断原因")
    rollback_parser.add_argument("--level", choices=["function", "warehouse", "system", "data"],
                                default="warehouse", help="回滚级别")
    rollback_parser.add_argument("--target-version", type=str, default="",
                                help="回滚目标版本")

    report_parser = subparsers.add_parser("report", help="报表管理")
    report_sub = report_parser.add_subparsers(dest="report_action")

    report_review = report_sub.add_parser("review", help="发布复盘报告")
    report_review.add_argument("--release-id", required=True, help="发布ID")

    report_monthly = report_sub.add_parser("monthly", help="月度成功率报表")
    report_monthly.add_argument("--month", type=str, help="月份(YYYY-MM)")

    report_gsp = report_sub.add_parser("gsp", help="GSP合规报表")
    report_gsp.add_argument("--period", choices=["month", "quarter", "year"],
                           default="quarter", help="统计周期")

    audit_parser = subparsers.add_parser("audit", help="审计日志")
    audit_sub = audit_parser.add_subparsers(dest="audit_action")

    audit_query = audit_sub.add_parser("query", help="查询审计日志")
    audit_query.add_argument("--log-type", type=str, help="日志类型")
    audit_query.add_argument("--start-date", type=str, help="开始日期")
    audit_query.add_argument("--end-date", type=str, help="结束日期")
    audit_query.add_argument("--operator", type=str, help="操作人")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    platform = GSPReleasePlatform(args.config)

    try:
        if args.command == "pre-check":
            result = platform.run_pre_check(
                version=args.version,
                data_file=args.data_file,
                release_id=args.release_id
            )
            report_text = platform.pre_check_engine.get_check_report(result)
            print(report_text)

        elif args.command == "approval":
            if args.approval_action == "create":
                result = platform.create_approval(
                    release_id=args.release_id,
                    channel=args.channel,
                    emergency_reason=args.emergency_reason,
                    requester=args.requester
                )
                flow_id = result["flow_id"]
                status_summary = platform.approval_engine.get_approval_summary(flow_id)
                print(status_summary)

            elif args.approval_action == "approve":
                result = platform.approve(
                    flow_id=args.flow_id,
                    node_id=args.node,
                    approver=args.approver,
                    comment=args.comment
                )
                print(f"审批结果: {'成功' if result['success'] else '失败'}")
                print(f"消息: {result['message']}")
                if result.get("flow"):
                    print(f"流程状态: {result['flow']['overall_status']}")

            elif args.approval_action == "reject":
                result = platform.reject(
                    flow_id=args.flow_id,
                    node_id=args.node,
                    approver=args.approver,
                    reject_reason=args.reason
                )
                print(f"驳回结果: {'成功' if result['success'] else '失败'}")
                print(f"消息: {result['message']}")

            elif args.approval_action == "status":
                status_summary = platform.approval_engine.get_approval_summary(args.flow_id)
                print(status_summary)

        elif args.command == "gray":
            if args.gray_action == "start":
                result = platform.start_gray_release(
                    release_id=args.release_id,
                    version=args.version,
                    target_version=args.target_version
                )
                print(f"灰度发布启动: {'成功' if result.get('success') else '失败'}")
                if result.get("release"):
                    summary = platform.gray_engine.get_release_summary(result["release"]["gray_id"])
                    print(summary)

            elif args.gray_action == "advance":
                result = platform.advance_gray_stage(args.gray_id)
                print(f"阶段推进: {'成功' if result.get('success') else '失败'}")
                print(f"消息: {result.get('message', '')}")
                if result.get("release"):
                    summary = platform.gray_engine.get_release_summary(args.gray_id)
                    print(summary)

            elif args.gray_action == "status":
                summary = platform.gray_engine.get_release_summary(args.gray_id)
                print(summary)

        elif args.command == "rollback":
            result = platform.trigger_circuit_break(
                gray_id=args.gray_id,
                reason=args.reason,
                rollback_level=args.level,
                target_version=args.target_version
            )
            cb = result.get("circuit_breaker", {})
            rb = result.get("rollback", {})
            print(f"熔断ID: {cb.get('circuit_breaker_id', 'N/A')}")
            print(f"触发原因: {cb.get('reason', 'N/A')}")
            print(f"回滚级别: {args.level}")
            print(f"回滚结果: {'成功' if rb.get('success') else '失败'}")
            print(f"回滚消息: {rb.get('message', '')}")

        elif args.command == "report":
            if args.report_action == "review":
                report = platform.generate_review_report(
                    release_id=args.release_id
                )
                report_text = platform.report_engine.format_report_text(report)
                print(report_text)

            elif args.report_action == "monthly":
                report = platform.generate_monthly_report(args.month)
                report_text = platform.report_engine.format_report_text(report)
                print(report_text)

            elif args.report_action == "gsp":
                report = platform.generate_gsp_report(args.period)
                report_text = platform.report_engine.format_report_text(report)
                print(report_text)

        elif args.command == "audit":
            if args.audit_action == "query":
                logs = platform.query_audit_logs(
                    log_type=args.log_type,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    operator=args.operator
                )
                print(f"查询到 {len(logs)} 条审计日志")
                print("-" * 50)
                for log in logs[:20]:
                    print(f"[{log.get('timestamp','')}] {log.get('log_type','')} - "
                         f"{log.get('action','')} by {log.get('operator','')}")
                    if log.get("detail"):
                        print(f"  详情: {log['detail']}")
                if len(logs) > 20:
                    print(f"... 还有 {len(logs) - 20} 条记录")

    except Exception as e:
        print(f"执行出错: {e}")
        platform.logger.error(f"命令执行异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
