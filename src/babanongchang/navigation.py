from __future__ import annotations

from babanongchang import runtime as time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from babanongchang.config import PROJECT_CONFIG
from babanongchang.handle import ScreenSnapshot, WaitTimeoutError


class BackDevice(Protocol):
    def back(self) -> None: ...


class ScreenHandle(Protocol):
    def scan(self) -> ScreenSnapshot: ...


@dataclass(frozen=True)
class BackResult:
    snapshot: ScreenSnapshot
    back_count: int


def back_until(
    device: BackDevice,
    handle: ScreenHandle,
    predicate: Callable[[ScreenSnapshot], bool],
    *,
    timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
    interval: int = 1000,
    max_backs: int | None = None,
    error: str = "多次返回后仍未进入目标页面",
) -> BackResult:
    """逐次返回并重新识别，直到目标页面出现。"""
    if timeout <= 0 or interval <= 0:
        raise ValueError("timeout 和 interval 必须大于 0")
    if max_backs is not None and max_backs < 1:
        raise ValueError("max_backs 必须大于 0")

    deadline = time.monotonic() + timeout / 1000
    back_count = 0
    while time.monotonic() < deadline:
        snapshot = handle.scan()
        if predicate(snapshot):
            return BackResult(snapshot=snapshot, back_count=back_count)
        if max_backs is not None and back_count >= max_backs:
            break
        device.back()
        back_count += 1
        time.sleep(interval / 1000)
    raise WaitTimeoutError(error)
