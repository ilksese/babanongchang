from __future__ import annotations

import re
import time
from typing import Iterable, Protocol

import numpy as np


class SwipeDevice(Protocol):
    def screenshot(self) -> np.ndarray: ...

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int) -> None: ...


def find_browse_iteration(texts: Iterable[str]) -> int | None:
    """从页面文案中解析“第 n 次”，仅支持阿拉伯数字。"""
    iterations = []
    for text in texts:
        iterations.extend(int(value) for value in re.findall(r"第\s*(\d+)\s*次", text))
    positive_iterations = [iteration for iteration in iterations if iteration > 0]
    return max(positive_iterations, default=None)


def swipe_browse(device: SwipeDevice, duration_seconds: float = 18) -> None:
    """在当前页面上下往复滑动指定时间。"""
    if duration_seconds <= 0:
        raise ValueError("浏览时长必须大于 0")

    image = device.screenshot()
    height, width = image.shape[:2]
    upper = (width // 2, int(height * 0.36))
    lower = (width // 2, int(height * 0.74))
    deadline = time.monotonic() + duration_seconds
    downward = True
    print(f"开始上下往复滑动 {duration_seconds:g} 秒")
    while time.monotonic() < deadline:
        start, end = (upper, lower) if downward else (lower, upper)
        device.swipe(start, end, duration_ms=650)
        downward = not downward
        time.sleep(0.2)
    print("浏览时间已满足，准备返回")
