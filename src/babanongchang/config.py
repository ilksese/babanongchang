from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # Android's OpenCV wheels currently require Python 3.10.
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_FILE_NAME = "babanongchang.toml"


@dataclass(frozen=True)
class ProjectConfig:
    screenshot_interval_ms: int = 200
    recognition_timeout_ms: int = 10000

    @property
    def screenshot_interval_seconds(self) -> float:
        return self.screenshot_interval_ms / 1000


def _positive_integer(value: Any, key: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"配置项 {key} 必须是大于 0 的整数")
    return value


def load_project_config(path: Path | None = None) -> ProjectConfig:
    config_path = path or Path.cwd() / CONFIG_FILE_NAME
    if not config_path.exists():
        return ProjectConfig()

    with config_path.open("rb") as config_file:
        data = tomllib.load(config_file)
    ocr = data.get("ocr", {})
    if not isinstance(ocr, dict):
        raise ValueError("配置项 ocr 必须是 TOML 表")

    defaults = ProjectConfig()
    return ProjectConfig(
        screenshot_interval_ms=_positive_integer(
            ocr.get("screenshot_interval_ms"),
            "ocr.screenshot_interval_ms",
            defaults.screenshot_interval_ms,
        ),
        recognition_timeout_ms=_positive_integer(
            ocr.get("recognition_timeout_ms"),
            "ocr.recognition_timeout_ms",
            defaults.recognition_timeout_ms,
        ),
    )
