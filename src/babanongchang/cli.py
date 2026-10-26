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

from babanongchang.browsing import swipe_browse
from babanongchang.task_executors import TASK_EXECUTORS
from babanongchang.task_pool import TASK_POOL, TaskDefinition, TaskOperation


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


TASK_DIALOG_TITLES = ("做任务集肥料", "做任务领肥料")


def has_task_dialog(items: Sequence[OcrText]) -> bool:
    return any(
        any(title in item.text.replace(" ", "") for title in TASK_DIALOG_TITLES)
        for item in items
    )


def find_fertilizer_entry(items: Sequence[OcrText], image_shape: tuple[int, ...]) -> OcrText | None:
    """查找首页右下方的“领肥料”，避开页面中其他领取文案。"""
    height, width = image_shape[:2]
    matches = [
        item
        for item in items
        if "领肥料" in item.text.replace(" ", "")
        and item.center[0] > 0.55 * width
        and item.center[1] > 0.55 * height
    ]
    return max(matches, key=lambda item: item.score, default=None)


def find_task_action(
    items: Sequence[OcrText],
    image_shape: tuple[int, ...],
    task: TaskDefinition,
    actions: str | Sequence[str] | None = None,
) -> OcrText | None:
    """返回目标任务同一行右侧的操作按钮，避免点击其他任务的同名按钮。"""
    height, width = image_shape[:2]
    titles = [item for item in items if task.matches(item.text)]
    action_names = task.action_labels if actions is None else actions
    action_names = (action_names,) if isinstance(action_names, str) else action_names
    actions = [
        item
        for item in items
        if any(name in item.text.replace(" ", "") for name in action_names)
        and item.center[0] > 0.55 * width
    ]
    pairs = [
        (title, button)
        for title in titles
        for button in actions
        if button.center[0] > title.center[0]
        and abs(button.center[1] - title.center[1]) < 0.06 * height
    ]
    if not pairs:
        return None
    return max(pairs, key=lambda pair: pair[0].score + pair[1].score)[1]


def describe_recognized_tasks(
    items: Sequence[OcrText], image_shape: tuple[int, ...]
) -> list[str]:
    """描述当前屏幕中命中任务池的任务及其同行按钮。"""
    descriptions = []
    for task in TASK_POOL:
        titles = [item for item in items if task.matches(item.text)]
        if not titles:
            continue
        title = max(titles, key=lambda item: item.score)
        button = find_task_action(
            items,
            image_shape,
            task,
            (*task.action_labels, "领取"),
        )
        button_text = button.text.strip() if button is not None else "无可执行按钮"
        descriptions.append(
            f"{title.text.strip()} -> {task.operation.value} [{button_text}]"
        )
    return descriptions


