"""ADB device access: screenshots, taps, and ad scrolling."""

from __future__ import annotations

import re
import subprocess
import threading

import cv2
import numpy as np

from babanongchang.nlgj.recognition import normalize
from babanongchang import runtime
from babanongchang.adb_devices import list_adb_devices


class Device:
    def __init__(self, serial: str | None, adb: str = "adb") -> None:
        try:
            found = list_adb_devices(adb)
        except FileNotFoundError as exc:
            raise RuntimeError("adb not found. Install Android platform-tools first.") from exc
        devices = [item.serial for item in found if item.state == "device"]
        if serial is None:
            if len(devices) != 1:
                raise RuntimeError(f"Choose an authorized device using --serial; found {devices}")
            serial = devices[0]
        if serial not in devices:
            raise RuntimeError(f"Device {serial} is not connected/authorized")
        self.prefix = [adb, "-s", serial]
        self.width = 720
        self.height = 1600
        self.package = self.foreground()

    def command(self, *args: str) -> bytes:
        runtime.checkpoint()
        result = subprocess.check_output(self.prefix + list(args), timeout=20)
        runtime.checkpoint()
        return result

    def foreground(self) -> str:
        output = self.command("shell", "dumpsys", "activity", "activities").decode(errors="replace")
        for line in output.splitlines():
            if "topResumedActivity=" in line or "mResumedActivity:" in line:
                match = re.search(r"\bu\d+\s+([\w.]+)/", line)
                if match:
                    return match[1]
        raise RuntimeError("Cannot identify foreground app; refusing to tap")

    def screenshot(self) -> np.ndarray:
        data = self.command("exec-out", "screencap", "-p")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("Invalid ADB screenshot")
        self.width = image.shape[1]
        image = normalize(image)
        self.height = image.shape[0]
        return image

    def tap(self, x: int, y: int) -> None:
        if self.foreground() != self.package:
            raise RuntimeError("Foreground app changed; stopping instead of tapping another app")
        ratio = self.width / 720
        self.command("shell", "input", "tap", str(round(x * ratio)), str(round(y * ratio)))

    def swipe_ad(self, upwards: bool) -> None:
        if self.foreground() != self.package:
            raise RuntimeError("Foreground app changed; stopping ad browsing")
        ratio = self.width / 720
        x = round(360 * ratio)
        y_bottom, y_top = round(self.height * .78 * ratio), round(self.height * .30 * ratio)
        start, end = (y_bottom, y_top) if upwards else (y_top, y_bottom)
        self.command("shell", "input", "swipe", str(x), str(start), str(x), str(end), "650")


class AdScroller:
    def __init__(self, device: Device) -> None:
        self.device = device
        self.stopped = threading.Event()
        self.error = None
        self.swipes = 0
        self.thread = threading.Thread(target=self._run, name="ad-scroll", daemon=True)

    def _run(self) -> None:
        upwards = True
        try:
            while not self.stopped.is_set():
                runtime.checkpoint()
                self.device.swipe_ad(upwards)
                self.swipes += 1
                upwards = not upwards
        except Exception as exc:
            self.error = exc
            self.stopped.set()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=25)
