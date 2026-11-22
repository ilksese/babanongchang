from __future__ import annotations

import re
from collections.abc import Callable
from typing import Sequence

import numpy as np

from babanongchang.automation.browsing import swipe_browse
from babanongchang.farm.device import FarmDevice
from babanongchang.logs import silent_log
from babanongchang.automation.handle import (
    AutomationError,
    OcrText,
    RelativeRegion,
    ScreenSnapshot,
    TextHandle,
    WaitTimeoutError,
    normalize_text,
)
from babanongchang.farm.alipay.task_executors import TASK_EXECUTORS
from babanongchang.farm.alipay.task_pool import TASK_POOL, TaskDefinition, TaskOperation


ALIPAY_PACKAGE = "com.eg.android.AlipayGphone"
ALIPAY_HOME_ACTIVITY = f"{ALIPAY_PACKAGE}/com.alipay.mobile.quinox.LauncherActivity"


def parse_fertilizer(items: Sequence[OcrText], image_shape: tuple[int, ...]) -> int | None:
    """从施肥按钮区域解析“肥料 + 数字”，排除商品列表中的“肥料 +70000”。"""
    height, width = image_shape[:2]
    candidates: list[tuple[float, int]] = []

    for item in items:
        x, y = item.center
        if not (0.2 * width < x < 0.8 * width and 0.55 * height < y < 0.85 * height):
            continue
        normalized = normalize_text(item.text)
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
    region = RelativeRegion(left=0, top=0.12, right=0.22, bottom=0.35)
    matches = [
        item
        for target in ("逛农货", "百县百品")
        for item in TextHandle.find_texts(
            items,
            target,
            region=region,
            image_shape=image_shape,
        )
    ]
    return max(matches, key=lambda item: item.score, default=None)


TASK_DIALOG_TITLES = ("做任务集肥料", "做任务领肥料")


def has_task_dialog(items: Sequence[OcrText]) -> bool:
    return any(
        any(normalize_text(title) in item.normalized_text for title in TASK_DIALOG_TITLES)
        for item in items
    )


def find_fertilizer_entry(items: Sequence[OcrText], image_shape: tuple[int, ...]) -> OcrText | None:
    """查找首页右下方的“领肥料”，避开页面中其他领取文案。"""
    return TextHandle.find_text(
        items,
        "领肥料",
        region=RelativeRegion(left=0.55, top=0.55),
        image_shape=image_shape,
    )


def find_task_action(
    items: Sequence[OcrText],
    image_shape: tuple[int, ...],
    task: TaskDefinition,
    actions: str | Sequence[str] | None = None,
) -> OcrText | None:
    """返回目标任务同一行右侧的操作按钮，避免点击其他任务的同名按钮。"""
    action_names = task.action_labels if actions is None else actions
    return TextHandle.find_same_row_text(
        items,
        image_shape,
        anchor_matcher=lambda item: task.matches(item.text),
        target_texts=action_names,
        target_region=RelativeRegion(left=0.55),
    )


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


class AlipayFlow:
    def __init__(
        self, device: FarmDevice, screen: TextHandle, browse_seconds: float = 18,
        *, log: Callable[[str], None] = silent_log,
    ) -> None:
        self.adb = device
        self.screen = screen
        self.browse_seconds = browse_seconds
        self.log = log

    def browse_for_reward(self, duration_seconds: float | None = None) -> None:
        swipe_browse(
            self.adb,
            self.browse_seconds if duration_seconds is None else duration_seconds,
            clock=self.screen.clock,
            log=self.log,
        )


