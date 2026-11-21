from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from babanongchang.runtime import Clock


class GameDevice(Protocol):
    @property
    def package(self) -> str: ...

    def screenshot(self) -> np.ndarray: ...

    def tap(self, x: int, y: int) -> None: ...

    def swipe_ad(self, upwards: bool) -> None: ...


class GameReader(Protocol):
    def read(self, image: np.ndarray) -> list[tuple[str, float, int, int]]: ...


class AdScroller:
    def __init__(self, device: GameDevice, clock: Clock) -> None:
        self.device = device
        self.clock = clock
        self.stopped = threading.Event()
        self.error = None
        self.swipes = 0
        self.thread = threading.Thread(target=self._run, name="ad-scroll", daemon=True)

    def _run(self) -> None:
        upwards = True
        try:
            while not self.stopped.is_set():
                self.clock.checkpoint()
                self.device.swipe_ad(upwards)
                self.swipes += 1
                upwards = not upwards
        except (Exception, KeyboardInterrupt) as exc:
            self.error = exc
            self.stopped.set()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=25)
