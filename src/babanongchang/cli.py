from __future__ import annotations

import argparse
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

import cv2
import numpy as np
from rapidocr import RapidOCR


class AutomationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrText:
    text: str
    score: float
    box: np.ndarray

    @property
    def center(self) -> tuple[int, int]:
        return int(self.box[:, 0].mean()), int(self.box[:, 1].mean())


def parse_fertilizer(items: Sequence[OcrText], image_shape: tuple[int, ...]) -> int | None:
    """从施肥按钮区域解析“肥料 + 数字”，排除商品列表中的“肥料 +70000”。"""
    height, width = image_shape[:2]
    candidates: list[tuple[float, int]] = []

    for item in items:
        x, y = item.center
        if not (0.2 * width < x < 0.8 * width and 0.55 * height < y < 0.85 * height):
            continue
        normalized = re.sub(r"\s+", "", item.text)
        match = re.search(r"肥料[：:]?(\d+)$", normalized)
        if match:
            candidates.append((item.score, int(match.group(1))))

    if candidates:
        return max(candidates)[1]

    # 某些分辨率下 OCR 会把“肥料”和数字拆成相邻的两段。
    labels = [item for item in items if "肥料" in item.text]
    numbers = [item for item in items if re.fullmatch(r"\d+", item.text.strip())]
    for label in labels:
        label_x, label_y = label.center
        if not (0.2 * width < label_x < 0.8 * width and 0.55 * height < label_y < 0.85 * height):
            continue
        nearby = [
            item
            for item in numbers
            if 0 < item.center[0] - label_x < 0.3 * width
            and abs(item.center[1] - label_y) < 0.035 * height
        ]
        if nearby:
            best = min(nearby, key=lambda item: item.center[0] - label_x)
            return int(best.text.strip())
    return None


def find_goods_entry(items: Sequence[OcrText], image_shape: tuple[int, ...]) -> OcrText | None:
    """查找首页左上方的“逛农货/百县百品”，避开中间的同名横幅。"""
    height, width = image_shape[:2]
    matches = []
    for item in items:
        x, y = item.center
        text = item.text.replace(" ", "").strip()
        if (
            ("逛农货" in text or "百县百品" in text)
            and x < 0.22 * width
            and 0.12 * height < y < 0.35 * height
        ):
            matches.append(item)
    return max(matches, key=lambda item: item.score, default=None)


class Adb:
    def __init__(self, serial: str | None = None) -> None:
        self.prefix = ["adb"] + (["-s", serial] if serial else [])
        self._verify_device()

    def _run(self, *args: str, timeout: float = 30) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [*self.prefix, *args],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise AutomationError("找不到 adb，请先将 Android platform-tools 加入 PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise AutomationError(f"ADB 命令超时：{' '.join(args)}") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise AutomationError(f"ADB 命令失败：{detail or '未知错误'}") from exc

    def _verify_device(self) -> None:
        result = self._run("get-state")
        if result.stdout.decode("utf-8", errors="replace").strip() != "device":
            raise AutomationError("ADB 设备未连接或未授权")

    def screenshot(self) -> np.ndarray:
        raw = self._run("exec-out", "screencap", "-p").stdout
        image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AutomationError("无法解码设备截图")
        return image

    def tap(self, point: tuple[int, int]) -> None:
        x, y = point
        self._run("shell", "input", "tap", str(x), str(y))

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration_ms: int) -> None:
        self._run(
            "shell",
            "input",
            "swipe",
            str(start[0]),
            str(start[1]),
            str(end[0]),
            str(end[1]),
            str(duration_ms),
        )

    def back(self) -> None:
        self._run("shell", "input", "keyevent", "KEYCODE_BACK")


