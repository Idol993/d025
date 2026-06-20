"""
GSP核心规则校验模块
- 首营企业/品种资质校验
- 近效期预警及超期锁定校验
- 先进先出/近效期先出规则校验
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from pathlib import Path

from ..common.utils import Result, format_datetime


class GSPChecker:
    """GSP规则校验器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.gsp_config = config.get("pre_check", {}).get("gsp", {})
        self.block_levels = self.gsp_config.get("block_levels", {})
        self.near_expiry_days = self.gsp_config.get("near_expiry_warning_days", 90)

    def run_all_checks(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行所有GSP规则校验"""
        self.logger.info("开始执行GSP核心规则校验...")

        results = {
            "module": "gsp_rules",
            "check_time": format_datetime(),
            "checks": {},
            "passed": True,
            "has_warning": False,
            "block_level": "none",
            "summary": "",
            "suggestions": []
        }

        check_items = [
            ("first_supplier", self._check_first_supplier_qualification, "首营企业资质校验"),
            ("first_drug", self._check_first_drug_qualification, "首营品种资质校验"),
            ("near_expiry", self._check_near_expiry_warning, "近效期预警校验"),
            ("expired_lock", self._check_expired_lock_logic, "超期锁定逻辑校验"),
            ("fifo", self._check_fifo_rule, "先进先出(FIFO)规则校验"),
            ("fefo", self._check_fefo_rule, "近效期先出(FEFO)规则校验"),
        ]

        high_blocks = 0
        warnings = 0

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
                        warnings += 1
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
                results["summary"] = f"GSP规则校验通过，存在{warnings}个警告项"
            else:
                results["summary"] = "GSP规则校验全部通过"
        else:
            results["summary"] = f"GSP规则校验未通过，{high_blocks}个核心指标不达标"

        self.logger.info(f"GSP规则校验完成: {results['summary']}")
        return results

    def _is_check_enabled(self, check_key: str) -> bool:
        """检查项是否启用"""
        enable_map = {
            "first_supplier": "first_supplier_check",
            "first_drug": "first_drug_check",
            "near_expiry": "near_expiry_warning_days",
            "expired_lock": "expired_lock_enabled",
            "fifo": "fifo_rule_enabled",
            "fefo": "fefo_rule_enabled",
        }
        config_key = enable_map.get(check_key)
        if config_key is None:
            return True
        return bool(self.gsp_config.get(config_key, True))

    def _check_first_supplier_qualification(self, release_data: Dict[str, Any]) -> Result:
        """首营企业资质校验"""
        new_suppliers = release_data.get("new_suppliers", [])
        if not new_suppliers:
            return Result(True, "无新增首营企业，校验通过")

        failed_suppliers = []
        for supplier in new_suppliers:
            supplier_name = supplier.get("name", "未知企业")
            required_docs = ["business_license", "gsp_certificate", "legal_person_id", "authorization_letter"]
            missing_docs = []
            for doc in required_docs:
                doc_info = supplier.get(doc, {})
                if not doc_info.get("exists", False):
                    missing_docs.append(doc)
                elif doc_info.get("expiry_date"):
                    try:
                        expiry_date = datetime.strptime(doc_info["expiry_date"], "%Y-%m-%d")
                        if expiry_date < datetime.now():
                            missing_docs.append(f"{doc}(已过期)")
                    except ValueError:
                        pass

            if missing_docs:
                failed_suppliers.append({
                    "supplier": supplier_name,
                    "missing": missing_docs
                })

        if failed_suppliers:
            return Result(
                False,
                f"{len(failed_suppliers)}家首营企业资质不完整",
                data={
                    "failed_suppliers": failed_suppliers,
                    "suggestion": f"请补充以下企业资质文件: {', '.join([s['supplier'] for s in failed_suppliers])}"
                }
            )

        return Result(True, f"{len(new_suppliers)}家首营企业资质校验全部通过")

    def _check_first_drug_qualification(self, release_data: Dict[str, Any]) -> Result:
        """首营品种资质校验"""
        new_drugs = release_data.get("new_drugs", [])
        if not new_drugs:
            return Result(True, "无新增首营品种，校验通过")

        failed_drugs = []
        for drug in new_drugs:
            drug_name = drug.get("name", "未知品种")
            required_docs = ["drug_registration_certificate", "drug_approval_number", "manufacturer_license",
                             "quality_standard", "package_spec", "label_sample"]
            missing_docs = []
            for doc in required_docs:
                doc_info = drug.get(doc, {})
                if not doc_info.get("exists", False):
                    missing_docs.append(doc)
                elif doc_info.get("expiry_date"):
                    try:
                        expiry_date = datetime.strptime(doc_info["expiry_date"], "%Y-%m-%d")
                        if expiry_date < datetime.now():
                            missing_docs.append(f"{doc}(已过期)")
                    except ValueError:
                        pass

            if missing_docs:
                failed_drugs.append({
                    "drug": drug_name,
                    "missing": missing_docs
                })

        if failed_drugs:
            return Result(
                False,
                f"{len(failed_drugs)}个首营品种资质不完整",
                data={
                    "failed_drugs": failed_drugs,
                    "suggestion": f"请补充以下品种资质文件: {', '.join([d['drug'] for d in failed_drugs])}"
                }
            )

        return Result(True, f"{len(new_drugs)}个首营品种资质校验全部通过")

    def _check_near_expiry_warning(self, release_data: Dict[str, Any]) -> Result:
        """近效期预警校验"""
        drugs = release_data.get("drugs", [])
        if not drugs:
            return Result(True, "无药品数据，跳过近效期预警校验")

        near_expiry_drugs = []
        warning_triggered = 0
        threshold_date = datetime.now() + timedelta(days=self.near_expiry_days)

        for drug in drugs:
            drug_name = drug.get("name", "")
            batches = drug.get("batches", [])
            for batch in batches:
                batch_no = batch.get("batch_no", "")
                try:
                    expiry_date = datetime.strptime(batch.get("expiry_date", "2099-12-31"), "%Y-%m-%d")
                    if expiry_date <= threshold_date:
                        near_expiry_drugs.append({
                            "drug": drug_name,
                            "batch": batch_no,
                            "expiry_date": batch.get("expiry_date"),
                            "days_left": (expiry_date - datetime.now()).days,
                            "warning_triggered": batch.get("warning_triggered", False)
                        })
                        if batch.get("warning_triggered", False):
                            warning_triggered += 1
                except ValueError:
                    continue

        if not near_expiry_drugs:
            return Result(True, "无近效期药品")

        total_near = len(near_expiry_drugs)
        trigger_rate = warning_triggered / total_near if total_near > 0 else 0

        if trigger_rate < 1.0:
            return Result(
                False,
                f"近效期药品共{total_near}个批次，仅{warning_triggered}个触发预警，触发率{trigger_rate:.1%}",
                data={
                    "near_expiry_drugs": near_expiry_drugs,
                    "trigger_rate": trigger_rate,
                    "suggestion": f"近效期预警覆盖率不足，请检查预警规则配置。当前预警天数设置: {self.near_expiry_days}天"
                }
            )

        return Result(
            True,
            f"近效期药品{total_near}个批次，预警覆盖率100%",
            data={"near_expiry_drugs": near_expiry_drugs}
        )

    def _check_expired_lock_logic(self, release_data: Dict[str, Any]) -> Result:
        """超期锁定逻辑校验"""
        drugs = release_data.get("drugs", [])
        if not drugs:
            return Result(True, "无药品数据，跳过超期锁定校验")

        expired_drugs = []
        locked_count = 0

        for drug in drugs:
            drug_name = drug.get("name", "")
            batches = drug.get("batches", [])
            for batch in batches:
                batch_no = batch.get("batch_no", "")
                try:
                    expiry_date = datetime.strptime(batch.get("expiry_date", "2099-12-31"), "%Y-%m-%d")
                    if expiry_date < datetime.now():
                        is_locked = batch.get("is_locked", False)
                        expired_drugs.append({
                            "drug": drug_name,
                            "batch": batch_no,
                            "expiry_date": batch.get("expiry_date"),
                            "is_locked": is_locked,
                            "can_outbound": batch.get("can_outbound", True)
                        })
                        if is_locked:
                            locked_count += 1
                except ValueError:
                    continue

        if not expired_drugs:
            return Result(True, "无过期药品")

        total_expired = len(expired_drugs)
        lock_rate = locked_count / total_expired if total_expired > 0 else 0

        unlocked_expired = [d for d in expired_drugs if not d["is_locked"] or d.get("can_outbound", True)]

        if unlocked_expired:
            return Result(
                False,
                f"过期药品共{total_expired}个批次，{len(unlocked_expired)}个未正确锁定",
                data={
                    "expired_drugs": expired_drugs,
                    "unlocked_expired": unlocked_expired,
                    "lock_rate": lock_rate,
                    "suggestion": f"过期药品锁定逻辑存在缺陷，{len(unlocked_expired)}个过期批次未被锁定或仍可出库，请检查锁定规则"
                }
            )

        return Result(
            True,
            f"过期药品{total_expired}个批次，全部正确锁定，锁定率100%",
            data={"expired_drugs": expired_drugs}
        )

    def _check_fifo_rule(self, release_data: Dict[str, Any]) -> Result:
        """先进先出(FIFO)规则校验"""
        fifo_config = release_data.get("fifo_config", {})
        if not self.gsp_config.get("fifo_rule_enabled", True):
            return Result(True, "FIFO规则未启用，跳过校验")

        issues = []

        if not fifo_config.get("enabled", True):
            issues.append("FIFO规则配置未启用")

        if fifo_config.get("priority", 1) != 1 and not fifo_config.get("enabled", False):
            pass

        test_cases = release_data.get("fifo_test_cases", [])
        failed_cases = []

        for case in test_cases:
            expected_order = case.get("expected_order", [])
            actual_order = case.get("actual_order", [])
            if expected_order and actual_order and expected_order != actual_order:
                failed_cases.append({
                    "case": case.get("name", "未知用例"),
                    "expected": expected_order,
                    "actual": actual_order
                })

        if failed_cases:
            return Result(
                False,
                f"FIFO规则验证失败，{len(failed_cases)}个测试用例不通过",
                data={
                    "failed_cases": failed_cases,
                    "suggestion": "请检查FIFO出库规则配置，确保同批次药品按入库顺序出库"
                }
            )

        if issues:
            return Result(
                False,
                "; ".join(issues),
                data={"suggestion": "请在系统配置中启用FIFO先进先出规则"}
            )

        return Result(True, "FIFO先进先出规则校验通过")

    def _check_fefo_rule(self, release_data: Dict[str, Any]) -> Result:
        """近效期先出(FEFO)规则校验"""
        if not self.gsp_config.get("fefo_rule_enabled", True):
            return Result(True, "FEFO规则未启用，跳过校验")

        fefo_config = release_data.get("fefo_config", {})
        issues = []

        if not fefo_config.get("enabled", True):
            issues.append("FEFO规则配置未启用")

        test_cases = release_data.get("fefo_test_cases", [])
        failed_cases = []

        for case in test_cases:
            expected_order = case.get("expected_order", [])
            actual_order = case.get("actual_order", [])
            if expected_order and actual_order and expected_order != actual_order:
                failed_cases.append({
                    "case": case.get("name", "未知用例"),
                    "expected": expected_order,
                    "actual": actual_order
                })

        if failed_cases:
            return Result(
                False,
                f"FEFO规则验证失败，{len(failed_cases)}个测试用例不通过",
                data={
                    "failed_cases": failed_cases,
                    "suggestion": "请检查FEFO出库规则配置，确保同品种药品按效期远近出库"
                }
            )

        if issues:
            return Result(
                False,
                "; ".join(issues),
                data={"suggestion": "请在系统配置中启用FEFO近效期先出规则"}
            )

        return Result(True, "FEFO近效期先出规则校验通过")
