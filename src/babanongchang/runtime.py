"""CLI uses the system clock; Android supplies a cancellable active-time clock."""

import time as _time


backend = None


def monotonic() -> float:
    return _time.monotonic() if backend is None else backend.activeMillis() / 1000


def sleep(seconds: float) -> None:
    if backend is None:
        _time.sleep(seconds)
    else:
        backend.sleepMillis(round(seconds * 1000))


def checkpoint() -> None:
    if backend is not None:
        backend.checkpoint()


def strftime(format: str) -> str:
    return _time.strftime(format)
