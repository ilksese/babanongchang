"""Testable model and process control for the desktop application."""

from __future__ import annotations

from dataclasses import dataclass
import json
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

from babanongchang.adb_devices import AdbDevice
from babanongchang.desktop_runtime import CANCEL_FILE_ENV
from babanongchang.launch import cli_command
from babanongchang.nlgj.options import GameOptions
from babanongchang.workflow import MIN_BROWSE_SECONDS, FarmOptions
from babanongchang.winproc import hidden_subprocess_kwargs


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
    FieldSpec("threshold", "停止施肥的肥料余额", str(FarmOptions.threshold), "int", 0),
    FieldSpec("browse_seconds", "浏览时长（秒）", f"{FarmOptions.browse_seconds:g}", minimum=MIN_BROWSE_SECONDS),
    FieldSpec("max_clicks", "最多施肥次数（留空不限）", "", "optional_int", 1),
)

NLGJ_FIELDS = (
    FieldSpec("target", "目标关卡（留空按次数）", "", "optional_int", 1),
    FieldSpec("levels", "通关次数", str(GameOptions.levels), "int", 0),
    FieldSpec("max_minutes", "最长运行时间（分钟）", f"{GameOptions.max_minutes:g}", minimum=0.01),
    FieldSpec("mode", "点击模式", GameOptions.mode, "choice", options=("safe", "fast")),
    FieldSpec("delay", "点击间隔（秒）", f"{GameOptions.delay:g}", minimum=0.01, advanced=True),
    FieldSpec("idle_timeout", "页面等待时限（秒）", f"{GameOptions.idle_timeout:g}", minimum=0.01, advanced=True),
    FieldSpec("max_restarts", "最多重开次数", str(GameOptions.max_restarts), "int", 0, advanced=True),
    FieldSpec("streak_policy", "连胜策略", GameOptions.streak_policy, "choice", options=("coins-or-abandon", "stop"), advanced=True),
    FieldSpec("revive_ads", "允许广告复活", GameOptions.revive_ads, "bool", advanced=True),
    FieldSpec("ad_timeout", "广告等待时限（秒）", f"{GameOptions.ad_timeout:g}", minimum=0.01, advanced=True),
    FieldSpec("board_top", "棋盘顶部比例", f"{GameOptions.board_top:g}", minimum=0, maximum=1, advanced=True),
    FieldSpec("board_bottom", "棋盘底部比例", f"{GameOptions.board_bottom:g}", minimum=0, maximum=1, advanced=True),
    FieldSpec("output", "输出目录", GameOptions.output.as_posix(), "directory", advanced=True),
    FieldSpec("dry_run", "仅查看设备，不点击", GameOptions.dry_run, "bool", advanced=True),
    FieldSpec("adb", "ADB 命令或路径", "adb", "text", advanced=True),
)

