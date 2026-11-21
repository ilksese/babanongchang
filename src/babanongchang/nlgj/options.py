from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameOptions:
    levels: int = 3
    target: int | None = None
    max_minutes: float = 15
    mode: str = "safe"
    delay: float = .65
    idle_timeout: float = 35
    max_restarts: int = 0
    streak_policy: str = "coins-or-abandon"
    revive_ads: bool = True
    ad_timeout: float = 180
    board_top: float = .146
    board_bottom: float = .824
    output: Path = Path("artifacts/nlgj")
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not (0 <= self.board_top < self.board_bottom <= 1):
            raise ValueError("Require 0 <= --board-top < --board-bottom <= 1")
        if self.target is not None and self.target < 1:
            raise ValueError("Require --target >= 1")
        if min(self.levels, self.max_restarts) < 0 or min(
            self.max_minutes, self.delay, self.idle_timeout, self.ad_timeout,
        ) <= 0:
            raise ValueError("Require nonnegative --levels and positive timing values")