class Adb:
    def __init__(self, serial: str | None = None) -> None:
        self.prefix = ["adb"] + (["-s", serial] if serial else [])
        self._verify_device()
        self._run("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        self._run("shell", "svc", "power", "stayon", "true")

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
        if not raw:
            raise AutomationError("设备截图为空，请检查屏幕是否已锁定")
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

    def allow_screen_sleep(self) -> None:
        self._run("shell", "svc", "power", "stayon", "false")


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

    def browse_for_reward(self, duration_seconds: float | None = None) -> None:
        swipe_browse(
            self.adb,
            self.browse_seconds if duration_seconds is None else duration_seconds,
        )

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


class TaskAutomation(FarmAutomation):
    """执行“做任务领肥料”弹窗中的指定浏览任务。"""

    def __init__(self, adb: Adb, browse_seconds: float = 18) -> None:
        super().__init__(adb, browse_seconds=browse_seconds)

    def wait_for_task_dialog(self, timeout: float = 15) -> None:
        """等待弹窗内容连续两次被识别，避开弹出动画。"""
        deadline = time.monotonic() + timeout
        stable_scans = 0
        while time.monotonic() < deadline:
            _, items = self.scan()
            if has_task_dialog(items):
                stable_scans += 1
                if stable_scans >= 2:
                    return
            else:
                stable_scans = 0
            time.sleep(0.5)
        raise AutomationError("等待“做任务领肥料”弹窗超时")

    def wait_for_task_list_stable(self, timeout: float = 20) -> None:
        """等待返回后的任务列表连续两帧内容一致，再继续识别。"""
        deadline = time.monotonic() + timeout
        previous_signature: tuple[str, ...] | None = None
        while time.monotonic() < deadline:
            _, items = self.scan()
            has_dialog = has_task_dialog(items)
            signature = self.task_list_signature(items)
            if has_dialog and signature == previous_signature:
                return
            previous_signature = signature if has_dialog else None
            time.sleep(0.6)
        raise AutomationError("任务列表刷新后未能稳定，已停止以避免误点")

    def open_task_dialog(self) -> None:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            image, items = self.scan()
            if has_task_dialog(items):
                self.wait_for_task_list_stable()
                print("检测到已在“做任务集肥料”任务列表")
                return
            entry = find_fertilizer_entry(items, image.shape)
            if entry is not None:
                self.adb.tap(entry.center)
                self.wait_for_task_dialog()
                self.wait_for_task_list_stable()
                print("已打开“做任务领肥料”弹窗")
                return
            time.sleep(0.6)
        raise AutomationError("未识别到屏幕右下方的“领肥料”按钮")

    def scroll_task_list(self, toward_bottom: bool = True) -> None:
        image = self.adb.screenshot()
        height, width = image.shape[:2]
        start_y, end_y = (
            (int(height * 0.76), int(height * 0.38))
            if toward_bottom
            else (int(height * 0.38), int(height * 0.76))
        )
        self.adb.swipe(
            (width // 2, start_y),
            (width // 2, end_y),
            duration_ms=650,
        )
        time.sleep(0.8)

    def reset_task_list(self) -> None:
        """回到列表顶部，使每轮查找都覆盖完整任务列表。"""
        for _ in range(8):
            self.scroll_task_list(toward_bottom=False)

    @staticmethod
    def scan_signature(items: Sequence[OcrText]) -> tuple[str, ...]:
        return tuple(sorted(item.text.replace(" ", "") for item in items if item.text.strip()))

    @staticmethod
    def task_list_signature(items: Sequence[OcrText]) -> tuple[str, ...]:
        """仅保留任务标题和操作按钮，排除状态栏、动画等动态文案。"""
        action_labels = {
            label
            for task in TASK_POOL
            for label in (*task.action_labels, "领取")
        }
        texts = []
        for item in items:
            normalized = item.text.replace(" ", "")
            if any(task.matches(item.text) for task in TASK_POOL) or any(
                label in normalized for label in action_labels
            ):
                texts.append(normalized)
        return tuple(sorted(texts))

    def find_action_in_list(
        self,
        tasks: Sequence[TaskDefinition] = TASK_POOL,
        actions: str | Sequence[str] | None = None,
        max_scrolls: int = 10,
    ) -> tuple[TaskDefinition, OcrText] | None:
        """优先检查当前屏幕，找不到时再从列表顶部完整查找。"""
        image, items = self.scan()
        self.log_recognized_tasks(items, image.shape)
        for task in tasks:
            button = find_task_action(items, image.shape, task, actions)
            if button is not None:
                return task, button

        self.reset_task_list()
        previous_signature: tuple[str, ...] | None = None
        unchanged_count = 0
        for page in range(max_scrolls + 1):
            image, items = self.scan()
            self.log_recognized_tasks(items, image.shape, page=page + 1)
            for task in tasks:
                button = find_task_action(items, image.shape, task, actions)
                if button is not None:
                    return task, button

            signature = self.scan_signature(items)
            unchanged_count = unchanged_count + 1 if signature == previous_signature else 0
            if page == max_scrolls or unchanged_count >= 1:
                return None
            previous_signature = signature
            self.scroll_task_list()
        return None

    @staticmethod
    def log_recognized_tasks(
        items: Sequence[OcrText], image_shape: tuple[int, ...], page: int | None = None
    ) -> None:
        descriptions = describe_recognized_tasks(items, image_shape)
        location = f"第 {page} 屏" if page is not None else "当前屏幕"
        if descriptions:
            print(f"任务识别（{location}）：")
            for description in descriptions:
                print(f"  - {description}")
        else:
            print(f"任务识别（{location}）：未命中任务池")

    def wait_for_task_target_page(self, timeout: float = 20) -> None:
        deadline = time.monotonic() + timeout
        stable_scans = 0
        while time.monotonic() < deadline:
            _, items = self.scan()
            dialog = next(
                (self.find_text(items, title) for title in TASK_DIALOG_TITLES if self.find_text(items, title)),
                None,
            )
            if dialog is None and len(items) >= 3:
                stable_scans += 1
                if stable_scans >= 2:
                    return
            else:
                stable_scans = 0
            time.sleep(0.5)
        raise AutomationError("点击任务按钮后未确认进入目标页面")

    def wait_for_task_list_departure(self, timeout: float = 10) -> None:
        """任务弹窗一消失就返回，避免等待期间目标页继续弹出其他窗口。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, items = self.scan()
            has_dialog = has_task_dialog(items)
            if not has_dialog:
                return
            time.sleep(0.1)
        raise AutomationError("点击任务按钮后未离开任务列表")

    def claim_reward(self, task: TaskDefinition) -> None:
        if task.operation is TaskOperation.CLICK_AND_RETURN:
            found = self.find_action_in_list(tasks=(task,), actions="领取")
            if found is None:
                raise AutomationError(f"返回任务列表后未找到“{task.name}”的领取按钮")
            button = found[1]
        else:
            image, items = self.scan()
            button = find_task_action(items, image.shape, task, "领取")
        if button is None:
            print(f"“{task.name}”已自动发放奖励或刷新，无需点击领取")
            return
        self.adb.tap(button.center)
        print(f"已领取“{task.name}”奖励")
        time.sleep(1.2)
        self.wait_for_task_dialog()
        self.wait_for_task_list_stable()

    def execute_task(self, task: TaskDefinition, button: OcrText) -> None:
        print(f"开始执行“{task.name}”")
        executor = TASK_EXECUTORS.get(task.operation)
        if executor is None:
            raise AutomationError(f"不支持的任务操作类型：{task.operation.value}")
        executor.execute(self, task, button.center)
        self.adb.back()
        self.wait_for_task_dialog(timeout=20)
        self.wait_for_task_list_stable(timeout=20)
        self.claim_reward(task)

    def tap_task_button(self, point: tuple[int, int]) -> None:
        self.adb.tap(point)

    def wait_for_task_page(self) -> None:
        self.wait_for_task_target_page()

    def read_task_page_texts(self) -> Sequence[str]:
        _, items = self.scan()
        return [item.text for item in items]

    def run_swipe_browse(self, duration_seconds: float) -> None:
        self.browse_for_reward(duration_seconds)

    def run(self) -> None:
        self.open_task_dialog()
        completed = 0
        while True:
            found = self.find_action_in_list()
            if found is None:
                print(f"任务池中已无可执行任务，共完成 {completed} 次")
                return

            task, button = found
            self.execute_task(task, button)
            completed += 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="支付宝芭芭农场自动化脚本")
    parser.add_argument(
        "module",
        nargs="?",
        choices=("fertilize", "goods", "tasks"),
        default="fertilize",
        help="运行模块：fertilize（施肥，默认）、goods（逛农货/百县百品）或 tasks（做任务领肥料）",
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

    adb: Adb | None = None
    try:
        adb = Adb(args.serial)
        if args.module == "goods":
            GoodsAutomation(adb, browse_seconds=args.browse_seconds).run()
        elif args.module == "tasks":
            TaskAutomation(adb, browse_seconds=args.browse_seconds).run()
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
    finally:
        if adb is not None:
            try:
                adb.allow_screen_sleep()
            except AutomationError as exc:
                print(f"警告：恢复屏幕自动休眠失败：{exc}")


if __name__ == "__main__":
    main()
