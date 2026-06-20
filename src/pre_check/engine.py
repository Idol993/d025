"""
发布前置校验引擎
整合GSP规则、进销存一致性、冷链完整性、药监接口四大维度校验
"""

import logging
from datetime import datetime
from typing import Dict, Any, List

from ..common.utils import format_datetime, save_json, ensure_dir
from .gsp_checker import GSPChecker
from .inventory_checker import InventoryChecker
from .cold_chain_checker import ColdChainChecker
from .drug_admin_checker import DrugAdminChecker


class PreCheckEngine:
    """发布前置校验引擎"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.pre_check_config = config.get("pre_check", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")

        self.gsp_checker = GSPChecker(config)
        self.inventory_checker = InventoryChecker(config)
        self.cold_chain_checker = ColdChainChecker(config)
        self.drug_admin_checker = DrugAdminChecker(config)

    def run_pre_check(self, release_request: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行完整的发布前置校验

        Args:
            release_request: 发布申请数据

        Returns:
            校验结果汇总
        """
        release_id = release_request.get("release_id", "UNKNOWN")
        version = release_request.get("version", "UNKNOWN")

        self.logger.info(f"开始执行发布前置校验 - 版本: {version}, 发布ID: {release_id}")

        result = {
            "release_id": release_id,
            "version": version,
            "check_start_time": format_datetime(),
            "check_end_time": None,
            "status": "running",
            "overall_pass": False,
            "block_level": "none",
            "modules": {},
            "total_checks": 0,
            "passed_checks": 0,
            "failed_checks": 0,
            "warning_checks": 0,
            "blocked_checks": 0,
            "all_suggestions": [],
            "summary": ""
        }

        release_data = release_request.get("check_data", {})

        try:
            gsp_result = self.gsp_checker.run_all_checks(release_data)
            result["modules"]["gsp_rules"] = gsp_result

            inv_result = self.inventory_checker.run_all_checks(release_data)
            result["modules"]["inventory_consistency"] = inv_result

            cc_result = self.cold_chain_checker.run_all_checks(release_data)
            result["modules"]["cold_chain"] = cc_result

            da_result = self.drug_admin_checker.run_all_checks(release_data)
            result["modules"]["drug_admin_interface"] = da_result

        except Exception as e:
            self.logger.error(f"前置校验执行异常: {e}")
            result["status"] = "error"
            result["summary"] = f"校验执行异常: {str(e)}"
            return result

        self._calculate_summary(result)

        result["check_end_time"] = format_datetime()
        result["status"] = "completed"

        self._save_check_result(result)

        self.logger.info(f"前置校验完成 - 状态: {'通过' if result['overall_pass'] else '未通过'}, "
                         f"阻断级别: {result['block_level']}")

        return result

    def _calculate_summary(self, result: Dict[str, Any]):
        """计算校验汇总结果"""
        overall_pass = True
        max_block_level = "none"
        all_suggestions = []

        level_order = {"none": 0, "low": 1, "medium": 2, "high": 3}

        total = 0
        passed = 0
        failed = 0
        warnings = 0
        blocked = 0

        for module_name, module_result in result["modules"].items():
            checks = module_result.get("checks", {})
            for check_key, check_result in checks.items():
                total += 1
                status = check_result.get("status", "unknown")

                if status == "passed" or (status == "success" and check_result.get("success", False)):
                    passed += 1
                elif status == "skipped":
                    pass
                else:
                    failed += 1
                    block_level = check_result.get("block_level", "medium")

                    if level_order.get(block_level, 0) > level_order.get(max_block_level, 0):
                        max_block_level = block_level

                    if block_level == "high":
                        blocked += 1
                        overall_pass = False
                    else:
                        warnings += 1

            suggestions = module_result.get("suggestions", [])
            all_suggestions.extend(suggestions)

        result["overall_pass"] = overall_pass
        result["block_level"] = max_block_level
        result["total_checks"] = total
        result["passed_checks"] = passed
        result["failed_checks"] = failed
        result["warning_checks"] = warnings
        result["blocked_checks"] = blocked
        result["all_suggestions"] = all_suggestions

        if overall_pass:
            if warnings > 0:
                result["summary"] = f"前置校验通过，存在{warnings}个警告项，建议关注并持续改进"
            else:
                result["summary"] = "前置校验全部通过，可以进入审批流程"
        else:
            result["summary"] = (f"前置校验未通过，{blocked}个核心指标阻断发布，"
                                 f"{warnings}个警告项，请修复后重新提交")

    def _save_check_result(self, result: Dict[str, Any]):
        """保存校验结果"""
        try:
            check_dir = f"{self.data_path}/pre_check"
            ensure_dir(check_dir)
            file_path = f"{check_dir}/{result['release_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
            save_json(result, file_path)
            self.logger.debug(f"校验结果已保存: {file_path}")
        except Exception as e:
            self.logger.warning(f"保存校验结果失败: {e}")

    def get_check_report(self, result: Dict[str, Any]) -> str:
        """生成校验报告文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("GSP管理系统 - 发布前置校验报告")
        lines.append("=" * 60)
        lines.append(f"发布ID: {result.get('release_id', 'N/A')}")
        lines.append(f"版本号: {result.get('version', 'N/A')}")
        lines.append(f"校验开始时间: {result.get('check_start_time', 'N/A')}")
        lines.append(f"校验结束时间: {result.get('check_end_time', 'N/A')}")
        lines.append(f"校验状态: {'通过' if result.get('overall_pass') else '未通过'}")
        lines.append(f"阻断级别: {result.get('block_level', 'none')}")
        lines.append("")

        lines.append(f"总检查项: {result.get('total_checks', 0)}")
        lines.append(f"通过: {result.get('passed_checks', 0)}")
        lines.append(f"警告: {result.get('warning_checks', 0)}")
        lines.append(f"阻断: {result.get('blocked_checks', 0)}")
        lines.append("")

        lines.append("-" * 40)
        lines.append("各模块校验结果:")
        lines.append("-" * 40)

        module_names = {
            "gsp_rules": "GSP核心规则",
            "inventory_consistency": "进销存一致性",
            "cold_chain": "冷链记录完整性",
            "drug_admin_interface": "药监接口连通性"
        }

        for module_key, module_result in result.get("modules", {}).items():
            name = module_names.get(module_key, module_key)
            passed = module_result.get("passed", False)
            has_warning = module_result.get("has_warning", False)
            summary = module_result.get("summary", "")

            status_icon = "✓" if passed else "✗"
            warning_note = " (含警告)" if has_warning and passed else ""

            lines.append(f"  {status_icon} {name}{warning_note}")
            lines.append(f"    {summary}")
            lines.append("")

        if result.get("all_suggestions"):
            lines.append("-" * 40)
            lines.append("修复建议:")
            lines.append("-" * 40)
            for i, suggestion in enumerate(result["all_suggestions"], 1):
                lines.append(f"  {i}. {suggestion}")
            lines.append("")

        lines.append("=" * 60)
        lines.append(f"结论: {result.get('summary', '')}")
        lines.append("=" * 60)

        return "\n".join(lines)
