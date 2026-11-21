"""Android entry points called by the Kotlin host."""

from dataclasses import replace
import json
from pathlib import Path
import shlex

import cv2
import numpy as np

from babanongchang.adapters.android import AndroidClock, AndroidDevice, AndroidGameDevice, AndroidOcr, AndroidScreenReader
from babanongchang.arguments import build_parser, farm_options, game_options, parse_arguments
from babanongchang.config import CONFIG_FILE_NAME, load_project_config
from babanongchang.automation.handle import AutomationError
from babanongchang.nlgj.options import GameOptions
from babanongchang.workflow import FarmOptions, run_farm


def run(bridge, module, options, output_dir, taobao_min_score=FarmOptions.taobao_min_score):
    parser = build_parser()
    args = parse_arguments(parser, [module, *shlex.split(options)])
    if args.module == "app":
        raise ValueError("APK 不支持桌面界面")
    if args.serial or args.adb != "adb":
        raise ValueError("APK 操作本机，不支持 --serial 或 --adb")
    if args.screenshot and not args.nlgj:
        raise ValueError("离线截图识别请使用 挪了个箭")
    farm = farm_options(args, taobao_min_score=taobao_min_score)
    root = Path(output_dir).resolve()
    clock = AndroidClock(bridge)

    def log(text: str) -> None:
        bridge.log(text + "\n")

    device = AndroidDevice(bridge)
    try:
        if args.nlgj:
            from babanongchang.nlgj.runner import play

            game = game_options(parser, args)
            game = replace(
                game,
                output=root if game.output == GameOptions.output else root / game.output,
                screenshot=None if game.screenshot is None else root / game.screenshot,
            )
            play(game, device=None if game.screenshot else AndroidGameDevice(device),
                 reader=AndroidScreenReader(device.ocr), clock=clock, log=log)
        else:
            root.mkdir(parents=True, exist_ok=True)
            config = load_project_config(root / CONFIG_FILE_NAME)
            run_farm(args.module, farm, device=device, ocr=device.ocr, config=config, clock=clock, log=log)
    except AutomationError as exc:
        raise RuntimeError(f"自动化已安全停止：{exc}") from exc
    finally:
        device.ocr.close()


def help_text():
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
