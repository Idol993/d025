"""
仓库灰度发布引擎
- 分阶段灰度策略
- 仓库/区域逐步放量
- 观察期控制
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

from ..common.utils import format_datetime, save_json, ensure_dir, generate_release_id


class GrayReleaseStatus(str, Enum):
    """灰度发布状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    STAGE_OBSERVING = "stage_observing"
    COMPLETED = "completed"
    PAUSED = "paused"
    CIRCUIT_BROKEN = "circuit_broken"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


class GrayReleaseStage:
    """灰度发布阶段"""

    def __init__(self, stage_num: int, name: str, warehouse_types: List[str],
                 observation_hours: int, risk_level: str):
        self.stage_num = stage_num
        self.name = name
        self.warehouse_types = warehouse_types
        self.observation_hours = observation_hours
        self.risk_level = risk_level
        self.status = GrayReleaseStatus.PENDING
        self.start_time = None
        self.end_time = None
        self.metrics_history = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_num": self.stage_num,
            "name": self.name,
            "warehouse_types": self.warehouse_types,
            "observation_hours": self.observation_hours,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metrics_history_count": len(self.metrics_history)
        }


class GrayReleaseEngine:
    """灰度发布引擎"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.gray_config = config.get("gray_release", {})
        self.data_path = config.get("system", {}).get("data_path", "./data")
        self.stages_config = self.gray_config.get("stages", [])
        self.monitor_interval = self.gray_config.get("monitor", {}).get("interval_seconds", 300)

    def create_gray_release(self, release_id: str, version: str,
                            target_version: str = "") -> Dict[str, Any]:
        """创建灰度发布任务"""
        gray_id = generate_release_id("GRY")

        stages = []
        for stage_cfg in self.stages_config:
            stage = GrayReleaseStage(
                stage_num=stage_cfg["stage"],
                name=stage_cfg["name"],
                warehouse_types=stage_cfg.get("warehouse_types", []),
                observation_hours=stage_cfg.get("observation_hours", 2),
                risk_level=stage_cfg.get("risk_level", "low")
            )
            stages.append(stage)

        release_data = {
            "gray_id": gray_id,
            "release_id": release_id,
            "version": version,
            "target_version": target_version,
            "create_time": format_datetime(),
            "update_time": format_datetime(),
            "status": GrayReleaseStatus.PENDING.value,
            "current_stage": 0,
            "stages": [s.to_dict() for s in stages],
            "metrics": {},
            "events": [],
            "circuit_breaker_triggered": False,
            "rollback_triggered": False
        }

        self._save_gray_release(release_data)
        self.logger.info(f"创建灰度发布任务 {gray_id} - 发布: {release_id}, 版本: {version}")
        return release_data

    def start_release(self, gray_id: str) -> Dict[str, Any]:
        """启动灰度发布"""
        release = self._load_gray_release(gray_id)
        if not release:
            return {"success": False, "message": "灰度发布任务不存在"}

        if release["status"] != GrayReleaseStatus.PENDING.value:
            return {"success": False, "message": f"当前状态{release['status']}，无法启动"}

        release["status"] = GrayReleaseStatus.IN_PROGRESS.value
        release["current_stage"] = 1
        release["update_time"] = format_datetime()

        if release["stages"]:
            first_stage = release["stages"][0]
            first_stage["status"] = GrayReleaseStatus.IN_PROGRESS.value
            first_stage["start_time"] = format_datetime()

        self._add_event(release, "start", "灰度发布启动，进入第一阶段")
        self._save_gray_release(release)

        self.logger.info(f"灰度发布启动 {gray_id} - 进入阶段1")
        return {"success": True, "message": "灰度发布已启动", "release": release}

    def advance_stage(self, gray_id: str) -> Dict[str, Any]:
        """推进到下一阶段"""
        release = self._load_gray_release(gray_id)
        if not release:
            return {"success": False, "message": "灰度发布任务不存在"}

        current_stage_num = release.get("current_stage", 0)
        total_stages = len(release["stages"])

        if current_stage_num >= total_stages:
            release["status"] = GrayReleaseStatus.COMPLETED.value
            release["update_time"] = format_datetime()
            self._save_gray_release(release)
            return {"success": True, "message": "灰度发布已完成所有阶段", "completed": True}

        current_stage = release["stages"][current_stage_num - 1]
        current_stage["status"] = GrayReleaseStatus.COMPLETED.value
        current_stage["end_time"] = format_datetime()

        next_stage_num = current_stage_num + 1
        release["current_stage"] = next_stage_num

        if next_stage_num <= total_stages:
            next_stage = release["stages"][next_stage_num - 1]
            next_stage["status"] = GrayReleaseStatus.IN_PROGRESS.value
            next_stage["start_time"] = format_datetime()

            release["status"] = GrayReleaseStatus.STAGE_OBSERVING.value
            self._add_event(release, "stage_advance",
                          f"进入阶段{next_stage_num}: {next_stage['name']}")
        else:
            release["status"] = GrayReleaseStatus.COMPLETED.value
            self._add_event(release, "complete", "所有灰度阶段完成")

        release["update_time"] = format_datetime()
        self._save_gray_release(release)

        self.logger.info(f"灰度阶段推进 {gray_id} - 阶段{current_stage_num} -> {next_stage_num}")
        return {
            "success": True,
            "message": f"已推进到阶段{next_stage_num}",
            "current_stage": next_stage_num,
            "release": release
        }

    def pause_release(self, gray_id: str, reason: str = "") -> Dict[str, Any]:
        """暂停灰度发布"""
        release = self._load_gray_release(gray_id)
        if not release:
            return {"success": False, "message": "灰度发布任务不存在"}

        release["status"] = GrayReleaseStatus.PAUSED.value
        release["update_time"] = format_datetime()
        self._add_event(release, "pause", f"暂停发布: {reason}")
        self._save_gray_release(release)

        self.logger.info(f"灰度发布暂停 {gray_id} - 原因: {reason}")
        return {"success": True, "message": "灰度发布已暂停", "release": release}

    def resume_release(self, gray_id: str) -> Dict[str, Any]:
        """恢复灰度发布"""
        release = self._load_gray_release(gray_id)
        if not release:
            return {"success": False, "message": "灰度发布任务不存在"}

        if release["status"] != GrayReleaseStatus.PAUSED.value:
            return {"success": False, "message": "当前状态不是暂停状态"}

        release["status"] = GrayReleaseStatus.IN_PROGRESS.value
        release["update_time"] = format_datetime()
        self._add_event(release, "resume", "恢复灰度发布")
        self._save_gray_release(release)

        self.logger.info(f"灰度发布恢复 {gray_id}")
        return {"success": True, "message": "灰度发布已恢复", "release": release}

    def record_metrics(self, gray_id: str, metrics: Dict[str, Any]):
        """记录监控指标"""
        release = self._load_gray_release(gray_id)
        if not release:
            return

        timestamp = format_datetime()
        metrics_record = {
            "timestamp": timestamp,
            "stage": release.get("current_stage", 0),
            "metrics": metrics
        }

        if "metrics_history" not in release:
            release["metrics_history"] = []

        release["metrics_history"].append(metrics_record)
        release["current_metrics"] = metrics
        release["update_time"] = format_datetime()

        self._save_gray_release(release)

    def update_status_to_rolled_back(self, gray_id: str, reason: str = "",
                                rollback_level: str = "") -> Dict[str, Any]:
        """更新灰度发布状态为已熔断/已回滚"""
        release = self._load_gray_release(gray_id)
        if not release:
            return {"success": False, "message": "灰度发布任务不存在"}

        release["status"] = GrayReleaseStatus.CIRCUIT_BROKEN.value
        release["circuit_breaker_triggered"] = True
        release["rollback_triggered"] = True
        release["rollback_level"] = rollback_level
        release["rollback_reason"] = reason
        release["update_time"] = format_datetime()

        self._add_event(release, "circuit_break", f"触发熔断: {reason}")
        self._add_event(release, "rollback", f"执行{rollback_level}级回滚")

        current_stage_num = release.get("current_stage", 0)
        if current_stage_num > 0 and current_stage_num <= len(release["stages"]):
            current_stage = release["stages"][current_stage_num - 1]
            if current_stage.get("status") == GrayReleaseStatus.IN_PROGRESS.value:
                current_stage["status"] = GrayReleaseStatus.CIRCUIT_BROKEN.value
                current_stage["end_time"] = format_datetime()

        self._save_gray_release(release)

        self.logger.warning(f"灰度发布熔断 {gray_id} - 原因: {reason}, 级别: {rollback_level}")

        return {"success": True, "message": "灰度状态已更新为已熔断", "release": release}

    def check_observation_complete(self, gray_id: str) -> bool:
        """检查当前阶段观察期是否结束"""
        release = self._load_gray_release(gray_id)
        if not release:
            return False

        current_stage_num = release.get("current_stage", 0)
        if current_stage_num == 0 or current_stage_num > len(release["stages"]):
            return False

        stage = release["stages"][current_stage_num - 1]
        start_time_str = stage.get("start_time")
        if not start_time_str:
            return False

        try:
            start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
            observation_hours = stage.get("observation_hours", 2)
            elapsed = datetime.now() - start_time
            return elapsed >= timedelta(hours=observation_hours)
        except (ValueError, TypeError):
            return False

    def get_release_status(self, gray_id: str) -> Optional[Dict[str, Any]]:
        """获取灰度发布状态"""
        return self._load_gray_release(gray_id)

    def get_stage_status(self, gray_id: str, stage_num: int = None) -> Optional[Dict[str, Any]]:
        """获取阶段状态"""
        release = self._load_gray_release(gray_id)
        if not release:
            return None

        if stage_num is None:
            stage_num = release.get("current_stage", 0)

        if stage_num == 0 or stage_num > len(release["stages"]):
            return None

        return release["stages"][stage_num - 1]

    def get_release_summary(self, gray_id: str) -> str:
        """生成灰度发布摘要"""
        release = self._load_gray_release(gray_id)
        if not release:
            return "灰度发布任务不存在"

        lines = []
        lines.append("=" * 50)
        lines.append("灰度发布摘要")
        lines.append("=" * 50)
        lines.append(f"灰度ID: {release['gray_id']}")
        lines.append(f"发布ID: {release['release_id']}")
        lines.append(f"版本: {release['version']}")
        lines.append(f"状态: {release['status']}")
        lines.append(f"当前阶段: {release['current_stage']}/{len(release['stages'])}")
        lines.append("")

        lines.append("阶段详情:")
        lines.append("-" * 30)
        for stage in release["stages"]:
            status_icon = {"pending": "○", "in_progress": "●", "completed": "✓",
                          "circuit_breaker": "⚠", "rolled_back": "↺"}.get(stage["status"], "?")
            lines.append(f"  {status_icon} 阶段{stage['stage_num']}: {stage['name']} "
                        f"(风险: {stage['risk_level']}, 观察期: {stage['observation_hours']}h)")
            if stage.get("start_time"):
                lines.append(f"     开始: {stage['start_time']}")
            if stage.get("end_time"):
                lines.append(f"     结束: {stage['end_time']}")

        if release.get("events"):
            lines.append("")
            lines.append("最近事件:")
            lines.append("-" * 30)
            for event in release["events"][-5:]:
                lines.append(f"  [{event.get('time','')}] {event.get('type','')}: {event.get('detail','')}")

        lines.append("=" * 50)
        return "\n".join(lines)

    def _add_event(self, release: Dict[str, Any], event_type: str, detail: str):
        """添加事件记录"""
        if "events" not in release:
            release["events"] = []

        release["events"].append({
            "time": format_datetime(),
            "type": event_type,
            "detail": detail
        })

    def _save_gray_release(self, release: Dict[str, Any]):
        """保存灰度发布数据"""
        try:
            gray_dir = f"{self.data_path}/gray_release"
            ensure_dir(gray_dir)
            file_path = f"{gray_dir}/{release['gray_id']}.json"
            save_json(release, file_path)
        except Exception as e:
            self.logger.error(f"保存灰度发布数据失败: {e}")

    def _load_gray_release(self, gray_id: str) -> Optional[Dict[str, Any]]:
        """加载灰度发布数据"""
        import os
        file_path = f"{self.data_path}/gray_release/{gray_id}.json"
        if not os.path.exists(file_path):
            return None

        try:
            from ..common.utils import load_json
            return load_json(file_path)
        except Exception as e:
            self.logger.error(f"加载灰度发布数据失败: {e}")
            return None
