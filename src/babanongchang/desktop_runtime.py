"""Cooperative cancellation for desktop child processes."""

from __future__ import annotations

import os
from pathlib import Path
import time


CANCEL_FILE_ENV = "BABANONGCHANG_CANCEL_FILE"


class DesktopRuntimeBackend:
    def __init__(self, cancel_file: Path) -> None:
        self.cancel_file = cancel_file
        self.started = time.monotonic()

    def checkpoint(self) -> None:
        if self.cancel_file.exists():
            raise KeyboardInterrupt

    def activeMillis(self) -> int:
        self.checkpoint()
        return round((time.monotonic() - self.started) * 1000)

    def sleepMillis(self, duration: int) -> None:
        deadline = time.monotonic() + duration / 1000
        while True:
            self.checkpoint()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))


def install_from_environment() -> bool:
    path = os.environ.get(CANCEL_FILE_ENV)
    if not path:
        return False
    from babanongchang import runtime

    runtime.backend = DesktopRuntimeBackend(Path(path))
    return True