class FarmAutomation(AlipayFlow):
    def __init__(
        self, device: FarmDevice, screen: TextHandle, threshold: int = 600,
        browse_seconds: float = 18, *, log: Callable[[str], None] = silent_log,
    ) -> None:
        super().__init__(device, screen, browse_seconds, log=log)
        self.threshold = threshold

    def wait_for_farm(self, timeout: float = 15) -> tuple[int, OcrText]:
        def match(snapshot: ScreenSnapshot) -> tuple[int, OcrText] | None:
            balance = parse_fertilizer(snapshot.items, snapshot.shape)
            fertilize = self.screen.find_text(snapshot.items, "施肥", exact=True)
            if balance is not None and fertilize is not None:
                return balance, fertilize
            return None

        return self.screen.wait_for_screen(
            match,
            timeout=int(timeout * 1000),
            interval=600,
            error="未识别到施肥页面的“施肥”和肥料余额，已停止以避免误点",
        )

    def maybe_claim_reward(self) -> bool:
        # 点击施肥后的动画约需一秒；短轮询可避免漏掉领取入口。
        try:
            claim_point = self.screen.wait_for_text("立即领肥", timeout=5000)
        except WaitTimeoutError:
            return False
        assert isinstance(claim_point, tuple)

        self.log("发现“立即领肥”，开始领取浏览奖励")
        self.adb.tap(claim_point)
        self.screen.click_text("立即领取")

        browse = self.wait_for_browse_or_farm()
        if browse is None:
            self.log("本轮未出现“逛一逛”，已回到施肥页，继续施肥")
            return True

        self.adb.tap(browse.center)
        self.screen.wait_for_text("浏览或查看商品领肥料", timeout=20000)
        self.browse_for_reward()

        self.adb.back()
        self.wait_for_farm(timeout=20)
        self.log("已返回施肥页面")
        return True

    def wait_for_browse_or_farm(self, timeout: float = 12) -> OcrText | None:
        """等待领取结果；返回按钮，或在已回到农场时返回 None。"""
        def match(snapshot: ScreenSnapshot) -> tuple[bool, OcrText | None] | None:
            browse = self.screen.find_text(snapshot.items, "逛一逛")
            if browse is not None:
                return True, browse

            balance = parse_fertilizer(snapshot.items, snapshot.shape)
            fertilize = self.screen.find_text(snapshot.items, "施肥", exact=True)
            if balance is not None and fertilize is not None:
                return True, None
            return None

        _, browse = self.screen.wait_for_screen(
            match,
            timeout=int(timeout * 1000),
            interval=600,
            error="领取后既未出现“逛一逛”，也未返回施肥页",
        )
        return browse

    def run(self, max_clicks: int | None = None) -> None:
        clicks = 0
        while max_clicks is None or clicks < max_clicks:
            balance, fertilize = self.wait_for_farm()
            self.log(f"识别到肥料余额：{balance}")
            if balance <= self.threshold:
                self.log(f"肥料余额不大于 {self.threshold}，施肥结束")
                return

            self.adb.tap(fertilize.center)
            clicks += 1
            self.log(f"已点击施肥（第 {clicks} 次）")
            self.screen.clock.sleep(1.2)
            self.maybe_claim_reward()

        self.log(f"已达到本次限制的 {max_clicks} 次点击，停止运行")


class GoodsAutomation(AlipayFlow):
    """执行每日一次的“逛农货/百县百品”浏览任务。"""

    def wait_for_home_entry(self, timeout: float = 15) -> OcrText:
        return self.screen.wait_for_screen(
            lambda snapshot: find_goods_entry(snapshot.items, snapshot.shape),
            timeout=int(timeout * 1000),
            interval=600,
            error="未识别到首页的“逛农货/百县百品”入口",
        )

    def wait_for_goods_page(self, timeout: float = 15) -> None:
        """确认首页控件消失且二级页内容已稳定出现，避免在过渡帧中开始计时。"""
        self.screen.wait_for_stable_screen(
            lambda snapshot: (
                find_goods_entry(snapshot.items, snapshot.shape) is None
                and self.screen.find_text(snapshot.items, "施肥", exact=True) is None
                and len(snapshot.items) >= 3
            ),
            stable_scans=2,
            timeout=int(timeout * 1000),
            interval=500,
            error="点击入口后未确认进入“逛农货/百县百品”二级页面",
        )

    def run(self) -> None:
        entry = self.wait_for_home_entry()
        self.log(f"识别到首页入口：{entry.text}")
        self.adb.tap(entry.center)
        self.wait_for_goods_page()
        self.log("已进入逛农货/百县百品二级页面")

        self.browse_for_reward()
        self.adb.back()
        self.wait_for_home_entry(timeout=20)
        self.log("已返回芭芭农场首页，本日任务完成")


