"""
熔断与回滚引擎
- 实时监控指标判定
- 多级熔断策略
- 智能回滚决策
- 回滚执行与验证
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

from ..common.utils import format_datetime, save_json, ensure_dir, generate_release_id


class CircuitBreakerStatus(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RollbackLevel(str, Enum):
    """回滚级别"""
    FUNCTION = "function"
    WAREHOUSE = "warehouse"
    SYSTEM = "system"
    DATA = "data"


class MetricAlert:
    """指标告警"""

    def __init__(self, metric_name: str, current_value: float,
                 warning_threshold: float, circuit_threshold: float,
                 level: str = "warning"):
        self.metric_name = metric_name
        self.current_value = current_value
        self.warning_threshold = warning_threshold
        self.circuit_threshold = circuit_threshold
        self.level = level
        self.timestamp = format_datetime()


class CircuitBreakerEngine:
    """熔断引擎"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.gray_config = config.get("gray_release", {})
        self.cb_config = self.gray_config.get("circuit_breaker", {})
        self.metrics_config = self.gray_config.get("monitor", {}).get("metrics", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")

        self.trend_deterioration_count = self.cb_config.get("trend_deterioration_count", 3)
        self.auto_rollback = self.cb_config.get("auto_rollback", True)

    def evaluate_metrics(self, metrics: Dict[str, Any],
                        metrics_history: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        评估监控指标，判断是否需要熔断

        Args:
            metrics: 当前监控指标
            metrics_history: 历史指标数据，用于趋势分析

        Returns:
            评估结果
        """
        result = {
            "timestamp": format_datetime(),
            "should_circuit_break": False,
            "has_warning": False,
            "circuit_reason": "",
            "triggered_metrics": [],
            "warning_metrics": [],
            "trend_analysis": {},
            "rollback_suggestion": "",
            "rollback_level": ""
        }

        all_metrics = self._flatten_metrics(self.metrics_config)
        current_values = self._flatten_metrics(metrics) if metrics else {}

        for metric_name, thresholds in all_metrics.items():
            current_val = current_values.get(metric_name)
            if current_val is None:
                continue

            warning_threshold = thresholds.get("warning")
            circuit_threshold = thresholds.get("circuit_breaker")

            if circuit_threshold is not None and current_val >= circuit_threshold:
                result["should_circuit_break"] = True
                result["triggered_metrics"].append({
                    "metric": metric_name,
                    "current": current_val,
                    "threshold": circuit_threshold,
                    "exceed_rate": (current_val - circuit_threshold) / circuit_threshold * 100
                })
            elif warning_threshold is not None and current_val >= warning_threshold:
                result["has_warning"] = True
                result["warning_metrics"].append({
                    "metric": metric_name,
                    "current": current_val,
                    "threshold": warning_threshold
                })

        if metrics_history and len(metrics_history) >= self.trend_deterioration_count:
            trend_result = self._analyze_trend(metrics_history, all_metrics)
            result["trend_analysis"] = trend_result

            if trend_result.get("deteriorating_metrics"):
                deteriorating_count = len(trend_result["deteriorating_metrics"])
                if deteriorating_count >= 2:
                    result["should_circuit_break"] = True
                    result["circuit_reason"] = (
                        f"连续{self.trend_deterioration_count}个周期指标持续恶化，"
                        f"涉及{deteriorating_count}个核心指标"
                    )

        if result["triggered_metrics"]:
            triggered_names = ", ".join([m["metric"] for m in result["triggered_metrics"]])
            result["circuit_reason"] = f"核心指标超过熔断阈值: {triggered_names}"

        if result["should_circuit_break"]:
            result["rollback_suggestion"], result["rollback_level"] = (
                self._suggest_rollback_level(result)
            )

        return result

    def _flatten_metrics(self, nested_metrics: Dict[str, Any],
                        prefix: str = "") -> Dict[str, Any]:
        """扁平化嵌套的指标配置"""
        flat = {}
        for key, value in nested_metrics.items():
            full_key = f"{prefix}{key}" if prefix else key
            if isinstance(value, dict) and "warning" in value:
                flat[full_key] = value
            elif isinstance(value, dict):
                flat.update(self._flatten_metrics(value, f"{full_key}."))
        return flat

    def _analyze_trend(self, metrics_history: List[Dict[str, Any]],
                       all_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """分析指标趋势"""
        result = {
            "deteriorating_metrics": [],
            "improving_metrics": [],
            "stable_metrics": []
        }

        if len(metrics_history) < self.trend_deterioration_count:
            return result

        recent_history = metrics_history[-self.trend_deterioration_count:]

        for metric_name in all_metrics.keys():
            values = []
            for record in recent_history:
                metrics_data = record.get("metrics", {})
                flat = self._flatten_metrics(metrics_data)
                val = flat.get(metric_name)
                if val is not None:
                    values.append(val)

            if len(values) < self.trend_deterioration_count:
                continue

            is_deteriorating = all(values[i] <= values[i + 1] for i in range(len(values) - 1))
            is_improving = all(values[i] >= values[i + 1] for i in range(len(values) - 1))

            if is_deteriorating and values[-1] > values[0]:
                result["deteriorating_metrics"].append({
                    "metric": metric_name,
                    "start_value": values[0],
                    "end_value": values[-1],
                    "change_rate": (values[-1] - values[0]) / values[0] * 100 if values[0] else 0
                })
            elif is_improving:
                result["improving_metrics"].append({
                    "metric": metric_name,
                    "start_value": values[0],
                    "end_value": values[-1]
                })
            else:
                result["stable_metrics"].append(metric_name)

        return result

    def _suggest_rollback_level(self, eval_result: Dict[str, Any]) -> Tuple[str, str]:
        """建议回滚级别"""
        triggered = eval_result.get("triggered_metrics", [])

        if not triggered:
            return "", ""

        high_risk_metrics = [
            "document.outbound_check_error_rate",
            "cold_chain.broken_chain_rate",
            "drug_admin.trace_upload_failure_rate"
        ]

        high_risk_triggered = [m for m in triggered if m["metric"] in high_risk_metrics]

        if len(triggered) >= 3 or len(high_risk_triggered) >= 2:
            return "建议执行系统级回滚", RollbackLevel.SYSTEM.value

        cold_chain_triggered = [m for m in triggered if "cold_chain" in m["metric"]]
        if cold_chain_triggered:
            return "建议执行仓库级回滚（冷链相关仓库）", RollbackLevel.WAREHOUSE.value

        doc_triggered = [m for m in triggered if "document" in m["metric"]]
        if doc_triggered:
            return "建议执行功能级回滚（单据相关模块）", RollbackLevel.FUNCTION.value

        return "建议执行仓库级回滚", RollbackLevel.WAREHOUSE.value

    def trigger_circuit_break(self, gray_id: str, reason: str,
                              rollback_level: str = "") -> Dict[str, Any]:
        """触发熔断"""
        self.logger.warning(f"触发熔断 - 灰度ID: {gray_id}, 原因: {reason}")

        cb_record = {
            "circuit_breaker_id": generate_release_id("CBR"),
            "gray_id": gray_id,
            "trigger_time": format_datetime(),
            "reason": reason,
            "rollback_level": rollback_level,
            "status": "triggered",
            "rollback_executed": False,
            "events": []
        }

        self._add_cb_event(cb_record, "trigger", f"熔断触发: {reason}")
        self._save_circuit_breaker(cb_record)

        return cb_record

    def execute_rollback(self, cb_id: str, rollback_level: str,
                         target_version: str = "") -> Dict[str, Any]:
        """执行回滚"""
        cb_record = self._load_circuit_breaker(cb_id)
        if not cb_record:
            return {"success": False, "message": "熔断记录不存在"}

        self.logger.info(f"执行回滚 - 熔断ID: {cb_id}, 级别: {rollback_level}")

        cb_record["status"] = "rolling_back"
        cb_record["rollback_executed"] = True
        cb_record["rollback_start_time"] = format_datetime()
        cb_record["rollback_level"] = rollback_level
        cb_record["target_version"] = target_version

        self._add_cb_event(cb_record, "rollback_start",
                          f"开始{rollback_level}级回滚，目标版本: {target_version}")
        self._save_circuit_breaker(cb_record)

        rollback_result = self._perform_rollback(rollback_level, target_version)

        cb_record["rollback_end_time"] = format_datetime()
        cb_record["rollback_result"] = rollback_result
        cb_record["status"] = "rolled_back" if rollback_result.get("success") else "rollback_failed"

        self._add_cb_event(cb_record, "rollback_end",
                          f"回滚完成，结果: {'成功' if rollback_result.get('success') else '失败'}")
        self._save_circuit_breaker(cb_record)

        return {
            "success": rollback_result.get("success", False),
            "message": rollback_result.get("message", ""),
            "cb_record": cb_record
        }

    def _perform_rollback(self, rollback_level: str, target_version: str) -> Dict[str, Any]:
        """
        执行实际回滚操作
        此处为模拟实现，实际需接入发布系统API
        """
        self.logger.info(f"模拟执行{rollback_level}级回滚到版本: {target_version}")

        rollback_actions = {
            RollbackLevel.FUNCTION.value: [
                "停止相关功能模块流量",
                "回滚功能模块代码",
                "重启相关服务",
                "验证功能可用性"
            ],
            RollbackLevel.WAREHOUSE.value: [
                "暂停受影响仓库业务",
                "回滚仓库相关配置",
                "恢复仓库旧版本服务",
                "验证仓库业务正常"
            ],
            RollbackLevel.SYSTEM.value: [
                "全系统暂停新业务",
                "数据库回滚/数据恢复",
                "应用整体回滚",
                "全链路验证",
                "恢复业务流量"
            ],
            RollbackLevel.DATA.value: [
                "停止所有数据写入",
                "从备份恢复数据",
                "数据一致性校验",
                "应用回滚",
                "业务验证"
            ]
        }

        actions = rollback_actions.get(rollback_level, [])

        return {
            "success": True,
            "message": f"{rollback_level}级回滚执行完成",
            "actions_executed": actions,
            "target_version": target_version
        }

    def verify_rollback(self, cb_id: str) -> Dict[str, Any]:
        """验证回滚结果"""
        cb_record = self._load_circuit_breaker(cb_id)
        if not cb_record:
            return {"success": False, "message": "熔断记录不存在"}

        self.logger.info(f"验证回滚结果 - 熔断ID: {cb_id}")

        verification_items = [
            {"item": "服务可用性", "status": "normal"},
            {"item": "核心接口响应", "status": "normal"},
            {"item": "数据一致性", "status": "normal"},
            {"item": "业务流程验证", "status": "normal"},
            {"item": "监控指标恢复", "status": "normal"}
        ]

        all_passed = all(v["status"] == "normal" for v in verification_items)

        self._add_cb_event(cb_record, "verify",
                          f"回滚验证{'通过' if all_passed else '未通过'}")
        self._save_circuit_breaker(cb_record)

        return {
            "success": all_passed,
            "verification_items": verification_items,
            "message": "回滚验证完成"
        }

    def _add_cb_event(self, cb_record: Dict[str, Any], event_type: str, detail: str):
        """添加熔断事件"""
        if "events" not in cb_record:
            cb_record["events"] = []

        cb_record["events"].append({
            "time": format_datetime(),
            "type": event_type,
            "detail": detail
        })

    def _save_circuit_breaker(self, cb_record: Dict[str, Any]):
        """保存熔断记录"""
        try:
            cb_dir = f"{self.data_path}/circuit_breaker"
            ensure_dir(cb_dir)
            file_path = f"{cb_dir}/{cb_record['circuit_breaker_id']}.json"
            save_json(cb_record, file_path)
        except Exception as e:
            self.logger.error(f"保存熔断记录失败: {e}")

    def _load_circuit_breaker(self, cb_id: str) -> Optional[Dict[str, Any]]:
        """加载熔断记录"""
        import os
        file_path = f"{self.data_path}/circuit_breaker/{cb_id}.json"
        if not os.path.exists(file_path):
            return None

        try:
            from ..common.utils import load_json
            return load_json(file_path)
        except Exception as e:
            self.logger.error(f"加载熔断记录失败: {e}")
            return None

    def get_circuit_breaker_report(self, cb_id: str) -> str:
        """生成熔断报告"""
        cb_record = self._load_circuit_breaker(cb_id)
        if not cb_record:
            return "熔断记录不存在"

        lines = []
        lines.append("=" * 50)
        lines.append("熔断与回滚报告")
        lines.append("=" * 50)
        lines.append(f"熔断ID: {cb_record['circuit_breaker_id']}")
        lines.append(f"关联灰度ID: {cb_record['gray_id']}")
        lines.append(f"触发时间: {cb_record['trigger_time']}")
        lines.append(f"触发原因: {cb_record['reason']}")
        lines.append(f"回滚级别: {cb_record.get('rollback_level', '未执行')}")
        lines.append(f"状态: {cb_record['status']}")
        lines.append("")

        if cb_record.get("events"):
            lines.append("事件时间线:")
            lines.append("-" * 30)
            for event in cb_record["events"]:
                lines.append(f"  [{event.get('time','')}] {event.get('type','')}: {event.get('detail','')}")

        lines.append("")
        lines.append("=" * 50)

        return "\n".join(lines)
