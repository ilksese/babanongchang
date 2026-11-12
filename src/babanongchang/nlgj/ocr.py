"""Local OCR wrapper."""

from __future__ import annotations

import numpy as np


class ScreenReader:
    def __init__(self) -> None:
        self.engine = None

    def read(self, image: np.ndarray) -> list[tuple[str, float, int, int]]:
        if self.engine is None:
            from rapidocr import RapidOCR
            self.engine = RapidOCR()
        result = self.engine(image)
        if result.boxes is None or result.txts is None or result.scores is None:
            return []
        lines = []
        for box, text, confidence in zip(result.boxes, result.txts, result.scores):
            x, y = np.asarray(box).mean(axis=0)
            lines.append((text.replace(" ", ""), float(confidence), round(x), round(y)))
        return lines