class TaskAutomation(AlipayFlow):
    """执行“做任务领肥料”弹窗中的指定浏览任务。"""

    def wait_for_task_dialog(self, timeout: float = 15) -> None:
        """等待弹窗内容连续两次被识别，避开弹出动画。"""
        self.screen.wait_for_stable_screen(
            lambda snapshot: has_task_dialog(snapshot.items),
            stable_scans=2,
            timeout=int(timeout * 1000),
            interval=500,
            error="等待“做任务领肥料”弹窗超时",
        )

    def wait_for_task_list_stable(self, timeout: float = 20) -> None:
        """等待返回后的任务列表连续两帧内容一致，再继续识别。"""
        self.screen.wait_for_stable_screen(
            lambda snapshot: has_task_dialog(snapshot.items),
            stable_scans=2,
            signature=lambda snapshot: self.task_list_signature(snapshot.items),
            timeout=int(timeout * 1000),
            interval=600,
            error="任务列表刷新后未能稳定，已停止以避免误点",
        )

    def open_task_dialog(self) -> None:
        deadline = self.screen.clock.monotonic() + 15
        while self.screen.clock.monotonic() < deadline:
            snapshot = self.screen.scan()
            if has_task_dialog(snapshot.items):
                self.wait_for_task_list_stable()
                self.log("检测到已在“做任务集肥料”任务列表")
                return
            entry = find_fertilizer_entry(snapshot.items, snapshot.shape)
            if entry is not None:
                self.adb.tap(entry.center)
                self.wait_for_task_dialog()
                self.wait_for_task_list_stable()
                self.log("已打开“做任务领肥料”弹窗")
                return
            self.screen.clock.sleep(0.6)
        raise AutomationError("未识别到屏幕右下方的“领肥料”按钮")

    def return_to_farm(self, timeout: float = 20) -> None:
        def is_farm(snapshot: ScreenSnapshot) -> bool:
            return (
                not has_task_dialog(snapshot.items)
                and parse_fertilizer(snapshot.items, snapshot.shape) is not None
                and self.screen.has_text(snapshot.items, "施肥", exact=True)
            )

        snapshot = self.screen.scan()
        if not is_farm(snapshot):
            title = next(
                (
                    found
                    for text in TASK_DIALOG_TITLES
                    if (found := self.screen.find_text(snapshot.items, text)) is not None
                ),
                None,
            )
            if title is None:
                raise AutomationError("未识别到任务弹窗或农场首页，停止关闭弹窗以避免误点")
            height, width = snapshot.shape[:2]
            title_top = float(np.min(title.box[:, 1]))
            mask_top = int(height * 0.12)
            mask_bottom = int(title_top - height * 0.06)
            if mask_bottom <= mask_top:
                raise AutomationError("任务弹窗上方没有可确认的遮罩区域，已停止以避免误点")
            mask_point = (width // 2, (mask_top + mask_bottom) // 2)
            self.screen.tap_and_wait(
                mask_point,
                lambda current: current if is_farm(current) else None,
                timeout=int(timeout * 1000),
                interval=600,
                error="点击遮罩后任务弹窗未关闭或未回到农场首页，已停止且不发送返回键",
            )
        self.screen.wait_for_stable_screen(
            is_farm,
            stable_scans=2,
            timeout=int(timeout * 1000),
            interval=600,
            error="任务结束后芭芭农场首页未能稳定",
        )
        self.log("已关闭任务弹窗并返回芭芭农场首页")

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
        self.screen.clock.sleep(0.8)

    def reset_task_list(self) -> None:
        """回到列表顶部，使每轮查找都覆盖完整任务列表。"""
        for _ in range(8):
            self.scroll_task_list(toward_bottom=False)

    @staticmethod
    def scan_signature(items: Sequence[OcrText]) -> tuple[str, ...]:
        return TextHandle.screen_signature(items)

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
            normalized = item.normalized_text
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
        snapshot = self.screen.scan()
        self.log_recognized_tasks(snapshot.items, snapshot.shape)
        for task in tasks:
            button = find_task_action(snapshot.items, snapshot.shape, task, actions)
            if button is not None:
                return task, button

        self.reset_task_list()
        previous_signature: tuple[str, ...] | None = None
        unchanged_count = 0
        for page in range(max_scrolls + 1):
            snapshot = self.screen.scan()
            self.log_recognized_tasks(snapshot.items, snapshot.shape, page=page + 1)
            for task in tasks:
                button = find_task_action(
                    snapshot.items, snapshot.shape, task, actions
                )
                if button is not None:
                    return task, button

            signature = self.scan_signature(snapshot.items)
            unchanged_count = unchanged_count + 1 if signature == previous_signature else 0
            if page == max_scrolls or unchanged_count >= 1:
                return None
            previous_signature = signature
            self.scroll_task_list()
        return None

    def log_recognized_tasks(
        self, items: Sequence[OcrText], image_shape: tuple[int, ...], page: int | None = None
    ) -> None:
        descriptions = describe_recognized_tasks(items, image_shape)
        location = f"第 {page} 屏" if page is not None else "当前屏幕"
        if descriptions:
            self.log(f"任务识别（{location}）：")
            for description in descriptions:
                self.log(f"  - {description}")
        else:
            self.log(f"任务识别（{location}）：未命中任务池")

    def wait_for_task_target_page(self, timeout: float = 20) -> None:
        self.screen.wait_for_stable_screen(
            lambda snapshot: (
                not any(
                    self.screen.has_text(snapshot.items, title)
                    for title in TASK_DIALOG_TITLES
                )
                and len(snapshot.items) >= 3
            ),
            stable_scans=2,
            timeout=int(timeout * 1000),
            interval=500,
            error="点击任务按钮后未确认进入目标页面",
        )

    def wait_for_task_list_departure(self, timeout: float = 10) -> None:
        """任务弹窗一消失就返回，避免等待期间目标页继续弹出其他窗口。"""
        self.screen.wait_for_stable_screen(
            lambda snapshot: not has_task_dialog(snapshot.items),
            stable_scans=1,
            timeout=int(timeout * 1000),
            interval=100,
            error="点击任务按钮后未离开任务列表",
        )

    def claim_reward(self, task: TaskDefinition) -> None:
        if task.operation is TaskOperation.CLICK_AND_RETURN:
            found = self.find_action_in_list(tasks=(task,), actions="领取")
            if found is None:
                raise AutomationError(f"返回任务列表后未找到“{task.name}”的领取按钮")
            button = found[1]
        else:
            snapshot = self.screen.scan()
            button = find_task_action(
                snapshot.items, snapshot.shape, task, "领取"
            )
        if button is None:
            self.log(f"“{task.name}”已自动发放奖励或刷新，无需点击领取")
            return
        self.adb.tap(button.center)
        self.log(f"已领取“{task.name}”奖励")
        self.screen.clock.sleep(1.2)
        self.wait_for_task_dialog()
        self.wait_for_task_list_stable()

    def execute_task(self, task: TaskDefinition, button: OcrText) -> None:
        self.log(f"开始执行“{task.name}”")
        executor = TASK_EXECUTORS.get(task.operation)
        if executor is None:
            raise AutomationError(f"不支持的任务操作类型：{task.operation.value}")
        executor.execute(self, task, button.center, sleep=self.screen.clock.sleep, log=self.log)
        self.adb.back()
        self.wait_for_task_dialog(timeout=20)
        self.wait_for_task_list_stable(timeout=20)
        self.claim_reward(task)

    def tap_task_button(self, point: tuple[int, int]) -> None:
        self.adb.tap(point)

    def wait_for_task_page(self) -> None:
        self.wait_for_task_target_page()

    def read_task_page_texts(self) -> Sequence[str]:
        return self.screen.scan().texts

    def run_swipe_browse(self, duration_seconds: float) -> None:
        self.browse_for_reward(duration_seconds)

    def run(self) -> None:
        self.open_task_dialog()
        completed = 0
        while True:
            found = self.find_action_in_list()
            if found is None:
                self.log(f"任务池中已无可执行任务，共完成 {completed} 次")
                return

            task, button = found
            self.execute_task(task, button)
            completed += 1


class AlipayAutomation(AlipayFlow):
    """自动进入支付宝芭芭农场并完成一轮支付宝流程。"""

    def __init__(
        self, device: FarmDevice, screen: TextHandle, threshold: int = 600,
        browse_seconds: float = 18, *, log: Callable[[str], None] = silent_log,
    ) -> None:
        super().__init__(device, screen, browse_seconds, log=log)
        self.threshold = threshold
        self.tasks = TaskAutomation(device, screen, browse_seconds, log=log)

    @staticmethod
    def is_home(snapshot: ScreenSnapshot) -> bool:
        def has_label(text: str, region: RelativeRegion) -> bool:
            return TextHandle.find_text(
                snapshot.items,
                text,
                exact=True,
                region=region,
                image_shape=snapshot.shape,
            ) is not None

        top = RelativeRegion(left=0, top=0.08, right=1, bottom=0.25)
        bottom = RelativeRegion(left=0, top=0.8, right=1, bottom=1)
        actions = sum(
            has_label(text, top)
            for text in ("扫一扫", "收付款", "付钱/收钱")
        )
        navigation = sum(
            has_label(text, bottom) for text in ("理财", "消息", "我的")
        )
        return (
            has_label("首页", bottom) and actions >= 1
        ) or (actions >= 2 and navigation >= 2)

    @staticmethod
    def is_farm(snapshot: ScreenSnapshot) -> bool:
        return (
            not has_task_dialog(snapshot.items)
            and parse_fertilizer(snapshot.items, snapshot.shape) is not None
            and TextHandle.has_text(snapshot.items, "施肥", exact=True)
        )

    def ensure_farm_page(self, timeout: float = 60) -> None:
        self.adb.start_activity(ALIPAY_HOME_ACTIVITY)
        self.log("已启动支付宝，正在查找芭芭农场")
        deadline = self.screen.clock.monotonic() + timeout
        while self.screen.clock.monotonic() < deadline:
            snapshot = self.screen.scan()
            if self.is_farm(snapshot):
                self.screen.wait_for_stable_screen(
                    self.is_farm,
                    timeout=20000,
                    interval=500,
                    error="支付宝芭芭农场首页未能稳定",
                )
                return
            if has_task_dialog(snapshot.items):
                self.tasks.wait_for_task_list_stable()
                return
            if self.is_home(snapshot):
                entry = self.screen.wait_for_stable_text(
                    "芭芭农场",
                    exact=True,
                    screen_predicate=self.is_home,
                    timeout=20000,
                    interval=500,
                    error="支付宝首页未找到稳定的“芭芭农场”入口",
                )
                self.screen.tap_and_wait(
                    entry.center,
                    lambda current: current if self.is_farm(current) else None,
                    timeout=30000,
                    interval=500,
                    error="点击支付宝首页“芭芭农场”后未进入农场首页",
                )
                self.screen.wait_for_stable_screen(
                    self.is_farm,
                    timeout=20000,
                    interval=500,
                    error="支付宝芭芭农场首页未能稳定",
                )
                self.log("已从支付宝首页进入芭芭农场")
                return
            self.screen.clock.sleep(0.5)
        raise AutomationError(
            "未能识别支付宝首页或芭芭农场，已停止且未发送返回键；"
            "请确认已登录并打开支付宝首页"
        )

    def run(self, max_clicks: int | None = None) -> None:
        self.ensure_farm_page()
        self.log("开始支付宝流程：做任务领肥料 → 逛农货 → 施肥")
        self.tasks.run()
        self.tasks.return_to_farm()
        GoodsAutomation(self.adb, self.screen, self.browse_seconds, log=self.log).run()
        FarmAutomation(
            self.adb,
            self.screen,
            threshold=self.threshold,
            browse_seconds=self.browse_seconds,
            log=self.log,
        ).run(max_clicks=max_clicks)
        self.log("支付宝流程已完成")
