"""
GSP发布与智能回滚自动化平台 - 通用工具模块
"""

import os
import sys
import json
import yaml
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List


class ConfigManager:
    """配置管理器"""

    _instance = None
    _config = None

    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config(config_path)
        return cls._instance

    def _load_config(self, config_path: Optional[str] = None):
        """加载配置文件"""
        if config_path is None:
            base_dir = Path(__file__).parent.parent.parent
            config_path = base_dir / "config" / "config.yaml"

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)

    def get(self, key_path: str, default: Any = None) -> Any:
        """获取配置，支持点分隔路径，如 pre_check.gsp.enabled"""
        keys = key_path.split(".")
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_all(self) -> Dict[str, Any]:
        """获取全部配置"""
        return self._config


def setup_logger(name: str, log_level: str = "INFO", log_dir: str = "./logs") -> logging.Logger:
    """初始化日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{name}_{datetime.now().strftime('%Y%m%d')}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def generate_release_id(prefix: str = "REL") -> str:
    """生成发布ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{timestamp}"


def format_datetime(dt: Optional[datetime] = None) -> str:
    """格式化日期时间"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(dt_str: str) -> datetime:
    """解析日期时间字符串"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"无法解析日期时间: {dt_str}")


def calculate_diff_rate(current: float, baseline: float) -> float:
    """计算差异率"""
    if baseline == 0:
        return 0.0 if current == 0 else 1.0
    return abs(current - baseline) / abs(baseline)


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def save_json(data: Any, file_path: str):
    """保存JSON数据"""
    ensure_dir(os.path.dirname(file_path))
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def load_json(file_path: str) -> Any:
    """加载JSON数据"""
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_env_var(key: str, default: str = "") -> str:
    """获取环境变量"""
    return os.environ.get(key, default)


def mask_sensitive_data(data: Dict[str, Any], sensitive_keys: List[str] = None) -> Dict[str, Any]:
    """脱敏敏感数据"""
    if sensitive_keys is None:
        sensitive_keys = ["password", "api_key", "secret", "token"]

    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = mask_sensitive_data(value, sensitive_keys)
        elif key.lower() in [k.lower() for k in sensitive_keys] and value:
            result[key] = "***" + str(value)[-4:] if len(str(value)) > 4 else "***"
        else:
            result[key] = value
    return result


class Result:
    """操作结果封装"""

    def __init__(self, success: bool, message: str = "", data: Any = None, level: str = "info"):
        self.success = success
        self.message = message
        self.data = data
        self.level = level
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "level": self.level,
            "timestamp": format_datetime(self.timestamp)
        }

    def __repr__(self) -> str:
        return f"Result(success={self.success}, level={self.level}, message={self.message})"
