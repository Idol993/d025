"""
合规审计与复盘报表引擎
- 操作审计日志
- 合规检查
- 发布复盘报告
- 统计分析报表
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict

from ..common.utils import format_datetime, save_json, ensure_dir, load_json


class AuditLogger:
    """审计日志记录器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.audit_config = config.get("audit", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")
        self.audit_dir = f"{self.data_path}/audit"
        self.log_types = self.audit_config.get("log_types", [])
        self.retention_years = self.audit_config.get("log_retention_years", 5)

        ensure_dir(self.audit_dir)

    def log(self, log_type: str, action: str, operator: str,
            target: str = "", detail: Dict[str, Any] = None,
            ip_address: str = "") -> str:
        """
        记录审计日志

        Args:
            log_type: 日志类型
            action: 操作动作
            operator: 操作人
            target: 操作对象
            detail: 详细信息
            ip_address: IP地址

        Returns:
            日志ID
        """
        log_id = f"AUD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{abs(hash(action + operator + target)) % 10000:04d}"

        log_entry = {
            "log_id": log_id,
            "log_type": log_type,
            "action": action,
            "operator": operator,
            "target": target,
            "detail": detail or {},
            "ip_address": ip_address,
            "timestamp": format_datetime(),
            "date": datetime.now().strftime("%Y-%m-%d")
        }

        self._save_audit_log(log_entry)
        self.logger.debug(f"审计日志: {log_id} - {action} by {operator}")

        return log_id

    def _save_audit_log(self, log_entry: Dict[str, Any]):
        """保存审计日志"""
        try:
            log_type = log_entry.get("log_type", "default")
            type_dir = f"{self.audit_dir}/{log_type}"
            ensure_dir(type_dir)

            date_str = log_entry.get("date", datetime.now().strftime("%Y-%m-%d"))
            file_path = f"{type_dir}/{date_str}.jsonl"

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(str(log_entry).replace("'", '"') + "\n")
        except Exception as e:
            self.logger.error(f"保存审计日志失败: {e}")

    def query_logs(self, log_type: str = None, start_date: str = None,
                   end_date: str = None, operator: str = None,
                   action: str = None, target: str = None) -> List[Dict[str, Any]]:
        """查询审计日志"""
        results = []

        if log_type:
            log_types = [log_type]
        else:
            log_types = self.log_types or ["release_operation", "data_change", "quality_gate", "abnormal_event"]

        for lt in log_types:
            type_dir = f"{self.audit_dir}/{lt}"
            if not os.path.exists(type_dir):
                continue

            for filename in sorted(os.listdir(type_dir)):
                if not filename.endswith(".jsonl"):
                    continue

                file_date = filename.replace(".jsonl", "")

                if start_date and file_date < start_date:
                    continue
                if end_date and file_date > end_date:
                    continue

                file_path = os.path.join(type_dir, filename)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                import json
                                log_entry = json.loads(line.strip())
                            except (json.JSONDecodeError, ValueError):
                                continue

                            if operator and log_entry.get("operator") != operator:
                                continue
                            if action and log_entry.get("action") != action:
                                continue
                            if target and target not in log_entry.get("target", ""):
                                continue

                            results.append(log_entry)
                except Exception as e:
                    self.logger.error(f"读取审计日志文件失败: {e}")

        return results

    def get_audit_statistics(self, start_date: str = None,
                            end_date: str = None) -> Dict[str, Any]:
        """获取审计统计信息"""
        stats = {
            "total_logs": 0,
            "by_type": defaultdict(int),
            "by_action": defaultdict(int),
            "by_operator": defaultdict(int),
            "by_day": defaultdict(int)
        }

        all_logs = self.query_logs(start_date=start_date, end_date=end_date)
        stats["total_logs"] = len(all_logs)

        for log in all_logs:
            stats["by_type"][log.get("log_type", "unknown")] += 1
            stats["by_action"][log.get("action", "unknown")] += 1
            stats["by_operator"][log.get("operator", "unknown")] += 1
            stats["by_day"][log.get("date", "unknown")] += 1

        return {
            "total_logs": stats["total_logs"],
            "by_type": dict(stats["by_type"]),
            "by_action": dict(stats["by_action"]),
            "by_operator": dict(stats["by_operator"]),
            "by_day": dict(sorted(stats["by_day"].items()))
        }


class ReportEngine:
    """报表引擎"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.report_config = config.get("audit", {}).get("report", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")
        self.report_dir = f"{self.data_path}/reports"

        ensure_dir(self.report_dir)

    def generate_release_review_report(self, release_id: str,
                                       pre_check_result: Dict[str, Any] = None,
                                       approval_flow: Dict[str, Any] = None,
                                       gray_release: Dict[str, Any] = None,
                                       circuit_breaker: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成发布复盘报告"""
        report_id = f"RPT-REVIEW-{release_id}"

        if pre_check_result is None:
            pre_check_result = self._find_pre_check_by_release_id(release_id)
        if approval_flow is None:
            approval_flow = self._find_approval_by_release_id(release_id)
        if gray_release is None:
            gray_release = self._find_gray_release_by_release_id(release_id)
        if circuit_breaker is None and gray_release:
            circuit_breaker = self._find_cb_by_gray_id(gray_release.get("gray_id", ""))

        report = {
            "report_id": report_id,
            "report_type": "release_review",
            "release_id": release_id,
            "generate_time": format_datetime(),
            "version": gray_release.get("version", "N/A") if gray_release else "N/A",
            "sections": {},
            "data_sources": {
                "pre_check": pre_check_result is not None,
                "approval_flow": approval_flow is not None,
                "gray_release": gray_release is not None,
                "circuit_breaker": circuit_breaker is not None
            }
        }

        report["sections"]["basic_info"] = self._generate_basic_info_section(
            release_id, pre_check_result, approval_flow, gray_release
        )

        report["sections"]["pre_check"] = self._generate_pre_check_section(pre_check_result)
        report["sections"]["approval"] = self._generate_approval_section(approval_flow)
        report["sections"]["gray_release"] = self._generate_gray_release_section(gray_release)
        report["sections"]["circuit_breaker"] = self._generate_cb_section(circuit_breaker)
        report["sections"]["summary"] = self._generate_summary_section(
            pre_check_result, approval_flow, gray_release, circuit_breaker
        )

        self._save_report(report_id, report)
        self.logger.info(f"生成发布复盘报告: {report_id}")

        return report

    def generate_monthly_success_rate_report(self, year_month: str = None) -> Dict[str, Any]:
        """生成月度发布成功率报表"""
        if year_month is None:
            year_month = datetime.now().strftime("%Y-%m")

        report_id = f"RPT-SUCCESS-{year_month}"

        releases = self._load_all_releases()
        month_releases = [r for r in releases if r.get("create_time", "").startswith(year_month)]

        total = len(month_releases)
        successful = len([r for r in month_releases if r.get("status") == "completed"])
        failed = len([r for r in month_releases if r.get("status") in ["failed", "rejected", "rolled_back"]])
        rollback_count = len([r for r in month_releases if r.get("rollback_triggered", False)])

        success_rate = successful / total if total > 0 else 0

        by_channel = defaultdict(lambda: {"total": 0, "success": 0})
        for r in month_releases:
            channel = r.get("channel", "normal")
            by_channel[channel]["total"] += 1
            if r.get("status") == "completed":
                by_channel[channel]["success"] += 1

        report = {
            "report_id": report_id,
            "report_type": "monthly_success_rate",
            "year_month": year_month,
            "generate_time": format_datetime(),
            "total_releases": total,
            "successful": successful,
            "failed": failed,
            "rollback_count": rollback_count,
            "success_rate": success_rate,
            "by_channel": {k: v for k, v in by_channel.items()},
            "trend_data": self._get_monthly_trend(year_month)
        }

        self._save_report(report_id, report)
        return report

    def generate_rollback_analysis_report(self, start_date: str = None,
                                          end_date: str = None) -> Dict[str, Any]:
        """生成回滚原因分析报表"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        report_id = f"RPT-ROLLBACK-{start_date}_{end_date}"

        cb_records = self._load_all_cb_records()
        period_records = [
            r for r in cb_records
            if start_date <= r.get("trigger_time", "")[:10] <= end_date
        ]

        reason_categories = defaultdict(int)
        by_stage = defaultdict(int)
        by_level = defaultdict(int)

        for record in period_records:
            reason = record.get("reason", "unknown")
            if "单据" in reason or "document" in reason.lower():
                reason_categories["单据异常"] += 1
            elif "冷链" in reason or "cold" in reason.lower():
                reason_categories["冷链异常"] += 1
            elif "药监" in reason or "drug" in reason.lower():
                reason_categories["药监接口异常"] += 1
            else:
                reason_categories["其他"] += 1

            by_stage[record.get("gray_id", "unknown")] += 1
            by_level[record.get("rollback_level", "unknown")] += 1

        report = {
            "report_id": report_id,
            "report_type": "rollback_analysis",
            "start_date": start_date,
            "end_date": end_date,
            "generate_time": format_datetime(),
            "total_rollbacks": len(period_records),
            "reason_distribution": dict(reason_categories),
            "by_rollback_level": dict(by_level),
            "improvement_suggestions": self._generate_improvement_suggestions(reason_categories)
        }

        self._save_report(report_id, report)
        return report

    def generate_gsp_compliance_report(self, period: str = "quarter",
                                       pre_check_result: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成GSP合规报表"""
        report_id = f"RPT-GSP-{period}-{datetime.now().strftime('%Y%m%d')}"

        compliance_items = self._generate_compliance_items_from_precheck(pre_check_result)

        total_items = len(compliance_items)
        compliant_count = sum(1 for item in compliance_items if item["compliant"])
        compliance_rate = compliant_count / total_items if total_items > 0 else 0

        non_compliant_detail = [item for item in compliance_items if not item["compliant"]]

        report = {
            "report_id": report_id,
            "report_type": "gsp_compliance",
            "period": period,
            "generate_time": format_datetime(),
            "compliance_rate": compliance_rate,
            "total_items": total_items,
            "compliant_items": compliant_count,
            "non_compliant_items": total_items - compliant_count,
            "compliance_details": compliance_items,
            "non_compliant_items_detail": non_compliant_detail,
            "based_on_precheck": pre_check_result is not None,
            "rectification_notice": self._generate_rectification_notice(compliance_items)
        }

        self._save_report(report_id, report)
        return report

    def _generate_compliance_items_from_precheck(self,
            pre_check_result: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """根据前置校验结果生成GSP合规检查项"""
        items = [
            {"item": "首营企业资质管理", "compliant": True, "non_compliant_count": 0,
             "description": "首营企业资质文件完整有效", "check_key": "first_supplier"},
            {"item": "首营品种资质管理", "compliant": True, "non_compliant_count": 0,
             "description": "首营品种注册批件等资料齐全", "check_key": "first_drug"},
            {"item": "近效期预警机制", "compliant": True, "non_compliant_count": 0,
             "description": "近效期药品100%预警", "check_key": "near_expiry"},
            {"item": "过期药品锁定", "compliant": True, "non_compliant_count": 0,
             "description": "过期药品自动锁定，禁止出库", "check_key": "expired_lock"},
            {"item": "先进先出规则", "compliant": True, "non_compliant_count": 0,
             "description": "FIFO出库规则正确执行", "check_key": "fifo"},
            {"item": "近效期先出规则", "compliant": True, "non_compliant_count": 0,
             "description": "FEFO出库规则正确执行", "check_key": "fefo"},
            {"item": "冷链温湿度监控", "compliant": True, "non_compliant_count": 0,
             "description": "冷链药品温湿度全程可追溯", "check_key": "cold_chain_data"},
            {"item": "药品追溯管理", "compliant": True, "non_compliant_count": 0,
             "description": "药品追溯码上传率100%", "check_key": "trace_upload"},
            {"item": "操作日志可追溯", "compliant": True, "non_compliant_count": 0,
             "description": "所有操作留痕可审计", "check_key": "audit_log"},
        ]

        if not pre_check_result:
            return items

        modules = pre_check_result.get("modules", {})

        gsp_checks = modules.get("gsp_rules", {}).get("checks", {})
        for item in items:
            check_key = item["check_key"]
            if check_key in gsp_checks:
                check_result = gsp_checks[check_key]
                is_success = check_result.get("success", False)
                item["compliant"] = is_success
                if not is_success:
                    item["non_compliant_count"] = 1
                    item["description"] = check_result.get("message", "检查未通过")

        cold_chain_checks = modules.get("cold_chain", {}).get("checks", {})
        for item in items:
            if item["check_key"] == "cold_chain_data":
                cc_check = cold_chain_checks.get("data_completeness", {})
                is_success = cc_check.get("success", False)
                item["compliant"] = is_success
                if not is_success:
                    item["non_compliant_count"] = 1
                    item["description"] = cc_check.get("message", "冷链温湿度数据不完整")

        drug_admin_checks = modules.get("drug_admin_interface", {}).get("checks", {})
        for item in items:
            if item["check_key"] == "trace_upload":
                trace_check = drug_admin_checks.get("trace_upload", {})
                is_success = trace_check.get("success", False)
                item["compliant"] = is_success
                if not is_success:
                    item["non_compliant_count"] = 1
                    item["description"] = trace_check.get("message", "药品追溯码上传失败")

        return items

    def _generate_basic_info_section(self, release_id: str,
                                     pre_check_result: Dict[str, Any],
                                     approval_flow: Dict[str, Any],
                                     gray_release: Dict[str, Any]) -> Dict[str, Any]:
        """生成基本信息章节"""
        return {
            "title": "发布基本信息",
            "release_id": release_id,
            "version": gray_release.get("version", "N/A") if gray_release else "N/A",
            "channel": approval_flow.get("channel", "normal") if approval_flow else "normal",
            "start_time": pre_check_result.get("check_start_time", "N/A") if pre_check_result else "N/A",
            "end_time": gray_release.get("update_time", "N/A") if gray_release else "N/A",
            "participants": self._get_participants(approval_flow),
            "result": self._get_release_result(gray_release)
        }

    def _generate_pre_check_section(self, pre_check_result: Dict[str, Any]) -> Dict[str, Any]:
        """生成前置校验章节"""
        if not pre_check_result:
            return {"title": "前置校验", "status": "no_data"}

        return {
            "title": "前置校验",
            "overall_pass": pre_check_result.get("overall_pass", False),
            "block_level": pre_check_result.get("block_level", "none"),
            "total_checks": pre_check_result.get("total_checks", 0),
            "passed_checks": pre_check_result.get("passed_checks", 0),
            "warning_checks": pre_check_result.get("warning_checks", 0),
            "blocked_checks": pre_check_result.get("blocked_checks", 0),
            "modules": list(pre_check_result.get("modules", {}).keys()),
            "suggestions": pre_check_result.get("all_suggestions", [])
        }

    def _generate_approval_section(self, approval_flow: Dict[str, Any]) -> Dict[str, Any]:
        """生成审批流程章节"""
        if not approval_flow:
            return {"title": "审批流程", "status": "no_data"}

        nodes = approval_flow.get("nodes", {})
        total_nodes = len(nodes)
        approved = sum(1 for n in nodes.values() if n.get("status") in ["approved", "post_signed"])
        rejected = sum(1 for n in nodes.values() if n.get("status") == "rejected")

        return {
            "title": "审批流程",
            "channel": approval_flow.get("channel", "normal"),
            "status": approval_flow.get("overall_status", "unknown"),
            "total_nodes": total_nodes,
            "approved": approved,
            "rejected": rejected,
            "emergency_reason": approval_flow.get("emergency_reason", ""),
            "create_time": approval_flow.get("create_time", ""),
            "update_time": approval_flow.get("update_time", "")
        }

    def _generate_gray_release_section(self, gray_release: Dict[str, Any]) -> Dict[str, Any]:
        """生成灰度发布章节"""
        if not gray_release:
            return {"title": "灰度发布", "status": "no_data"}

        stages = gray_release.get("stages", [])
        completed_stages = sum(1 for s in stages if s.get("status") == "completed")

        return {
            "title": "灰度发布",
            "status": gray_release.get("status", "unknown"),
            "current_stage": gray_release.get("current_stage", 0),
            "total_stages": len(stages),
            "completed_stages": completed_stages,
            "stages": [
                {
                    "stage": s["stage_num"],
                    "name": s["name"],
                    "status": s["status"],
                    "risk_level": s["risk_level"],
                    "observation_hours": s["observation_hours"]
                }
                for s in stages
            ],
            "events": gray_release.get("events", [])[-10:]
        }

    def _generate_cb_section(self, circuit_breaker: Dict[str, Any]) -> Dict[str, Any]:
        """生成熔断章节"""
        if not circuit_breaker:
            return {"title": "熔断与回滚", "status": "no_trigger", "message": "本次发布未触发熔断"}

        return {
            "title": "熔断与回滚",
            "triggered": True,
            "trigger_time": circuit_breaker.get("trigger_time", ""),
            "reason": circuit_breaker.get("reason", ""),
            "rollback_level": circuit_breaker.get("rollback_level", ""),
            "status": circuit_breaker.get("status", ""),
            "rollback_executed": circuit_breaker.get("rollback_executed", False)
        }

    def _generate_summary_section(self, pre_check_result: Dict[str, Any],
                                  approval_flow: Dict[str, Any],
                                  gray_release: Dict[str, Any],
                                  circuit_breaker: Dict[str, Any]) -> Dict[str, Any]:
        """生成总结章节"""
        lessons_learned = []
        improvement_actions = []

        if pre_check_result and not pre_check_result.get("overall_pass", True):
            lessons_learned.append("发布前应加强质量门禁检查，确保核心指标达标")
            improvement_actions.append("完善发布前自测清单")

        if circuit_breaker:
            lessons_learned.append(f"本次发布触发熔断，原因: {circuit_breaker.get('reason', '未知')}")
            improvement_actions.append("分析熔断根因，制定预防措施")

        return {
            "title": "总结与改进",
            "lessons_learned": lessons_learned if lessons_learned else ["本次发布顺利完成，无重大问题"],
            "improvement_actions": improvement_actions if improvement_actions else ["持续监控系统运行状态"],
            "overall_evaluation": self._evaluate_release(gray_release, circuit_breaker)
        }

    def _evaluate_release(self, gray_release: Dict[str, Any],
                         circuit_breaker: Dict[str, Any]) -> str:
        """评估发布效果"""
        if circuit_breaker:
            return "需改进"
        if gray_release and gray_release.get("status") == "completed":
            return "良好"
        return "进行中"

    def _get_participants(self, approval_flow: Dict[str, Any]) -> List[str]:
        """获取参与人员"""
        if not approval_flow:
            return []
        participants = []
        for node in approval_flow.get("nodes", {}).values():
            if node.get("approver"):
                participants.append(node["approver"])
        return list(set(participants))

    def _get_release_result(self, gray_release: Dict[str, Any]) -> str:
        """获取发布结果"""
        if not gray_release:
            return "未知"
        status = gray_release.get("status", "")
        if status == "completed":
            return "成功"
        elif status == "rolled_back":
            return "回滚"
        elif status in ["circuit_broken", "rolling_back"]:
            return "熔断中"
        return "进行中"

    def _get_monthly_trend(self, current_month: str) -> List[Dict[str, Any]]:
        """获取月度趋势数据"""
        trend = []
        try:
            year, month = map(int, current_month.split("-"))
            for i in range(6):
                m = month - i
                y = year
                if m <= 0:
                    m += 12
                    y -= 1
                month_str = f"{y}-{m:02d}"
                trend.append({"month": month_str, "total": 0, "success_rate": 0})
        except (ValueError, TypeError):
            pass

        return list(reversed(trend))

    def _generate_improvement_suggestions(self, reason_categories: Dict[str, int]) -> List[str]:
        """生成改进建议"""
        suggestions = []
        if reason_categories.get("单据异常", 0) > 0:
            suggestions.append("加强单据生成逻辑的单元测试和集成测试覆盖率")
        if reason_categories.get("冷链异常", 0) > 0:
            suggestions.append("优化冷链监控系统报警阈值和响应机制")
        if reason_categories.get("药监接口异常", 0) > 0:
            suggestions.append("增加药监接口重试机制和降级策略")
        if not suggestions:
            suggestions.append("持续监控系统运行，保持发布质量")
        return suggestions

    def _generate_rectification_notice(self, compliance_items: List[Dict[str, Any]]) -> List[str]:
        """生成整改通知"""
        notices = []
        non_compliant = [item for item in compliance_items if not item["compliant"]]
        for item in non_compliant:
            notices.append(f"【整改项】{item['item']}: {item.get('description', '')}")
        if not notices:
            notices.append("本期合规检查全部通过，继续保持")
        return notices

    def _load_all_releases(self) -> List[Dict[str, Any]]:
        """加载所有发布记录"""
        releases = []
        releases_dir = f"{self.data_path}/gray_release"
        if not os.path.exists(releases_dir):
            return releases

        for filename in os.listdir(releases_dir):
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(releases_dir, filename)
            try:
                release = load_json(file_path)
                if release:
                    releases.append(release)
            except Exception:
                pass

        return releases

    def _load_all_cb_records(self) -> List[Dict[str, Any]]:
        """加载所有熔断记录"""
        records = []
        cb_dir = f"{self.data_path}/circuit_breaker"
        if not os.path.exists(cb_dir):
            return records

        for filename in os.listdir(cb_dir):
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(cb_dir, filename)
            try:
                record = load_json(file_path)
                if record:
                    records.append(record)
            except Exception:
                pass

        return records

    def _find_pre_check_by_release_id(self, release_id: str) -> Optional[Dict[str, Any]]:
        """根据发布ID查找前置校验结果"""
        pre_check_dir = f"{self.data_path}/pre_check"
        if not os.path.exists(pre_check_dir):
            return None

        for filename in sorted(os.listdir(pre_check_dir), reverse=True):
            if not filename.endswith(".json"):
                continue
            if release_id in filename:
                file_path = os.path.join(pre_check_dir, filename)
                try:
                    return load_json(file_path)
                except Exception:
                    pass
        return None

    def _find_approval_by_release_id(self, release_id: str) -> Optional[Dict[str, Any]]:
        """根据发布ID查找审批流"""
        approval_dir = f"{self.data_path}/approvals"
        if not os.path.exists(approval_dir):
            return None

        for filename in os.listdir(approval_dir):
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(approval_dir, filename)
            try:
                data = load_json(file_path)
                if data and data.get("release_id") == release_id:
                    return data
            except Exception:
                pass
        return None

    def _find_gray_release_by_release_id(self, release_id: str) -> Optional[Dict[str, Any]]:
        """根据发布ID查找灰度发布记录"""
        releases = self._load_all_releases()
        for release in releases:
            if release.get("release_id") == release_id:
                return release
        return None

    def _find_cb_by_gray_id(self, gray_id: str) -> Optional[Dict[str, Any]]:
        """根据灰度ID查找熔断记录"""
        cb_records = self._load_all_cb_records()
        for record in cb_records:
            if record.get("gray_id") == gray_id:
                return record
        return None

    def _save_report(self, report_id: str, report: Dict[str, Any]):
        """保存报表"""
        try:
            file_path = f"{self.report_dir}/{report_id}.json"
            save_json(report, file_path)
        except Exception as e:
            self.logger.error(f"保存报表失败: {e}")

    def format_report_text(self, report: Dict[str, Any]) -> str:
        """格式化报表为文本"""
        lines = []
        report_type = report.get("report_type", "unknown")

        type_names = {
            "release_review": "发布复盘报告",
            "monthly_success_rate": "月度发布成功率报表",
            "rollback_analysis": "回滚原因分析报表",
            "gsp_compliance": "GSP合规报表"
        }

        lines.append("=" * 60)
        lines.append(type_names.get(report_type, report_type))
        lines.append("=" * 60)
        lines.append(f"报告ID: {report.get('report_id', 'N/A')}")
        lines.append(f"生成时间: {report.get('generate_time', 'N/A')}")
        lines.append("")

        if report_type == "release_review":
            sections = report.get("sections", {})
            for section_key, section in sections.items():
                if isinstance(section, dict) and section.get("title"):
                    lines.append(f"【{section['title']}】")
                    lines.append("-" * 40)
                    for key, value in section.items():
                        if key == "title":
                            continue
                        if isinstance(value, list):
                            lines.append(f"  {key}:")
                            for item in value[:5]:
                                lines.append(f"    - {item}")
                        elif isinstance(value, dict):
                            lines.append(f"  {key}: {len(value)}项")
                        else:
                            lines.append(f"  {key}: {value}")
                    lines.append("")

        elif report_type == "monthly_success_rate":
            lines.append(f"统计月份: {report.get('year_month', 'N/A')}")
            lines.append(f"总发布次数: {report.get('total_releases', 0)}")
            lines.append(f"成功次数: {report.get('successful', 0)}")
            lines.append(f"失败次数: {report.get('failed', 0)}")
            lines.append(f"回滚次数: {report.get('rollback_count', 0)}")
            lines.append(f"成功率: {report.get('success_rate', 0):.2%}")

        elif report_type == "gsp_compliance":
            lines.append(f"统计周期: {report.get('period', 'N/A')}")
            lines.append(f"合规率: {report.get('compliance_rate', 0):.2%}")
            lines.append(f"检查项总数: {report.get('total_items', 0)}")
            lines.append(f"合规项: {report.get('compliant_items', 0)}")
            lines.append(f"不合规项: {report.get('non_compliant_items', 0)}")

            compliance_details = report.get('compliance_details', [])
            if compliance_details:
                lines.append("")
                lines.append("合规检查明细:")
                lines.append("-" * 40)
                for item in compliance_details:
                    status = "✓" if item.get("compliant") else "✗"
                    lines.append(f"  {status} {item.get('item', '')}")
                    if not item.get("compliant"):
                        lines.append(f"      描述: {item.get('description', '')}")
                        nc_count = item.get('non_compliant_count', 0)
                        if nc_count > 0:
                            lines.append(f"      不合规数量: {nc_count}")
                        if item.get('issues'):
                            lines.append(f"      问题: {item.get('issues')}")

            rectification = report.get('rectification_notice', [])
            if rectification:
                lines.append("")
                lines.append("整改通知:")
                lines.append("-" * 40)
                for notice in rectification:
                    lines.append(f"  {notice}")

        lines.append("=" * 60)

        return "\n".join(lines)
