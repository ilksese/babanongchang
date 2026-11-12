"""Screen-state checks: game background, hearts, and arrow departure."""

from __future__ import annotations

import cv2
import numpy as np


def white_board_background(image: np.ndarray, top: float, bottom: float) -> bool:
    height = image.shape[0]
    brightness = np.min(image[round(height * top):round(height * bottom)], axis=2)
    white = np.count_nonzero(brightness > 235)
    background = np.count_nonzero(brightness > 120)
    return white / brightness.size >= .45 and white / max(1, background) >= .90


def heart_count(image: np.ndarray) -> int:
    h, w = image.shape[:2]
    roi = image[round(h * .065):round(h * .097), round(w * .38):round(w * .62)]
    mask = cv2.inRange(roi, (30, 30, 200), (150, 150, 255))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    return sum(int(area) > 180 for area in stats[1:, cv2.CC_STAT_AREA])


def heart_lost(previous: int | None, hearts: int, final_tap: bool = False) -> bool:
    # The victory transition shrinks a heart after the last arrow leaves; the
    # last arrow has nothing left to collide with, so it cannot cost a heart.
    return bool(previous and hearts and hearts < previous and not final_tap)


def arrow_has_left(mask: np.ndarray, original: np.ndarray,
                   count: int, previous_count: int,
                   expected_after: np.ndarray | None = None) -> bool:
    overlap = np.count_nonzero((mask > 0) & original)
    unchanged = expected_after is None or np.count_nonzero(mask != expected_after) <= 2
    return (count == previous_count - 1 and unchanged
            and overlap <= max(3, .01 * np.count_nonzero(original)))
