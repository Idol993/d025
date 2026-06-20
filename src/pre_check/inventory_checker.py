"""
进销存一致性校验模块
- WMS与ERP库存对账
- 单据完整性校验
- 批次一致性校验
"""

import logging
from typing import Dict, List, Any
from decimal import Decimal, getcontext

from ..common.utils import Result, format_datetime, calculate_diff_rate

getcontext().prec = 10


class InventoryChecker:
    """进销存一致性校验器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.inv_config = config.get("pre_check", {}).get("inventory", {})
        self.block_levels = self.inv_config.get("block_levels", {})
        self.diff_threshold = self.inv_config.get("diff_rate_threshold", 0.001)

    def run_all_checks(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行所有进销存一致性校验"""
        self.logger.info("开始执行进销存一致性校验...")

        results = {
            "module": "inventory_consistency",
            "check_time": format_datetime(),
            "checks": {},
            "passed": True,
            "has_warning": False,
            "block_level": "none",
            "summary": "",
            "suggestions": []
        }

        check_items = [
            ("wms_erp_diff", self._check_wms_erp_reconciliation, "WMS-ERP库存对账校验"),
            ("doc_integrity", self._check_doc_integrity, "单据完整性校验"),
            ("batch_consistency", self._check_batch_consistency, "批次一致性校验"),
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

                block_level = self.block_levels.get(key, "high")
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
                    "block_level": self.block_levels.get(key, "high")
                }
                high_blocks += 1
                results["passed"] = False

        if results["passed"]:
            if results["has_warning"]:
                results["summary"] = "进销存一致性校验通过，存在警告项"
            else:
                results["summary"] = "进销存一致性校验全部通过"
        else:
            results["summary"] = f"进销存一致性校验未通过，{high_blocks}个核心指标不达标"

        self.logger.info(f"进销存一致性校验完成: {results['summary']}")
        return results

    def _is_check_enabled(self, check_key: str) -> bool:
        """检查项是否启用"""
        enable_map = {
            "wms_erp_diff": "wms_erp_reconciliation",
            "doc_integrity": "doc_integrity_check",
            "batch_consistency": "batch_consistency_check",
        }
        config_key = enable_map.get(check_key)
        if config_key is None:
            return True
        return bool(self.inv_config.get(config_key, True))

    def _check_wms_erp_reconciliation(self, release_data: Dict[str, Any]) -> Result:
        """WMS-ERP库存对账校验"""
        wms_inventory = release_data.get("wms_inventory", {})
        erp_inventory = release_data.get("erp_inventory", {})

        if not wms_inventory or not erp_inventory:
            return Result(False, "WMS或ERP库存数据缺失，无法对账",
                          data={"suggestion": "请确保WMS和ERP系统均可正常访问并提供库存数据"})

        diff_items = []
        total_items = 0
        total_wms_qty = Decimal(0)
        total_erp_qty = Decimal(0)
        total_diff_qty = Decimal(0)

        all_drugs = set(list(wms_inventory.keys()) + list(erp_inventory.keys()))

        for drug_id in all_drugs:
            total_items += 1
            wms_batches = wms_inventory.get(drug_id, {})
            erp_batches = erp_inventory.get(drug_id, {})

            drug_wms_total = sum(Decimal(str(b.get("quantity", 0))) for b in wms_batches.values())
            drug_erp_total = sum(Decimal(str(b.get("quantity", 0))) for b in erp_batches.values())

            total_wms_qty += drug_wms_total
            total_erp_qty += drug_erp_total

            if drug_wms_total != drug_erp_total:
                diff_qty = abs(drug_wms_total - drug_erp_total)
                total_diff_qty += diff_qty
                diff_items.append({
                    "drug_id": drug_id,
                    "wms_qty": float(drug_wms_total),
                    "erp_qty": float(drug_erp_total),
                    "diff_qty": float(diff_qty),
                    "diff_rate": float(diff_qty / drug_erp_total) if drug_erp_total != 0 else 1.0
                })

        if total_erp_qty == 0:
            overall_diff_rate = 0.0 if total_wms_qty == 0 else 1.0
        else:
            overall_diff_rate = float(total_diff_qty / total_erp_qty)

        if diff_items and overall_diff_rate > self.diff_threshold:
            return Result(
                False,
                f"WMS-ERP库存对账差异: {len(diff_items)}个品种不符，总体差异率{overall_diff_rate:.4%}，阈值{self.diff_threshold:.4%}",
                data={
                    "diff_items": diff_items[:10],
                    "total_diff_items": len(diff_items),
                    "overall_diff_rate": overall_diff_rate,
                    "total_wms_qty": float(total_wms_qty),
                    "total_erp_qty": float(total_erp_qty),
                    "suggestion": f"库存差异率超过阈值({self.diff_threshold:.4%})，请检查WMS与ERP数据同步机制，核对{len(diff_items)}个差异品种"
                }
            )

        return Result(
            True,
            f"WMS-ERP库存对账通过，共{total_items}个品种，总体差异率{overall_diff_rate:.4%}",
            data={
                "total_items": total_items,
                "overall_diff_rate": overall_diff_rate
            }
        )

    def _check_doc_integrity(self, release_data: Dict[str, Any]) -> Result:
        """单据完整性校验"""
        doc_statistics = release_data.get("doc_statistics", {})
        if not doc_statistics:
            return Result(False, "单据统计数据缺失",
                          data={"suggestion": "请确保能获取采购单、销售单、出入库单统计数据"})

        doc_types = [
            ("purchase_orders", "采购单"),
            ("sales_orders", "销售单"),
            ("inbound_orders", "入库单"),
            ("outbound_orders", "出库单"),
            ("check_orders", "复核单"),
        ]

        failed_types = []
        total_docs = 0
        total_incomplete = 0

        for doc_key, doc_name in doc_types:
            stats = doc_statistics.get(doc_key, {})
            total_count = stats.get("total", 0)
            incomplete_count = stats.get("incomplete", 0)

            total_docs += total_count
            total_incomplete += incomplete_count

            if total_count > 0 and incomplete_count > 0:
                incomplete_rate = incomplete_count / total_count
                if incomplete_rate > 0:
                    failed_types.append({
                        "type": doc_key,
                        "name": doc_name,
                        "total": total_count,
                        "incomplete": incomplete_count,
                        "incomplete_rate": incomplete_rate
                    })

        if failed_types:
            return Result(
                False,
                f"存在不完整单据，涉及{len(failed_types)}种单据类型，共{total_incomplete}张不完整",
                data={
                    "failed_types": failed_types,
                    "total_docs": total_docs,
                    "total_incomplete": total_incomplete,
                    "suggestion": f"以下单据存在完整性问题: {', '.join([t['name'] for t in failed_types])}，请在发布前修复数据完整性"
                }
            )

        return Result(
            True,
            f"单据完整性校验通过，共{total_docs}张单据，完整率100%",
            data={"total_docs": total_docs}
        )

    def _check_batch_consistency(self, release_data: Dict[str, Any]) -> Result:
        """批次一致性校验"""
        wms_batches = release_data.get("wms_batches", {})
        erp_batches = release_data.get("erp_batches", {})

        if not wms_batches or not erp_batches:
            return Result(False, "WMS或ERP批次数据缺失，无法校验",
                          data={"suggestion": "请确保WMS和ERP系统均可提供批次级库存数据"})

        inconsistent_batches = []
        total_batches = 0

        all_batches = set()
        for drug_batches in wms_batches.values():
            all_batches.update(drug_batches.keys())
        for drug_batches in erp_batches.values():
            all_batches.update(drug_batches.keys())

        for batch_no in all_batches:
            total_batches += 1
            wms_batch_info = None
            erp_batch_info = None

            for drug_id, batches in wms_batches.items():
                if batch_no in batches:
                    wms_batch_info = batches[batch_no]
                    break

            for drug_id, batches in erp_batches.items():
                if batch_no in batches:
                    erp_batch_info = batches[batch_no]
                    break

            is_consistent = True
            diff_fields = []

            if wms_batch_info and erp_batch_info:
                for field in ["expiry_date", "manufacturer", "specification", "quantity"]:
                    wms_val = wms_batch_info.get(field)
                    erp_val = erp_batch_info.get(field)
                    if wms_val != erp_val:
                        is_consistent = False
                        diff_fields.append({
                            "field": field,
                            "wms_value": wms_val,
                            "erp_value": erp_val
                        })

            if not is_consistent:
                inconsistent_batches.append({
                    "batch_no": batch_no,
                    "diff_fields": diff_fields
                })

        consistency_rate = (total_batches - len(inconsistent_batches)) / total_batches if total_batches > 0 else 1.0

        if inconsistent_batches:
            return Result(
                False,
                f"批次一致性校验失败，{len(inconsistent_batches)}个批次信息不一致，一致率{consistency_rate:.1%}",
                data={
                    "inconsistent_batches": inconsistent_batches[:10],
                    "total_batches": total_batches,
                    "inconsistent_count": len(inconsistent_batches),
                    "consistency_rate": consistency_rate,
                    "suggestion": f"批次信息存在差异，请核对WMS与ERP系统中的批次数据，特别是效期、生产厂家等关键信息"
                }
            )

        return Result(
            True,
            f"批次一致性校验通过，共{total_batches}个批次，一致率100%",
            data={"total_batches": total_batches}
        )
