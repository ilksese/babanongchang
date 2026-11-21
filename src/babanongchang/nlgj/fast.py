"""Fast mode: tap a whole precomputed removal order at a fixed cadence."""

from __future__ import annotations

from collections.abc import Callable
from babanongchang.runtime import Clock, SYSTEM_CLOCK

from babanongchang.nlgj.device import GameDevice
from babanongchang.nlgj.models import Board
from babanongchang.nlgj.overlay import tap_point


FAST_TAP_INTERVAL = .3


def fast_sequence(board: Board) -> list[tuple[int, int, int]]:
    # A tapped arrow that can leave stops colliding immediately, so the
    # topological order stays valid without waiting for each arrow to leave.
    removed = set()
    sequence = []
    for label in board.order:
        if not board.blockers[label] <= removed:
            continue
        point = tap_point(board, label)
        if point is None:
            continue
        sequence.append((label, *point))
        removed.add(label)
    return sequence


def tap_sequence(device: GameDevice, sequence: list[tuple[int, int, int]],
                 on_tap: Callable[[int, int, int, int], None],
                 interval: float = FAST_TAP_INTERVAL, *, clock: Clock = SYSTEM_CLOCK) -> None:
    # Start-to-start cadence; taps are synchronous, so two never overlap.
    next_at = clock.monotonic()
    for index, (label, x, y) in enumerate(sequence):
        delay = next_at - clock.monotonic()
        if delay > 0:
            clock.sleep(delay)
        next_at = clock.monotonic() + interval
        on_tap(index, label, x, y)
        device.tap(x, y)
