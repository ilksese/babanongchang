from __future__ import annotations

import subprocess

import cv2
import numpy as np

from babanongchang.automation.handle import AutomationError
from babanongchang.runtime import Clock, SYSTEM_CLOCK


class Adb:
    def __init__(self, serial: str | None = None, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self.clock = clock
        self.prefix = ["adb"]
        if serial is None:
            serial = self._select_device()
        if serial:
            self.prefix += ["-s", serial]
        self._verify_device()
        self._run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        try:
            self._run("shell", "svc", "power", "stayon", "true")
        except (AutomationError, KeyboardInterrupt):
            self.allow_screen_sleep()
            raise

    def _run(self, *args: str, timeout: float = 30, check_cancel: bool = True) -> subprocess.CompletedProcess[bytes]:
        if check_cancel:
            self.clock.checkpoint()
        try:
            result = subprocess.run(
                [*self.prefix, *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            if check_cancel:
                self.clock.checkpoint()
            return result
        except FileNotFoundError as exc:
            raise AutomationError("找不到 adb，请先将 Android platform-tools 加入 PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise AutomationError(f"ADB 命令超时：{' '.join(args)}") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise AutomationError(f"ADB 命令失败：{detail or '未知错误'}") from exc

    def _select_device(self) -> str:
        from babanongchang.adb_devices import list_adb_devices

        found = list_adb_devices(runner=lambda command: self._run(
            *command[1:]
        ).stdout.decode("utf-8", errors="replace"))
        devices = [device.serial for device in found if device.state == "device"]
        if not devices:
            raise AutomationError("ADB 设备未连接或未授权")
        if len(devices) == 1:
            return devices[0]

        print("检测到多台已授权设备，请选择要使用的设备：")
        for index, device in enumerate(devices, start=1):
            print(f"  {index}. {device}")
        while True:
            try:
                choice = input("请输入设备序号：").strip()
            except EOFError as exc:
                raise AutomationError("未选择 ADB 设备") from exc
            if choice.isdigit() and 1 <= int(choice) <= len(devices):
                return devices[int(choice) - 1]
            print(f"请输入 1 到 {len(devices)} 之间的设备序号")

    def _verify_device(self) -> None:
        result = self._run("get-state")
        if result.stdout.decode("utf-8", errors="replace").strip() != "device":
            raise AutomationError("ADB 设备未连接或未授权")

    def screenshot(self) -> np.ndarray:
        raw = self._run("exec-out", "screencap", "-p").stdout
        if not raw:
            raise AutomationError("设备截图为空，请检查屏幕是否已锁定")
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AutomationError("无法解码设备截图")
        return image

    def tap(self, point: tuple[int, int]) -> None:
        x, y = point
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int) -> None:
        self._run(
            "shell",
            "input",
            "swipe",
            str(start[0]),
            str(start[1]),
            str(end[0]),
            str(end[1]),
            str(duration_ms),
        )

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_BACK")

    def installed_packages(self) -> set[str]:
        result = self._run("shell", "pm", "list", "packages")
        lines = result.stdout.decode("utf-8", errors="replace").splitlines()
        if any(line.strip() and not line.startswith("package:") for line in lines):
            raise AutomationError("无法读取设备已安装应用列表")
        return {line.removeprefix("package:").strip() for line in lines if line.strip()}

    def launch_package(self, package: str) -> None:
        self._run(
            "shell",
            "monkey",
            "-p",
            package,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        )

    def start_activity(self, component: str) -> None:
        self._run(
            "shell",
            "am",
            "start",
            "-W",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-f",
            "0x04000000",
            "-n",
            component,
        )

    def allow_screen_sleep(self) -> None:
        try:
            self._run("shell", "svc", "power", "stayon", "false", check_cancel=False)
        except AutomationError as exc:
            print(f"警告：恢复屏幕自动休眠失败：{exc}")