FEATURES = (
    FeatureSpec("all", "一键照料", "按安装情况依次照料支付宝与淘宝农场", COMMON),
    FeatureSpec("fertilize", "连续施肥", "施肥至余额阈值或达到次数限制", (COMMON[0], COMMON[2])),
    FeatureSpec("goods", "逛农货", "浏览农货页面并领取奖励", (COMMON[1],)),
    FeatureSpec("tasks", "领取任务", "识别并完成支付宝农场任务", (COMMON[1],)),
    FeatureSpec("taobao", "淘宝农场", "执行淘宝芭芭农场流程"),
    FeatureSpec("nlgj", "挪了个箭", "识别设备上的棋盘并自动闯关", NLGJ_FIELDS),
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
    target = str(values.get("target", "")).strip()
    for field in feature.fields:
        if feature_key == "nlgj" and target and field.key in ("levels", "max_minutes"):
            continue
        if field.kind in ("int", "optional_int", "float"):
            try:
                parsed[field.key] = _number(field, str(values.get(field.key, "")))
            except ValueError as exc:
                errors[field.key] = str(exc)
        elif field.kind == "choice" and values.get(field.key) not in field.options:
            errors[field.key] = f"{field.label}不是有效选项"
    if feature_key == "nlgj":
        top, bottom = parsed.get("board_top"), parsed.get("board_bottom")
        if top is not None and bottom is not None and top >= bottom:
            errors["board_bottom"] = "棋盘底部必须大于顶部"
    return errors


def effective_parameters(
    feature_key: str,
    values: Mapping[str, str | bool],
) -> tuple[tuple[str, str], ...]:
    """Return the effective, user-facing settings after dependency rules."""
    target = str(values.get("target", "")).strip()
    parameters = []
    for field in FEATURE_BY_KEY[feature_key].fields:
        if feature_key == "nlgj" and target and field.key in ("levels", "max_minutes"):
            continue
        value = values.get(field.key, field.default)
        parameters.append((field.label, "是" if value is True else "否" if value is False else str(value)))
    return tuple(parameters)


def build_arguments(
    feature_key: str,
    values: Mapping[str, str | bool],
    serial: str | None,
    log: bool = False,
) -> list[str]:
    errors = validate_settings(feature_key, values)
    if errors:
        raise ValueError(next(iter(errors.values())))
    if not serial:
        raise ValueError("请选择一台已授权设备")
    args = ["games"] if feature_key == "nlgj" else [feature_key]
    if feature_key == "nlgj":
        args.append("--nlgj")
    args.extend(("--serial", serial))

    fields = FEATURE_BY_KEY[feature_key].fields
    target = str(values.get("target", "")).strip()
    for field in fields:
        value = values.get(field.key, field.default)
        if feature_key == "nlgj" and target and field.key in ("levels", "max_minutes"):
            continue
        flag = "--" + field.key.replace("_", "-")
        if field.kind == "bool":
            if field.key == "revive_ads" and not value:
                args.append("--no-revive-ads")
            elif field.key != "revive_ads" and value:
                args.append(flag)
        elif str(value).strip() and str(value) != str(field.default):
            args.extend((flag, str(value)))
    if log:
        args.append("--debug")
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
            options.update(hidden_subprocess_kwargs(subprocess.CREATE_NEW_PROCESS_GROUP))
        else:
            options["start_new_session"] = True
        self.stop_requested = False
        program = cli_command(arguments, sys.executable)
        self.process = subprocess.Popen(
            program, cwd=cwd, env=environment, stdout=subprocess.PIPE,
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
                **hidden_subprocess_kwargs(),
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)


def resolve_nlgj_output(output: str | None) -> str:
    text = (output or "").strip() or GameOptions.output.as_posix()
    return str(Path(text).resolve())


@dataclass
class NlgjProgress:
    mode: str
    goal: int
    level: int | None = None
    completed: int = 0
    stopped: bool = False
    stop_reason: str = ""


def nlgj_progress_from_values(values: Mapping[str, str | bool]) -> NlgjProgress:
    target = str(values.get("target", "")).strip()
    if target:
        return NlgjProgress("target", int(target))
    levels = str(values.get("levels", "")).strip()
    return NlgjProgress("levels", int(levels) if levels else 0)


def observe_nlgj_log(progress: NlgjProgress, text: str) -> bool:
    changed = False
    for line in text.splitlines():
        payload = _json_object(line)
        if payload is None:
            continue
        event = payload.get("event")
        if event in {"level", "revived", "completed"}:
            level = payload.get("level")
            if _count(level) and progress.level != level:
                progress.level = level
                changed = True
        if event == "completed":
            completed = payload.get("completed")
            if _count(completed, minimum=0) and progress.completed != completed:
                progress.completed = completed
                changed = True
        if event == "stop":
            reason = str(payload.get("reason") or "")
            if not progress.stopped or progress.stop_reason != reason:
                progress.stopped = True
                progress.stop_reason = reason
                changed = True
    return changed


def progress_ratio(progress: NlgjProgress) -> tuple[int, int] | None:
    if progress.goal <= 0:
        return None
    current = progress.level if progress.mode == "target" else progress.completed
    return min(0 if current is None else current, progress.goal), progress.goal


def progress_text(progress: NlgjProgress) -> str:
    place = "等待识别关卡" if progress.level is None else f"第 {progress.level} 关"
    if progress.mode == "target" and progress.goal > 0:
        detail = f"{place} / 目标 {progress.goal}"
    elif progress.goal > 0:
        detail = f"{place} · 已通关 {progress.completed}/{progress.goal}"
    else:
        detail = place
    if not progress.stopped:
        return detail
    if _timeout_reason(progress.stop_reason):
        prefix = "超时停止"
    elif _goal_reached(progress):
        prefix = "已完成"
    else:
        prefix = "已停止"
    return f"{prefix} · {detail}"


def _json_object(line: str) -> dict[str, object] | None:
    text = line.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _count(value: object, minimum: int = 1) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _timeout_reason(reason: str) -> bool:
    lowered = reason.lower()
    return "time limit" in lowered or "timeout" in lowered


def _goal_reached(progress: NlgjProgress) -> bool:
    ratio = progress_ratio(progress)
    return ratio is not None and ratio[0] >= ratio[1]


@dataclass
class DeviceRun:
    feature_key: str
    feature_title: str
    output_dir: str | None
    status_title: str
    status_detail: str
    disconnected: bool = False
    stopping: bool = False
    model: str | None = None


class DeviceBoard:
    """Which phones are listed, which jobs are live, and the log kept for each."""

    def __init__(self) -> None:
        self.devices: dict[str, AdbDevice] = {}
        self.order: tuple[str, ...] = ()
        self.runs: dict[str, DeviceRun] = {}
        self.logs: dict[str, str] = {}
        self.results: dict[str, tuple[str, str]] = {}
        self.progress: dict[str, NlgjProgress] = {}
        self.selected: str | None = None

    def apply_devices(self, devices: tuple[AdbDevice, ...]) -> None:
        found = {device.serial: device for device in devices}
        self.devices = dict(found)
        visible = [device.serial for device in devices]
        for device in devices:
            run = self.runs.get(device.serial)
            if run is None:
                continue
            run.disconnected = False
            if device.model:
                run.model = device.model
        for serial, run in self.runs.items():
            if serial not in found:
                run.disconnected = True
                visible.append(serial)
        kept = set(visible)
        for serial in list(self.logs):
            if serial not in kept:
                del self.logs[serial]
        for serial in list(self.results):
            if serial not in kept:
                del self.results[serial]
        for serial in list(self.progress):
            if serial not in kept:
                del self.progress[serial]
        if self.selected not in kept:
            self.selected = None
        self.order = tuple(visible)

    def select(self, serial: str | None) -> None:
        if serial is not None and serial not in self.order:
            return
        self.selected = serial

    def can_start(self, serial: str | None = None) -> bool:
        chosen = self.selected if serial is None else serial
        if not chosen or chosen in self.runs:
            return False
        device = self.devices.get(chosen)
        return device is not None and device.state == "device"

    def can_stop(self, serial: str | None = None) -> bool:
        chosen = self.selected if serial is None else serial
        run = self.runs.get(chosen or "")
        return run is not None and not run.stopping

    def output_conflict(self, feature_key: str, output: str | None) -> str | None:
        if feature_key != "nlgj":
            return None
        target = resolve_nlgj_output(output)
        for run in self.runs.values():
            if run.feature_key == "nlgj" and run.output_dir == target:
                return "另一台正在把挪了个箭写入同一输出目录，请改输出目录。"
        return None

    def begin(
        self,
        serial: str,
        feature_key: str,
        feature_title: str,
        output: str | None,
        progress: NlgjProgress | None = None,
    ) -> None:
        device = self.devices.get(serial)
        self.runs[serial] = DeviceRun(
            feature_key=feature_key,
            feature_title=feature_title,
            output_dir=resolve_nlgj_output(output) if feature_key == "nlgj" else None,
            status_title="运行中",
            status_detail=f"正在执行：{feature_title}",
            model=device.model if device else None,
        )
        self.logs[serial] = ""
        self.results.pop(serial, None)
        if progress is None:
            self.progress.pop(serial, None)
        else:
            self.progress[serial] = progress

    def append_log(self, serial: str, text: str) -> bool:
        if serial not in self.logs and serial not in self.runs:
            return False
        self.logs[serial] = self.logs.get(serial, "") + text
        current = self.progress.get(serial)
        if current is None:
            return False
        return observe_nlgj_log(current, text)

    def request_stop(self, serial: str) -> None:
        run = self.runs[serial]
        run.stopping = True
        run.status_title = "正在停止"
        run.status_detail = "已请求安全停止；正在等待当前设备操作结束…"

    def finish(
        self, serial: str, *, code: int, stopped: bool, forced: bool,
        logged: bool = True, note: str = "",
    ) -> None:
        progress = self.progress.get(serial)
        if progress is not None and not progress.stopped:
            progress.stopped = True
        if forced:
            title, detail = "被强制终止", "最后一次设备操作结果可能未确认"
        elif stopped:
            title, detail = "已由用户停止", "任务已完成清理"
        elif code == 0:
            title = "已完成"
            detail = "流程正常结束；业务结果请以日志为准" if logged else "流程正常结束"
        else:
            title, detail = "运行失败", f"子进程退出码：{code}"
        if note and not logged:
            detail = f"{detail}；{note}"
        if progress is not None and progress.level is not None and not _goal_reached(progress):
            stuck = f"停在第 {progress.level} 关"
            if _timeout_reason(progress.stop_reason):
                title, detail = "超时停止", stuck
            else:
                detail = f"{detail}；{stuck}"
        self.runs.pop(serial, None)
        if serial not in self.devices:
            self.logs.pop(serial, None)
            self.results.pop(serial, None)
            self.progress.pop(serial, None)
            self.order = tuple(item for item in self.order if item != serial)
            if self.selected == serial:
                self.selected = None
            return
        self.results[serial] = (title, detail)

    def header(self) -> tuple[str, str]:
        serial = self.selected
        if serial is None:
            if self.runs:
                return f"{len(self.runs)} 台运行中", "选择一台设备查看日志"
            authorized = sum(1 for device in self.devices.values() if device.state == "device")
            detail = f"发现 {authorized} 台可用设备" if authorized else "未发现已授权设备；可检查连接后刷新"
            return "就绪", detail
        run = self.runs.get(serial)
        if run is not None:
            if run.disconnected:
                detail = "已请求安全停止；ADB 已看不到此设备" if run.stopping else "ADB 已看不到此设备，任务仍在运行"
                return "已断开", detail
            return run.status_title, run.status_detail
        if serial in self.results:
            return self.results[serial]
        device = self.devices.get(serial)
        if device is None or device.state != "device":
            return "无法开始", "设备未授权或未连接"
        return "就绪", "空闲，可开始作业"

    def row_text(self, serial: str) -> str:
        device = self.devices.get(serial)
        run = self.runs.get(serial)
        model = device.model if device is not None and device.model else None
        if model is None and run is not None:
            model = run.model
        if run is not None:
            if run.disconnected:
                state = "已断开"
            elif run.stopping:
                state = "正在停止"
            else:
                state = f"运行中 · {run.feature_title}"
            result = ""
        else:
            if device is None:
                state = "已移除"
            elif device.state == "device":
                state = "空闲"
            elif device.state == "unauthorized":
                state = "未授权"
            elif device.state == "offline":
                state = "离线"
            else:
                state = device.state
            result = self.results.get(serial, ("", ""))[0]
        text = f"{serial} · {model or '未知型号'} · {state}"
        if result:
            text += f" · {result}"
        progress = self.progress.get(serial)
        if progress is not None and progress.level is not None:
            text += f" · 第 {progress.level} 关"
        return text


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


def load_log_enabled(path: Path | None = None) -> bool:
    from babanongchang.config import CONFIG_FILE_NAME

    config_path = path or Path.cwd() / CONFIG_FILE_NAME
    if not config_path.is_file():
        return False
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return False
    app = data.get("app", {})
    return isinstance(app, dict) and app.get("log") is True


def save_log_enabled(path: Path, enabled: bool) -> None:
    import tomlkit

    document = tomlkit.parse(path.read_text(encoding="utf-8")) if path.exists() else tomlkit.document()
    if "app" not in document:
        document["app"] = tomlkit.table()
    document["app"]["log"] = bool(enabled)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
    temporary.replace(path)
