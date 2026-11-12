"""Board foreground extraction, app overlays, and safe tap points."""

from __future__ import annotations

import cv2
import numpy as np

from babanongchang.nlgj.models import Board


def dark_board(image: np.ndarray, top: float, bottom: float,
               no_tap: list[tuple[int, int, int, int]] | None = None) -> np.ndarray:
    mask = cv2.inRange(image, (0, 0, 0), (115, 100, 100))
    # A blocked arrow turns red and remains a real obstacle on this game's board.
    red = cv2.inRange(image, (40, 25, 180), (180, 160, 255))
    mask = cv2.bitwise_or(mask, red)
    h = mask.shape[0]
    mask[:round(h * top)] = 0
    mask[round(h * bottom):] = 0
    return remove_edge_overlays(mask, no_tap)


def remove_edge_overlays(mask: np.ndarray,
                         no_tap: list[tuple[int, int, int, int]] | None = None) -> np.ndarray:
    # Floating side buttons are solid blobs anchored to the screen edge; arrow strokes stay thin.
    w = mask.shape[1]
    unit = w / 720
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    distance = None
    for i in range(1, count):
        x, width = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_WIDTH]
        if x > 3 * unit and x + width < w - 3 * unit:
            continue
        if distance is None:
            distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        component = labels == i
        if distance[component].max() >= 8 * unit:
            mask[component] = 0
            if no_tap is not None:
                y, height = stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_HEIGHT]
                # Blob (2,682)-(46,756) had touch bounds (2,594)-(76,800); keep a small margin.
                inward, up, down = round(36 * unit), round(96 * unit), round(52 * unit)
                x0 = 0 if x <= 3 * unit else x - inward
                x1 = w - 1 if x + width >= w - 3 * unit else x + width + inward
                no_tap.append((int(x0), int(y - up), int(x1), int(y + height + down)))
    return mask


def tap_point(board: Board, label: int) -> tuple[int, int] | None:
    arrow = board.arrows[label]

    def blocked(x: int, y: int) -> bool:
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in board.no_tap)

    if not blocked(arrow.x, arrow.y):
        return arrow.x, arrow.y
    # Tap the arrow body instead: the stroke center farthest from any overlay.
    body = np.uint8(board.labels == label)
    distance = cv2.distanceTransform(body, cv2.DIST_L2, 3)
    ys, xs = np.nonzero(body)
    keep = np.array([not blocked(int(x), int(y)) for x, y in zip(xs, ys)], bool)
    if not keep.any():
        return None
    xs, ys = xs[keep], ys[keep]
    depth = distance[ys, xs]
    center = depth >= depth.max() - .5
    xs, ys = xs[center], ys[center]
    gap = np.full(len(xs), np.inf)
    for x0, y0, x1, y1 in board.no_tap:
        dx = np.maximum(np.maximum(x0 - xs, xs - x1), 0)
        dy = np.maximum(np.maximum(y0 - ys, ys - y1), 0)
        gap = np.minimum(gap, np.hypot(dx, dy))
    best = int(np.argmax(gap))
    return int(xs[best]), int(ys[best])
