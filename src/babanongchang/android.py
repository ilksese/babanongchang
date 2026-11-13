"""Android adapters for the shared CLI; no ADB or desktop OCR dependencies."""

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import shlex

import cv2
import numpy as np

from babanongchang import runtime


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

    def allow_screen_sleep(self):
        pass  # The Android run owns and releases the screen wake lock.


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


class RunLog(io.TextIOBase):
    def __init__(self, bridge):
        self.bridge = bridge

    def write(self, text):
        self.bridge.log(text)
        return len(text)

    def flush(self):
        pass


def run(bridge, module, options, output_dir, taobao_min_score=0.75):
    from babanongchang.cli import build_parser, main

    if not 0 <= taobao_min_score <= 1:
        raise ValueError("淘宝 OCR 置信度阈值必须在 0 到 1 之间")
    arguments = [module, *shlex.split(options)]
    parser = build_parser()
    args = parser.parse_args(arguments)
    if args.serial or args.adb != "adb":
        raise ValueError("APK 操作本机，不支持 --serial 或 --adb")
    if args.screenshot and not args.nlgj:
        raise ValueError("离线截图识别请使用 挪了个箭")
    if args.output == Path("artifacts/nlgj"):
        arguments += ["--output", output_dir]
    device = AndroidDevice(bridge)
    device.taobao_min_score = taobao_min_score
    game = AndroidGameDevice(device) if args.nlgj and not args.screenshot else None
    previous_directory = Path.cwd()
    runtime.backend = bridge
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        os.chdir(output_dir)
        with redirect_stdout(RunLog(bridge)), redirect_stderr(RunLog(bridge)):
            main(arguments, device_factory=lambda serial: device, game_device=game,
                 game_reader=AndroidScreenReader(device.ocr))
    finally:
        runtime.backend = None
        os.chdir(previous_directory)
        device.ocr.close()


def help_text():
    from babanongchang.cli import build_parser

    return build_parser().format_help()


def recognize_png(png):
    """The legacy single-attempt entry uses the same offline OCR as CLI flows."""
    class Uncontrolled:
        def checkpoint(self):
            pass

    image = cv2.imdecode(np.frombuffer(bytes(png), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("无法解码 OCR 图片")
    ocr = AndroidOcr(Uncontrolled())
    try:
        result = ocr(image)
        return json.dumps([] if result.txts is None else [
            [text, np.asarray(box).tolist(), float(score)]
            for text, box, score in zip(result.txts, result.boxes, result.scores)
        ])
    finally:
        ocr.close()
