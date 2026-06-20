"""
药监接口连通性校验模块
- 追溯码上传
- 电子监管码扫码
- 联网监管平台连通
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any

from ..common.utils import Result, format_datetime


class DrugAdminChecker:
    """药监接口连通性校验器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.da_config = config.get("pre_check", {}).get("drug_admin", {})
        self.block_levels = self.da_config.get("block_levels", {})
        self.upload_success_rate = self.da_config.get("upload_success_rate", 1.0)
        self.scan_response_time = self.da_config.get("scan_response_time", 3)
        self.sync_delay_threshold = self.da_config.get("sync_delay_threshold", 1800)

    def run_all_checks(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行所有药监接口连通性校验"""
        self.logger.info("开始执行药监接口连通性校验...")

        results = {
            "module": "drug_admin_interface",
            "check_time": format_datetime(),
            "checks": {},
            "passed": True,
            "has_warning": False,
            "block_level": "none",
            "summary": "",
            "suggestions": []
        }

        check_items = [
            ("trace_upload", self._check_trace_code_upload, "追溯码上传接口校验"),
            ("e_code_scan", self._check_electronic_code_scan, "电子监管码扫码接口校验"),
            ("platform_sync", self._check_online_platform_sync, "联网监管平台同步校验"),
        ]

        high_blocks = 0

        for key, check_func, name in check_items:
            if not self._is_check_enabled(key):
                results["checks"][key] = {
                    "name": name,
                    "status": "skipped",
                    "message": "该检查项未启用"
                }
                continue

            try:
                result = check_func(release_data)
                results["checks"][key] = result.to_dict()

                block_level = self.block_levels.get(key, "medium")
                results["checks"][key]["block_level"] = block_level

                if not result.success:
                    if block_level == "high":
                        high_blocks += 1
                        results["passed"] = False
                        results["block_level"] = "high"
                    else:
                        results["has_warning"] = True

                if result.data and result.data.get("suggestion"):
                    results["suggestions"].append(result.data["suggestion"])

            except Exception as e:
                self.logger.error(f"{name}执行异常: {e}")
                results["checks"][key] = {
                    "name": name,
                    "status": "error",
                    "message": f"校验执行异常: {str(e)}",
                    "block_level": self.block_levels.get(key, "medium")
                }
                high_blocks += 1
                results["passed"] = False

        if results["passed"]:
            if results["has_warning"]:
                results["summary"] = "药监接口连通性校验通过，存在警告项"
            else:
                results["summary"] = "药监接口连通性校验全部通过"
        else:
            results["summary"] = f"药监接口连通性校验未通过，{high_blocks}个核心指标不达标"

        self.logger.info(f"药监接口连通性校验完成: {results['summary']}")
        return results

    def _is_check_enabled(self, check_key: str) -> bool:
        """检查项是否启用"""
        enable_map = {
            "trace_upload": "trace_code_upload",
            "e_code_scan": "e_code_scan",
            "online_platform_sync": "online_platform_sync",
        }
        config_key = enable_map.get(check_key)
        if config_key is None:
            return True
        return bool(self.da_config.get(config_key, True))

    def _check_trace_code_upload(self, release_data: Dict[str, Any]) -> Result:
        """追溯码上传接口校验"""
        trace_upload_data = release_data.get("trace_upload_data", {})
        if not trace_upload_data:
            return Result(False, "追溯码上传数据缺失",
                          data={"suggestion": "请确保药监追溯系统接口可正常访问"})

        total_uploads = trace_upload_data.get("total", 0)
        success_count = trace_upload_data.get("success", 0)
        failed_count = trace_upload_data.get("failed", 0)
        avg_response_time = trace_upload_data.get("avg_response_time_ms", 0)
        test_connection = trace_upload_data.get("connection_ok", False)

        if not test_connection:
            return Result(
                False,
                "追溯码上传接口连通性测试失败",
                data={"suggestion": "追溯码上传接口无法连通，请检查网络连接、接口地址及认证信息"}
            )

        if total_uploads == 0:
            return Result(
                False,
                "无追溯码上传记录，无法评估成功率",
                data={"suggestion": "请执行追溯码上传测试，确保上传功能正常"}
            )

        success_rate = success_count / total_uploads if total_uploads > 0 else 0
        failed_records = trace_upload_data.get("failed_records", [])

        if success_rate < self.upload_success_rate:
            return Result(
                False,
                f"追溯码上传成功率{success_rate:.2%}，低于阈值{self.upload_success_rate:.0%}，失败{failed_count}条",
                data={
                    "total": total_uploads,
                    "success": success_count,
                    "failed": failed_count,
                    "success_rate": success_rate,
                    "failed_records": failed_records[:5],
                    "avg_response_time_ms": avg_response_time,
                    "suggestion": f"追溯码上传成功率不达标，请检查药监追溯平台接口状态，失败原因包括: {', '.join(set([r.get('reason','未知') for r in failed_records[:3]]))}"
                }
            )

        return Result(
            True,
            f"追溯码上传接口校验通过，上传成功率{success_rate:.2%}，平均响应时间{avg_response_time}ms",
            data={
                "total": total_uploads,
                "success": success_count,
                "success_rate": success_rate,
                "avg_response_time_ms": avg_response_time
            }
        )

    def _check_electronic_code_scan(self, release_data: Dict[str, Any]) -> Result:
        """电子监管码扫码接口校验"""
        e_code_data = release_data.get("electronic_code_data", {})
        if not e_code_data:
            return Result(False, "电子监管码扫码数据缺失",
                          data={"suggestion": "请确保电子监管码扫码接口可正常访问"})

        total_scans = e_code_data.get("total", 0)
        success_count = e_code_data.get("success", 0)
        failed_count = e_code_data.get("failed", 0)
        avg_response_time = e_code_data.get("avg_response_time_seconds", 0)
        test_connection = e_code_data.get("connection_ok", False)

        if not test_connection:
            return Result(
                False,
                "电子监管码扫码接口连通性测试失败",
                data={"suggestion": "电子监管码扫码接口无法连通，请检查接口配置"}
            )

        if total_scans == 0:
            return Result(
                True,
                "无扫码记录，接口连通性正常",
                data={"suggestion": ""}
            )

        success_rate = success_count / total_scans if total_scans > 0 else 1.0

        issues = []
        if success_rate < 0.99:
            issues.append(f"扫码成功率{success_rate:.2%}")

        if avg_response_time > self.scan_response_time:
            issues.append(f"平均响应时间{avg_response_time}s > 阈值{self.scan_response_time}s")

        if issues:
            return Result(
                False,
                "电子监管码扫码接口存在性能问题: " + "; ".join(issues),
                data={
                    "total": total_scans,
                    "success": success_count,
                    "failed": failed_count,
                    "success_rate": success_rate,
                    "avg_response_time_seconds": avg_response_time,
                    "suggestion": f"电子监管码扫码接口性能不达标: {'; '.join(issues)}，请优化接口性能或检查网络状况"
                }
            )

        return Result(
            True,
            f"电子监管码扫码接口校验通过，扫码成功率{success_rate:.2%}，平均响应时间{avg_response_time}s",
            data={
                "total": total_scans,
                "success": success_count,
                "success_rate": success_rate,
                "avg_response_time_seconds": avg_response_time
            }
        )

    def _check_online_platform_sync(self, release_data: Dict[str, Any]) -> Result:
        """联网监管平台同步校验"""
        platform_sync_data = release_data.get("platform_sync_data", {})
        if not platform_sync_data:
            return Result(False, "联网监管平台同步数据缺失",
                          data={"suggestion": "请确保联网监管平台数据同步功能正常"})

        sync_status = platform_sync_data.get("sync_ok", False)
        last_sync_time = platform_sync_data.get("last_sync_time", "")
        sync_delay_minutes = platform_sync_data.get("sync_delay_minutes", 0)
        pending_data_count = platform_sync_data.get("pending_count", 0)
        total_data_count = platform_sync_data.get("total_count", 0)

        if not sync_status:
            return Result(
                False,
                "联网监管平台数据同步状态异常",
                data={"suggestion": "联网监管平台同步失败，请检查平台连接及数据同步配置"}
            )

        issues = []
        delay_threshold_minutes = self.sync_delay_threshold / 60

        if sync_delay_minutes > delay_threshold_minutes:
            issues.append(f"数据同步延迟{sync_delay_minutes}分钟 > 阈值{delay_threshold_minutes}分钟")

        if total_data_count > 0 and pending_data_count / total_data_count > 0.05:
            issues.append(f"待同步数据占比过高: {pending_data_count}/{total_data_count}")

        if issues:
            return Result(
                False,
                "联网监管平台同步存在延迟: " + "; ".join(issues),
                data={
                    "last_sync_time": last_sync_time,
                    "sync_delay_minutes": sync_delay_minutes,
                    "pending_count": pending_data_count,
                    "total_count": total_data_count,
                    "suggestion": f"联网监管平台数据同步不及时: {'; '.join(issues)}，请检查同步频率及平台处理能力"
                }
            )

        return Result(
            True,
            f"联网监管平台同步校验通过，最近同步时间: {last_sync_time}，延迟{sync_delay_minutes}分钟",
            data={
                "last_sync_time": last_sync_time,
                "sync_delay_minutes": sync_delay_minutes,
                "pending_count": pending_data_count
            }
        )