class FarmAutomation:
    def __init__(self, adb: Adb, threshold: int = 600, browse_seconds: float = 18) -> None:
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        self.adb = adb
        self.threshold = threshold
        self.browse_seconds = browse_seconds
        self.ocr = RapidOCR()

    def scan(self) -> tuple[np.ndarray, list[OcrText]]:
        image = self.adb.screenshot()
        result = self.ocr(image)
        if result.txts is None or result.boxes is None or result.scores is None:
            return image, []
        items = [
            OcrText(text=text, score=float(score), box=np.asarray(box))
            for text, score, box in zip(result.txts, result.scores, result.boxes)
            if float(score) >= 0.75
        ]
        return image, items

    @staticmethod
    def find_text(items: Sequence[OcrText], target: str, exact: bool = False) -> OcrText | None:
        matches = [
            item
            for item in items
            if (item.text.strip() == target if exact else target in item.text.replace(" ", ""))
        ]
        return max(matches, key=lambda item: item.score, default=None)

    def wait_for_text(self, target: str, timeout: float = 12, exact: bool = False) -> OcrText:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, items = self.scan()
            found = self.find_text(items, target, exact=exact)
            if found is not None:
                return found
            time.sleep(0.6)
        raise AutomationError(f"等待“{target}”超时，已停止以避免误点")

    def wait_for_farm(self, timeout: float = 15) -> tuple[int, OcrText]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image, items = self.scan()
            balance = parse_fertilizer(items, image.shape)
            fertilize = self.find_text(items, "施肥", exact=True)
            if balance is not None and fertilize is not None:
                return balance, fertilize
            time.sleep(0.6)
        raise AutomationError("未识别到施肥页面的“施肥”和肥料余额，已停止以避免误点")

    def maybe_claim_reward(self) -> bool:
        # 点击施肥后的动画约需一秒；短轮询可避免漏掉领取入口。
        deadline = time.monotonic() + 5
        claim_entry: OcrText | None = None
        while time.monotonic() < deadline:
            _, items = self.scan()
            claim_entry = self.find_text(items, "立即领肥")
            if claim_entry is not None:
                break
            time.sleep(0.5)
        if claim_entry is None:
            return False

        print("发现“立即领肥”，开始领取浏览奖励")
        self.adb.tap(claim_entry.center)
        claim = self.wait_for_text("立即领取")
        self.adb.tap(claim.center)

        browse = self.wait_for_browse_or_farm()
        if browse is None:
            print("本轮未出现“逛一逛”，已回到施肥页，继续施肥")
            return True

        self.adb.tap(browse.center)
        self.wait_for_text("浏览或查看商品领肥料", timeout=20)
        self.browse_for_reward()

        self.adb.back()
        self.wait_for_farm(timeout=20)
        print("已返回施肥页面")
        return True

    def wait_for_browse_or_farm(self, timeout: float = 12) -> OcrText | None:
        """等待领取结果；返回按钮，或在已回到农场时返回 None。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image, items = self.scan()
            browse = self.find_text(items, "逛一逛")
            if browse is not None:
                return browse

            balance = parse_fertilizer(items, image.shape)
            fertilize = self.find_text(items, "施肥", exact=True)
            if balance is not None and fertilize is not None:
                return None
            time.sleep(0.6)
        raise AutomationError("领取后既未出现“逛一逛”，也未返回施肥页")

    def browse_for_reward(self) -> None:
        image = self.adb.screenshot()
        height, width = image.shape[:2]
        upper = (width // 2, int(height * 0.36))
        lower = (width // 2, int(height * 0.74))
        deadline = time.monotonic() + self.browse_seconds
        downward = True
        print(f"开始上下往复滑动 {self.browse_seconds:g} 秒")
        while time.monotonic() < deadline:
            start, end = (upper, lower) if downward else (lower, upper)
            self.adb.swipe(start, end, duration_ms=650)
            downward = not downward
            time.sleep(0.2)
        print("浏览时间已满足，准备返回")

    def run(self, max_clicks: int | None = None) -> None:
        clicks = 0
        while max_clicks is None or clicks < max_clicks:
            balance, fertilize = self.wait_for_farm()
            print(f"识别到肥料余额：{balance}")
            if balance <= self.threshold:
                print(f"肥料余额不大于 {self.threshold}，施肥结束")
                return

            self.adb.tap(fertilize.center)
            clicks += 1
            print(f"已点击施肥（第 {clicks} 次）")
            time.sleep(1.2)
            self.maybe_claim_reward()

        print(f"已达到本次限制的 {max_clicks} 次点击，停止运行")


class GoodsAutomation(FarmAutomation):
    """执行每日一次的“逛农货/百县百品”浏览任务。"""

    def __init__(self, adb: Adb, browse_seconds: float = 18) -> None:
        super().__init__(adb, browse_seconds=browse_seconds)

    def wait_for_home_entry(self, timeout: float = 15) -> OcrText:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            image, items = self.scan()
            entry = find_goods_entry(items, image.shape)
            if entry is not None:
                return entry
            time.sleep(0.6)
        raise AutomationError("未识别到首页的“逛农货/百县百品”入口")

    def wait_for_goods_page(self, timeout: float = 15) -> None:
        """确认首页控件消失且二级页内容已稳定出现，避免在过渡帧中开始计时。"""
        deadline = time.monotonic() + timeout
        stable_scans = 0
        while time.monotonic() < deadline:
            image, items = self.scan()
            entry = find_goods_entry(items, image.shape)
            fertilize = self.find_text(items, "施肥", exact=True)
            if entry is None and fertilize is None and len(items) >= 3:
                stable_scans += 1
                if stable_scans >= 2:
                    return
            else:
                stable_scans = 0
            time.sleep(0.5)
        raise AutomationError("点击入口后未确认进入“逛农货/百县百品”二级页面")

    def run(self) -> None:
        entry = self.wait_for_home_entry()
        print(f"识别到首页入口：{entry.text}")
        self.adb.tap(entry.center)
        self.wait_for_goods_page()
        print("已进入逛农货/百县百品二级页面")

        self.browse_for_reward()
        self.adb.back()
        self.wait_for_home_entry(timeout=20)
        print("已返回芭芭农场首页，本日任务完成")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="支付宝芭芭农场自动化脚本")
    parser.add_argument(
        "module",
        nargs="?",
        choices=("fertilize", "goods"),
        default="fertilize",
        help="运行模块：fertilize（施肥，默认）或 goods（逛农货/百县百品）",
    )
    parser.add_argument("--serial", help="ADB 设备序列号；仅连接一台设备时可省略")
    parser.add_argument("--threshold", type=int, default=600, help="停止施肥的余额阈值（默认：600）")
    parser.add_argument(
        "--browse-seconds",
        type=float,
        default=18,
        help="浏览奖励页面的往复滑动秒数（默认：18）",
    )
    parser.add_argument("--max-clicks", type=int, help="最多点击几次施肥；用于小范围测试")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.threshold < 0 or args.browse_seconds < 15:
        raise SystemExit("threshold 不能为负数，browse-seconds 不能少于 15 秒")
    if args.max_clicks is not None and args.max_clicks < 1:
        raise SystemExit("max-clicks 必须大于 0")

    try:
        adb = Adb(args.serial)
        if args.module == "goods":
            GoodsAutomation(adb, browse_seconds=args.browse_seconds).run()
        else:
            FarmAutomation(
                adb,
                threshold=args.threshold,
                browse_seconds=args.browse_seconds,
            ).run(max_clicks=args.max_clicks)
    except KeyboardInterrupt:
        print("\n已由用户停止")
    except AutomationError as exc:
        raise SystemExit(f"自动化已安全停止：{exc}") from exc


if __name__ == "__main__":
    main()
