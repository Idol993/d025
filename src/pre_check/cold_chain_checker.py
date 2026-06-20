"""
冷链记录完整性校验模块
- 温湿度数据采集完整性
- 报警联动测试
- 冷链断链检测
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any

from ..common.utils import Result, format_datetime


class ColdChainChecker:
    """冷链记录完整性校验器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.cc_config = config.get("pre_check", {}).get("cold_chain", {})
        self.block_levels = self.cc_config.get("block_levels", {})
        self.data_completeness_threshold = self.cc_config.get("data_completeness_threshold", 0.999)
        self.alarm_response_time = self.cc_config.get("alarm_response_time", 300)

    def run_all_checks(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行所有冷链记录完整性校验"""
        self.logger.info("开始执行冷链记录完整性校验...")

        results = {
            "module": "cold_chain",
            "check_time": format_datetime(),
            "checks": {},
            "passed": True,
            "has_warning": False,
            "block_level": "none",
            "summary": "",
            "suggestions": []
        }

        check_items = [
            ("data_completeness", self._check_temp_humidity_completeness, "温湿度数据采集完整性校验"),
            ("alarm_response", self._check_alarm_linkage, "报警联动测试"),
            ("broken_chain", self._check_broken_chain_detection, "冷链断链检测"),
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
                results["summary"] = "冷链记录完整性校验通过，存在警告项"
            else:
                results["summary"] = "冷链记录完整性校验全部通过"
        else:
            results["summary"] = f"冷链记录完整性校验未通过，{high_blocks}个核心指标不达标"

        self.logger.info(f"冷链记录完整性校验完成: {results['summary']}")
        return results

    def _is_check_enabled(self, check_key: str) -> bool:
        """检查项是否启用"""
        enable_map = {
            "data_completeness": "temp_humidity_check",
            "alarm_response": "alarm_linkage_test",
            "broken_chain": "broken_chain_detection",
        }
        config_key = enable_map.get(check_key)
        if config_key is None:
            return True
        return bool(self.cc_config.get(config_key, True))

    def _check_temp_humidity_completeness(self, release_data: Dict[str, Any]) -> Result:
        """温湿度数据采集完整性校验"""
        temp_humidity_data = release_data.get("temp_humidity_data", {})
        if not temp_humidity_data:
            return Result(False, "温湿度监控数据缺失",
                          data={"suggestion": "请确保冷链监控系统可正常访问并提供温湿度数据"})

        sensors = temp_humidity_data.get("sensors", [])
        if not sensors:
            return Result(False, "无温湿度传感器数据",
                          data={"suggestion": "请检查冷链监控系统，确认温湿度传感器配置正常"})

        sensor_results = []
        total_expected = 0
        total_actual = 0

        for sensor in sensors:
            sensor_id = sensor.get("id", "未知")
            sensor_name = sensor.get("name", sensor_id)
            expected_count = sensor.get("expected_records", 0)
            actual_count = sensor.get("actual_records", 0)
            warehouse = sensor.get("warehouse", "未知仓库")

            total_expected += expected_count
            total_actual += actual_count

            completeness = actual_count / expected_count if expected_count > 0 else 0

            sensor_results.append({
                "sensor_id": sensor_id,
                "sensor_name": sensor_name,
                "warehouse": warehouse,
                "expected": expected_count,
                "actual": actual_count,
                "completeness": completeness,
                "pass": completeness >= self.data_completeness_threshold
            })

        failed_sensors = [s for s in sensor_results if not s["pass"]]
        overall_completeness = total_actual / total_expected if total_expected > 0 else 0

        if failed_sensors:
            return Result(
                False,
                f"温湿度数据采集完整性不达标，{len(failed_sensors)}个传感器数据完整率低于阈值({self.data_completeness_threshold:.3%})，总体完整率{overall_completeness:.3%}",
                data={
                    "failed_sensors": failed_sensors,
                    "total_sensors": len(sensor_results),
                    "failed_count": len(failed_sensors),
                    "overall_completeness": overall_completeness,
                    "suggestion": f"以下传感器数据采集不完整: {', '.join([s['sensor_name'] for s in failed_sensors])}，请检查冷链设备及数据采集通道"
                }
            )

        return Result(
            True,
            f"温湿度数据采集完整性校验通过，共{len(sensor_results)}个传感器，总体完整率{overall_completeness:.3%}",
            data={
                "total_sensors": len(sensor_results),
                "overall_completeness": overall_completeness
            }
        )

    def _check_alarm_linkage(self, release_data: Dict[str, Any]) -> Result:
        """报警联动测试"""
        alarm_test_data = release_data.get("alarm_test_data", {})
        if not alarm_test_data:
            return Result(False, "报警测试数据缺失",
                          data={"suggestion": "请执行报警联动测试并提供测试结果数据"})

        test_cases = alarm_test_data.get("test_cases", [])
        if not test_cases:
            return Result(False, "无报警测试用例",
                          data={"suggestion": "请配置温湿度超标报警测试用例，验证报警联动机制"})

        test_results = []
        passed = 0
        failed = 0

        for case in test_cases:
            case_name = case.get("name", "未知测试")
            alarm_triggered = case.get("alarm_triggered", False)
            response_time = case.get("response_time_seconds", 9999)
            notification_received = case.get("notification_received", False)

            is_pass = alarm_triggered and notification_received and response_time <= self.alarm_response_time

            test_results.append({
                "case_name": case_name,
                "alarm_triggered": alarm_triggered,
                "response_time": response_time,
                "notification_received": notification_received,
                "pass": is_pass,
                "issues": [
                    issue for issue, cond in [
                        ("报警未触发", not alarm_triggered),
                        (f"响应超时({response_time}s)", response_time > self.alarm_response_time),
                        ("通知未送达", not notification_received)
                    ] if cond
                ]
            })

            if is_pass:
                passed += 1
            else:
                failed += 1

        pass_rate = passed / len(test_results) if test_results else 0

        if failed > 0:
            failed_cases = [t for t in test_results if not t["pass"]]
            return Result(
                False,
                f"报警联动测试通过率{pass_rate:.1%}，{failed}个用例失败，响应时间阈值: {self.alarm_response_time}秒",
                data={
                    "failed_cases": failed_cases,
                    "total_cases": len(test_results),
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": pass_rate,
                    "suggestion": f"以下报警测试用例失败: {'; '.join([c['case_name'] + ': ' + ','.join(c['issues']) for c in failed_cases])}，请检查报警规则配置与通知渠道"
                }
            )

        return Result(
            True,
            f"报警联动测试通过，共{len(test_results)}个测试用例，通过率100%，平均响应时间正常",
            data={"total_cases": len(test_results), "pass_rate": pass_rate}
        )

    def _check_broken_chain_detection(self, release_data: Dict[str, Any]) -> Result:
        """冷链断链检测校验"""
        broken_chain_data = release_data.get("broken_chain_data", {})
        if not broken_chain_data:
            return Result(True, "无冷链断链检测数据，默认通过")

        broken_chain_records = broken_chain_data.get("records", [])
        total_records = broken_chain_data.get("total_records", len(broken_chain_records))
        traceable_count = broken_chain_data.get("traceable_count", 0)

        untraceable = []
        for record in broken_chain_records:
            if not record.get("traceable", False):
                untraceable.append(record)

        traceable_rate = traceable_count / total_records if total_records > 0 else 1.0

        if untraceable or traceable_rate < 1.0:
            return Result(
                False,
                f"冷链断链记录可追溯率{traceable_rate:.1%}，{len(untraceable)}条记录不可追溯",
                data={
                    "untraceable_records": untraceable[:5],
                    "total_records": total_records,
                    "traceable_count": traceable_count,
                    "traceable_rate": traceable_rate,
                    "suggestion": "冷链断链记录需100%可追溯，请完善断链记录的溯源信息，包括断链原因、时间、处理措施等"
                }
            )

        return Result(
            True,
            f"冷链断链检测校验通过，共{total_records}条断链记录，可追溯率100%",
            data={"total_records": total_records, "traceable_rate": traceable_rate}
        )
