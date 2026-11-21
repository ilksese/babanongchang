import json
from pathlib import Path

import cv2
import numpy as np


class AndroidClock:
    def __init__(self, bridge):
        self.bridge = bridge

    def monotonic(self) -> float:
        return self.bridge.activeMillis() / 1000

    def sleep(self, seconds: float) -> None:
        self.bridge.sleepMillis(round(seconds * 1000))

    def checkpoint(self) -> None:
        self.bridge.checkpoint()


class AndroidOcr:
    def __init__(self, bridge):
        self.bridge = bridge
        self.engine = None

    def _load_engine(self):
        import babanongchang_ocr_models
        from rapidocr import RapidOCR

        root = Path(babanongchang_ocr_models.__file__).parent
        return RapidOCR(params={
            f"{name}.model_path": str(root / f"{name}.onnx")
            for name in ("Det", "Cls", "Rec")
        })

    def __call__(self, image):
        self.bridge.checkpoint()
        if self.engine is None:
            self.engine = self._load_engine()
        result = self.engine(image)
        self.bridge.checkpoint()
        return result

    def close(self):
        if self.engine is not None:
            for name in ("text_det", "text_cls", "text_rec"):
                model = getattr(self.engine, name)
                if model is not None:
                    model.session.session.close()
            self.engine = None


class AndroidDevice:
    def __init__(self, bridge):
        self.bridge = bridge
        self.ocr = AndroidOcr(bridge)

    def screenshot(self):
        data = bytes(self.bridge.capture())
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("无法解码无障碍截图")
        return image

    def tap(self, point):
        self.bridge.tap(int(point[0]), int(point[1]))

    def swipe(self, start, end, duration_ms):
        self.bridge.swipe(*map(int, (*start, *end)), int(duration_ms))

    def back(self):
        self.bridge.back()

    def installed_packages(self):
        return set(json.loads(str(self.bridge.installedPackages())))

    def launch_package(self, package):
        self.bridge.launch(package, "")

    def start_activity(self, component):
        package, activity = component.split("/", 1)
        self.bridge.launch(package, activity)

class AndroidGameDevice:
    def __init__(self, device):
        self.device = device
        self.width = 720
        self.height = 1600
        self.package = self.foreground()

    def foreground(self):
        return str(self.device.bridge.foreground())

    def screenshot(self):
        from babanongchang.nlgj.recognition import normalize

        if self.foreground() != self.package:
            raise RuntimeError("前台应用已切换，停止游戏")
        image = self.device.screenshot()
        self.width = image.shape[1]
        image = normalize(image)
        self.height = image.shape[0]
        return image

    def tap(self, x, y):
        if self.foreground() != self.package:
            raise RuntimeError("前台应用已切换，停止游戏点击")
        ratio = self.width / 720
        self.device.tap((round(x * ratio), round(y * ratio)))

    def swipe_ad(self, upwards):
        if self.foreground() != self.package:
            raise RuntimeError("前台应用已切换，停止广告浏览")
        ratio = self.width / 720
        bottom, top = round(self.height * .78 * ratio), round(self.height * .30 * ratio)
        start, end = (bottom, top) if upwards else (top, bottom)
        x = round(360 * ratio)
        self.device.swipe((x, start), (x, end), 650)


class AndroidScreenReader:
    def __init__(self, ocr):
        self.ocr = ocr

    def read(self, image):
        result = self.ocr(image)
        if result.txts is None:
            return []
        return [(text.replace(" ", ""), score, *map(int, np.asarray(box).mean(axis=0).round()))
                for text, score, box in zip(result.txts, result.scores, result.boxes)]
