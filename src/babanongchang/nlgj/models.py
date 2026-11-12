"""Board geometry shared by recognition, verification, and tapping."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


DIRECTIONS = ((0, 1), (1, 0), (0, -1), (-1, 0))


@dataclass
class Arrow:
    label: int
    x: int
    y: int
    dx: int
    dy: int
    confidence: float
    scale: float


@dataclass
class Board:
    image: np.ndarray
    labels: np.ndarray
    arrows: dict[int, Arrow]
    blockers: dict[int, set[int]]
    order: list[int]
    reason: str = ""
    # Screen rectangles (x0, y0, x1, y1) where taps would hit an app overlay.
    no_tap: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return bool(self.arrows) and not self.reason
