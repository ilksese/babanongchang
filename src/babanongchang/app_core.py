"""Testable model and process control for the desktop application."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from typing import Callable, Mapping

from babanongchang.desktop_runtime import CANCEL_FILE_ENV


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    default: str | bool
    kind: str = "float"
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[str, ...] = ()
    advanced: bool = False


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    title: str
    description: str
    fields: tuple[FieldSpec, ...] = ()


COMMON = (
    FieldSpec("threshold", "停止施肥的肥料余额", "600", "int", 0),
    FieldSpec("browse_seconds", "浏览时长（秒）", "18", minimum=15),
    FieldSpec("max_clicks", "最多施肥次数（留空不限）", "", "optional_int", 1),
)

NLGJ_FIELDS = (
    FieldSpec("target", "目标关卡（留空按次数）", "", "optional_int", 1),
    FieldSpec("levels", "通关次数", "3", "int", 0),
    FieldSpec("max_minutes", "最长运行时间（分钟）", "15", minimum=0.01),
    FieldSpec("mode", "点击模式", "safe", "choice", options=("safe", "fast")),
    FieldSpec("delay", "点击间隔（秒）", "0.65", minimum=0.01, advanced=True),
    FieldSpec("idle_timeout", "页面等待时限（秒）", "35", minimum=0.01, advanced=True),
    FieldSpec("max_restarts", "最多重开次数", "0", "int", 0, advanced=True),
    FieldSpec("streak_policy", "连胜策略", "coins-or-abandon", "choice", options=("coins-or-abandon", "stop"), advanced=True),
    FieldSpec("revive_ads", "允许广告复活", True, "bool", advanced=True),
    FieldSpec("ad_timeout", "广告等待时限（秒）", "180", minimum=0.01, advanced=True),
    FieldSpec("board_top", "棋盘顶部比例", "0.146", minimum=0, maximum=1, advanced=True),
    FieldSpec("board_bottom", "棋盘底部比例", "0.824", minimum=0, maximum=1, advanced=True),
    FieldSpec("output", "输出目录", "artifacts/nlgj", "directory", advanced=True),
    FieldSpec("dry_run", "仅查看设备，不点击", False, "bool", advanced=True),
    FieldSpec("screenshot", "离线截图", "", "file"),
    FieldSpec("ocr", "离线报告包含 OCR", False, "bool", advanced=True),
    FieldSpec("adb", "ADB 命令或路径", "adb", "text", advanced=True),
)

FEATURES = (
    FeatureSpec("all", "一键照料", "按安装情况依次照料支付宝与淘宝农场", COMMON),
    FeatureSpec("fertilize", "连续施肥", "施肥至余额阈值或达到次数限制", (COMMON[0], COMMON[2])),
    FeatureSpec("goods", "逛农货", "浏览农货页面并领取奖励", (COMMON[1],)),
    FeatureSpec("tasks", "领取任务", "识别并完成支付宝农场任务", (COMMON[1],)),
    FeatureSpec("taobao", "淘宝农场", "执行淘宝芭芭农场流程"),
    FeatureSpec("nlgj", "挪了个箭", "在线闯关，或离线分析一张截图", NLGJ_FIELDS),
)
FEATURE_BY_KEY = {feature.key: feature for feature in FEATURES}


def defaults_for(feature: FeatureSpec) -> dict[str, str | bool]:
    return {field.key: field.default for field in feature.fields}


def _number(field: FieldSpec, value: str) -> int | float | None:
    if not value.strip() and field.kind == "optional_int":
        return None
    try:
        number = int(value) if field.kind in ("int", "optional_int") else float(value)
    except ValueError as exc:
        raise ValueError(f"{field.label}必须是数字") from exc
    if field.minimum is not None and number < field.minimum:
        raise ValueError(f"{field.label}不能小于 {field.minimum:g}")
    if field.maximum is not None and number > field.maximum:
        raise ValueError(f"{field.label}不能大于 {field.maximum:g}")
    return number


def validate_settings(feature_key: str, values: Mapping[str, str | bool]) -> dict[str, str]:
    errors: dict[str, str] = {}
    feature = FEATURE_BY_KEY[feature_key]
    parsed: dict[str, int | float | None] = {}
    screenshot = str(values.get("screenshot", "")).strip()
    target = str(values.get("target", "")).strip()
    offline_fields = {"screenshot", "ocr", "output", "board_top", "board_bottom"}
    for field in feature.fields:
        if feature_key == "nlgj":
            if screenshot and field.key not in offline_fields and field.key != "dry_run":
                continue
            if target and field.key in ("levels", "max_minutes"):
                continue
        if field.kind in ("int", "optional_int", "float"):
            try:
                parsed[field.key] = _number(field, str(values.get(field.key, "")))
            except ValueError as exc:
                errors[field.key] = str(exc)
        elif field.kind == "choice" and values.get(field.key) not in field.options:
            errors[field.key] = f"{field.label}不是有效选项"
    if feature_key == "nlgj":
        if screenshot and not Path(screenshot).is_file():
            errors["screenshot"] = "离线截图文件不存在"
        if not screenshot and bool(values.get("ocr")):
            errors["ocr"] = "OCR 分析仅用于离线截图"
        if screenshot and bool(values.get("dry_run")):
            errors["dry_run"] = "离线截图与设备只读模式不能同时使用"
        top, bottom = parsed.get("board_top"), parsed.get("board_bottom")
        if top is not None and bottom is not None and top >= bottom:
            errors["board_bottom"] = "棋盘底部必须大于顶部"
    return errors


def requires_device(feature_key: str, values: Mapping[str, str | bool]) -> bool:
    return not (feature_key == "nlgj" and str(values.get("screenshot", "")).strip())


def effective_parameters(
    feature_key: str,
    values: Mapping[str, str | bool],
) -> tuple[tuple[str, str], ...]:
    """Return the effective, user-facing settings after dependency rules."""
    screenshot = str(values.get("screenshot", "")).strip()
    target = str(values.get("target", "")).strip()
    offline_fields = {"screenshot", "ocr", "output", "board_top", "board_bottom"}
    parameters = []
    for field in FEATURE_BY_KEY[feature_key].fields:
        if feature_key == "nlgj":
            if screenshot and field.key not in offline_fields:
                continue
            if target and field.key in ("levels", "max_minutes"):
                continue
        value = values.get(field.key, field.default)
        parameters.append((field.label, "是" if value is True else "否" if value is False else str(value)))
    return tuple(parameters)


def build_arguments(
    feature_key: str,
    values: Mapping[str, str | bool],
    serial: str | None,
) -> list[str]:
    errors = validate_settings(feature_key, values)
    if errors:
        raise ValueError(next(iter(errors.values())))
    if requires_device(feature_key, values) and not serial:
        raise ValueError("请选择一台已授权设备")
    args = ["games"] if feature_key == "nlgj" else [feature_key]
    if feature_key == "nlgj":
        args.append("--nlgj")
    if serial and requires_device(feature_key, values):
        args.extend(("--serial", serial))

    fields = FEATURE_BY_KEY[feature_key].fields
    screenshot = str(values.get("screenshot", "")).strip()
    for field in fields:
        value = values.get(field.key, field.default)
        if feature_key == "nlgj":
            if screenshot and field.key not in ("screenshot", "ocr", "output", "board_top", "board_bottom"):
                continue
            if values.get("target") and field.key in ("levels", "max_minutes"):
                continue
        flag = "--" + field.key.replace("_", "-")
        if field.kind == "bool":
            if field.key == "revive_ads" and not value:
                args.append("--no-revive-ads")
            elif field.key != "revive_ads" and value:
                args.append(flag)
        elif str(value).strip() and str(value) != str(field.default):
            args.extend((flag, str(value)))
    return args


class TaskProcess:
    """One CLI child process with cooperative and forced stop boundaries."""

    def __init__(self, events: queue.Queue[tuple[str, object]]) -> None:
        self.events = events
        self.process: subprocess.Popen[str] | None = None
        self.control_dir: Path | None = None
        self.cancel_file: Path | None = None
        self.stop_requested = False

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, arguments: list[str], cwd: Path) -> None:
        if self.running:
            raise RuntimeError("已有任务正在运行")
        self.control_dir = Path(tempfile.mkdtemp(prefix="babanongchang-"))
        self.cancel_file = self.control_dir / "cancel"
        environment = os.environ.copy()
        environment[CANCEL_FILE_ENV] = str(self.cancel_file)
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        command = [sys.executable, "-m", "babanongchang.cli", *arguments]
        options: dict[str, object] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self.stop_requested = False
        self.process = subprocess.Popen(
            command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, **options,
        )
        threading.Thread(target=self._read, name="app-cli-output", daemon=True).start()

    def _read(self) -> None:
        process = self.process
        assert process is not None and process.stdout is not None
        try:
            for line in process.stdout:
                self.events.put(("log", line))
        finally:
            process.stdout.close()
        code = process.wait()
        self.events.put(("exit", (code, self.stop_requested)))
        if self.control_dir is not None:
            shutil.rmtree(self.control_dir, ignore_errors=True)

    def request_stop(self) -> None:
        if self.running and self.cancel_file is not None:
            self.stop_requested = True
            self.cancel_file.touch()

    def force_stop(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)


def save_ocr_config(path: Path, screenshot_interval_ms: int, recognition_timeout_ms: int) -> None:
    if min(screenshot_interval_ms, recognition_timeout_ms) <= 0:
        raise ValueError("OCR 配置必须是大于 0 的整数")
    import tomlkit

    document = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    if "ocr" not in document:
        document["ocr"] = tomlkit.table()
    document["ocr"]["screenshot_interval_ms"] = screenshot_interval_ms
    document["ocr"]["recognition_timeout_ms"] = recognition_timeout_ms
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
    temporary.replace(path)
