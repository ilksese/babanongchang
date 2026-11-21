"""Cooperative cancellation for desktop child processes."""

from __future__ import annotations

import os
from pathlib import Path
import time

from babanongchang.runtime import Clock, SYSTEM_CLOCK


CANCEL_FILE_ENV = "BABANONGCHANG_CANCEL_FILE"


class DesktopRuntimeBackend:
    def __init__(self, cancel_file: Path) -> None:
        self.cancel_file = cancel_file
        self.started = time.monotonic()

    def checkpoint(self) -> None:
        if self.cancel_file.exists():
            raise KeyboardInterrupt

    def monotonic(self) -> float:
        self.checkpoint()
        return time.monotonic() - self.started

    def sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while True:
            self.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))


def clock_from_environment() -> Clock:
    path = os.environ.get(CANCEL_FILE_ENV)
    return DesktopRuntimeBackend(Path(path)) if path else SYSTEM_CLOCK
