"""Arrow recognition and blocker analysis."""

from __future__ import annotations

import cv2
import numpy as np

from babanongchang.nlgj.models import DIRECTIONS, Arrow, Board
from babanongchang.nlgj.overlay import dark_board
from babanongchang.nlgj.verification import white_board_background


def normalize(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    return cv2.resize(image, (720, round(h * 720 / w)))


def head_template() -> np.ndarray:
    template = np.zeros((35, 25), np.uint8)
    cv2.rectangle(template, (9, 2), (15, 17), 255, -1)
    cv2.fillConvexPoly(template, np.array([[4, 17], [20, 17], [12, 32]]), 255)
    return template


def topological_order(blockers: dict[int, set[int]]) -> list[int]:
    remaining = set(blockers)
    order = []
    removed = set()
    while remaining:
        ready = sorted(i for i in remaining if blockers[i] <= removed)
        if not ready:
            break
        order.extend(ready)
        remaining.difference_update(ready)
        removed.update(ready)
    return order


def match_heads(mask: np.ndarray, labels: np.ndarray, targets: set[int],
                arrows: dict[int, Arrow], template_down: np.ndarray,
                scale: float, threshold: float = .80) -> None:
    for rotation, (dx, dy) in enumerate(DIRECTIONS):
        template = np.rot90(template_down, rotation).copy()
        th, tw = template.shape
        result = cv2.matchTemplate(mask, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= threshold)
        for y, x in zip(ys, xs):
            score = float(result[y, x])
            cx, cy = int(x + tw // 2), int(y + th // 2)
            label = int(labels[cy, cx])
            previous = arrows.get(label)
            if label in targets and (previous is None or score > previous.confidence):
                arrows[label] = Arrow(label, cx, cy, dx, dy, score, scale)


def predict_removal(board: Board, label: int) -> Board:
    labels = board.labels.copy()
    labels[labels == label] = 0
    arrows = {i: arrow for i, arrow in board.arrows.items() if i != label}
    blockers = {i: dependencies - {label} for i, dependencies in board.blockers.items() if i != label}
    return Board(board.image, labels, arrows, blockers, topological_order(blockers),
                 reason="" if arrows else "No arrows", no_tap=board.no_tap)


def recognize(image: np.ndarray, top: float = .146, bottom: float = .824) -> Board:
    image = normalize(image)
    h, w = image.shape[:2]
    y0, y1 = round(h * top), round(h * bottom)
    empty = np.zeros((h, w), np.int32)
    board = Board(image, empty, {}, {}, [])
    if not white_board_background(image, top, bottom):
        board.reason = "Board is dimmed/covered or not on a white game screen"
        return board

    # Keep all dark obstacles, even when their arrowheads cannot be recognized.
    mask = dark_board(image, top, bottom, board.no_tap)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    expected = {i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 35}
    board.labels = labels
    if not expected:
        board.reason = "No arrows"
        return board
    for i in expected:
        x, y, width, height, _ = stats[i]
        if x <= 1 or x + width >= w - 1 or y <= y0 + 1 or y + height >= y1 - 1:
            board.reason = "An arrow touches the board crop; zoom out or adjust --board-top/bottom"
            return board

    base = head_template()
    # The first scale handles the current default zoom; other scales are fallback.
    scales = (1., .9, 1.1, .8, 1.2, .7, 1.3, .6, 1.45, .5, 1.6, .4, 1.75)
    for scale in scales:
        scaled = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        match_heads(mask, labels, expected, board.arrows, scaled, scale)
        if set(board.arrows) == expected:
            break
    # Dense boards rasterize tiny heads differently per scale; calibrate from the
    # most confident heads overall and the most confident head at each scale.
    ranked = sorted(board.arrows.values(), key=lambda arrow: arrow.confidence, reverse=True)
    seeds = ranked[:2]
    for arrow in ranked:
        if all(arrow.scale != seed.scale for seed in seeds):
            seeds.append(arrow)
    seeds.sort(key=lambda arrow: arrow.confidence, reverse=True)
    for seed in seeds:
        missing = expected - set(board.arrows)
        if not missing or seed.confidence < .88:
            break
        radius = max(10, round(20 * seed.scale))
        if not (radius < seed.x < w - radius and radius < seed.y < h - radius):
            continue
        patch = np.uint8(labels[seed.y - radius:seed.y + radius + 1,
                                seed.x - radius:seed.x + radius + 1] == seed.label) * 255
        rotation = DIRECTIONS.index((seed.dx, seed.dy))
        patch = np.rot90(patch, -rotation).copy()
        half_width = round(12 * seed.scale)
        template = patch[radius - round(7 * seed.scale):radius + round(17 * seed.scale) + 1,
                         radius - half_width:radius + half_width + 1]
        match_heads(mask, labels, missing, board.arrows, template, seed.scale, threshold=.86)
    # Refine scale gaps only after calibration, without replacing calibrated heads.
    # Earlier refinement can mistake tight bends for heads and skip calibration.
    sorted_scales = sorted(scales)
    for lower, upper in zip(sorted_scales, sorted_scales[1:]):
        missing = expected - set(board.arrows)
        if not missing:
            break
        scale = (lower + upper) / 2
        scaled = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        match_heads(mask, labels, missing, board.arrows, scaled, scale)
    missing = expected - set(board.arrows)
    if missing:
        board.reason = f"Unrecognized strokes/animation: {len(missing)} components"
        return board

    for label, arrow in board.arrows.items():
        x, y, dx, dy = arrow.x, arrow.y, arrow.dx, arrow.dy
        margin = max(2, round(2 * arrow.scale))
        if dx:
            rows = labels[max(0, y - margin):y + margin + 1]
            ray = rows[:, x:] if dx > 0 else rows[:, :x + 1]
        else:
            cols = labels[:, max(0, x - margin):x + margin + 1]
            ray = cols[y:] if dy > 0 else cols[:y + 1]
        # Specks below the arrow area threshold are UI residue, not obstacles.
        board.blockers[label] = set(map(int, np.unique(ray))) & expected - {label}

    board.order = topological_order(board.blockers)
    if len(board.order) != len(board.arrows):
        board.reason = "Dependency cycle or unknown obstacle; refusing to guess"
    return board


def annotate(board: Board) -> np.ndarray:
    image = board.image.copy()
    for label, arrow in board.arrows.items():
        color = (0, 150, 0) if not board.blockers.get(label) else (0, 80, 240)
        cv2.arrowedLine(image, (arrow.x, arrow.y),
                       (arrow.x + arrow.dx * 25, arrow.y + arrow.dy * 25), color, 2)
        cv2.putText(image, str(label), (arrow.x + 6, arrow.y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
    return image


def report(board: Board) -> dict:
    return {"valid": board.valid, "reason": board.reason, "arrows": len(board.arrows),
            "order": board.order,
            "ready": [i for i, deps in board.blockers.items() if not deps],
            "heads": {i: vars(a) for i, a in board.arrows.items()}}
