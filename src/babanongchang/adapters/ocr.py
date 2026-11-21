import logging

import numpy as np

from babanongchang.automation.handle import OcrResult


class DesktopOcr:
    def __init__(self) -> None:
        self.engine = None

    def __call__(self, image: np.ndarray) -> OcrResult:
        if self.engine is None:
            from rapidocr import RapidOCR

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            self.engine = RapidOCR()
        return self.engine(image)
