import numpy as np

from babanongchang.logs import apply_library_logging
from babanongchang.automation.handle import OcrResult


class DesktopOcr:
    def __init__(self) -> None:
        self.engine = None

    def __call__(self, image: np.ndarray) -> OcrResult:
        if self.engine is None:
            from rapidocr import RapidOCR

            apply_library_logging()
            self.engine = RapidOCR()
        return self.engine(image)
