from __future__ import annotations

from babanongchang import runtime as time
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from babanongchang.browsing import swipe_browse
from babanongchang.cli import Adb, FarmAutomation
from babanongchang.handle import (
    AutomationError,
    OcrText,
    RelativeRegion,
    ScreenSnapshot,
    TextHandle,
    normalize_text,
)
from babanongchang.navigation import back_until


TAOBAO_SEARCH_TASKS = ("搜一搜你喜欢的商品", "搜一搜你心仪的宝贝")


class TaobaoTaskOperation(Enum):
    SIGN_IN = "sign_in"
    SEARCH = "search"
    SWIPE_BROWSE = "swipe_browse"
    STAY = "stay"
    COINS_STAY = "coins_stay"


@dataclass(frozen=True)
class TaobaoTaskDefinition:
    name: str
    operation: TaobaoTaskOperation


TAOBAO_TASKS = (
    *(
        TaobaoTaskDefinition(name, TaobaoTaskOperation.SEARCH)
        for name in TAOBAO_SEARCH_TASKS
    ),
    TaobaoTaskDefinition("发现精选好物", TaobaoTaskOperation.SWIPE_BROWSE),
    TaobaoTaskDefinition("逛精选好物", TaobaoTaskOperation.SWIPE_BROWSE),
    TaobaoTaskDefinition("看严选推荐商品", TaobaoTaskOperation.STAY),
    TaobaoTaskDefinition("去淘金币", TaobaoTaskOperation.COINS_STAY),
)

TAOBAO_SIGN_IN_TASK = TaobaoTaskDefinition("去签到", TaobaoTaskOperation.SIGN_IN)


def find_taobao_farm_entry(items: Sequence[OcrText]) -> OcrText | None:
    return TextHandle.find_text(items, "芭芭农场")


def is_taobao_farm_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    has_title = any("芭芭农场" in text and "免费领水果" in text for text in texts)
    has_fertilize = any(text == "施肥" for text in texts)
    return has_title and has_fertilize


def find_taobao_fertilizer_entry(items: Sequence[OcrText]) -> OcrText | None:
    return TextHandle.find_text(items, "集肥料", exact=True)


def is_taobao_fertilizer_tasks_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    return any(text == "做任务赚肥料" for text in texts) and any(
        "肥料明细" in text for text in texts
    )


def find_taobao_task_action(
    items: Sequence[OcrText],
    image_shape: tuple[int, ...],
    task_text: str,
    action_text: str = "去完成",
) -> OcrText | None:
    normalized_task = normalize_text(task_text)
    return TextHandle.find_same_row_text(
        items,
        image_shape,
        anchor_matcher=lambda item: normalized_task in item.normalized_text,
        target_texts=action_text,
        target_region=RelativeRegion(left=0.55),
    )


def find_available_taobao_search_task(
    items: Sequence[OcrText], image_shape: tuple[int, ...]
) -> tuple[str, OcrText] | None:
    for task_name in TAOBAO_SEARCH_TASKS:
        button = find_taobao_task_action(items, image_shape, task_name)
        if button is not None:
            return task_name, button
    return None


def find_available_taobao_task(
    items: Sequence[OcrText], image_shape: tuple[int, ...]
) -> tuple[TaobaoTaskDefinition, OcrText] | None:
    """查找当前页面中位置最靠上的可执行任务。"""
    available = []
    sign_in = TextHandle.find_text(items, "去签到", exact=True)
    if sign_in is not None:
        available.append((TAOBAO_SIGN_IN_TASK, sign_in))
    for task in TAOBAO_TASKS:
        button = find_taobao_task_action(items, image_shape, task.name)
        if button is not None:
            available.append((task, button))
    return min(
        available,
        key=lambda result: (result[1].center[1], result[1].center[0]),
        default=None,
    )


def is_taobao_search_reward_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    return any("搜索有福利" in text for text in texts) and any(
        "搜索后浏览立得奖励" in text for text in texts
    )


def find_taobao_recommended_keyword(items: Sequence[OcrText]) -> OcrText | None:
    markers = [item for item in items if item.normalized_text == "搜索发现"]
    if not markers:
        return None
    marker = max(markers, key=lambda item: item.score)
    candidates = [
        item
        for item in items
        if marker.center[1] + 30 < item.center[1] < marker.center[1] + 140
        and item.center[0] < 360
        and "近一个月" not in item.normalized_text
    ]
    return min(candidates, key=lambda item: (item.center[1], item.center[0]), default=None)


def is_taobao_search_results_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    return any("搜索有福利" in text for text in texts) and any(
        "滑动浏览得肥料" in text for text in texts
    )


def is_taobao_discovery_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    return any(text == "浏览得奖励" for text in texts) and any(
        "下单得肥料" in text for text in texts
    )


def is_taobao_recommended_video_page(items: Sequence[OcrText]) -> bool:
    texts = [item.normalized_text for item in items]
    return any("滑动浏览得" in text for text in texts) and any(
        text == "肥料" for text in texts
    )


def is_taobao_coins_page(items: Sequence[OcrText]) -> bool:
    return TextHandle.has_text(items, "淘金币", exact=True) and TextHandle.has_text(
        items, "去赚金币", exact=True
    )


class TaobaoAutomation(FarmAutomation):
    """执行淘宝芭芭农场任务流程。"""

    PACKAGE = "com.taobao.taobao"
    HOME_ACTIVITY = "com.taobao.taobao/com.taobao.tao.welcome.Welcome"

    def __init__(self, adb: Adb) -> None:
        super().__init__(adb)
        min_score = getattr(adb, "taobao_min_score", 0.75)
        if not 0 <= min_score <= 1:
            raise ValueError("淘宝 OCR 置信度阈值必须在 0 到 1 之间")
        self.min_score = min_score

    def wait_for_farm_page_ready(self, timeout: float = 30) -> OcrText:
        """等待农场页及“集肥料”入口连续三帧位置稳定。"""
        return self.wait_for_stable_text(
            "集肥料",
            stable_scans=3,
            position_tolerance=8,
            screen_predicate=lambda snapshot: is_taobao_farm_page(snapshot.items),
            timeout=int(timeout * 1000),
            interval=500,
            exact=True,
            error="淘宝芭芭农场页面加载超时，未能稳定识别“集肥料”",
        )

    def wait_for_fertilizer_tasks_after_click(self, timeout: float = 15) -> bool:
        """单次点击后等待任务列表；进入其他页面时返回 False。"""
        deadline = time.monotonic() + timeout
        left_farm_at: float | None = None
        while time.monotonic() < deadline:
            snapshot = self.scan()
            if is_taobao_fertilizer_tasks_page(snapshot.items):
                return True
            if is_taobao_farm_page(snapshot.items):
                left_farm_at = None
            elif left_farm_at is None:
                left_farm_at = time.monotonic()
            elif time.monotonic() - left_farm_at >= 2:
                return False
            time.sleep(0.5)
        return False

    def return_to_farm_page(self, timeout: float = 20) -> None:
        back_until(
            self.adb,
            self,
            lambda snapshot: is_taobao_farm_page(snapshot.items),
            timeout=int(timeout * 1000),
            error="进入错误页面后未能返回淘宝芭芭农场",
        )

    def open_fertilizer_tasks_from_farm(self, max_attempts: int = 3) -> None:
        for attempt in range(1, max_attempts + 1):
            entry = self.wait_for_farm_page_ready()
            print(f"第 {attempt} 次点击“集肥料”")
            self.adb.tap(entry.center)
            if self.wait_for_fertilizer_tasks_after_click():
                print("已稳定进入淘宝肥料任务列表")
                return
            print("点击后未进入任务列表，返回农场首页重试")
            self.return_to_farm_page()
        raise AutomationError("多次点击“集肥料”后仍未进入任务列表")

    def wait_after_farm_entry_click(self, timeout: float = 30) -> None:
        destination = self.wait_for_screen(
            lambda snapshot: (
                "tasks"
                if is_taobao_fertilizer_tasks_page(snapshot.items)
                else "farm"
                if is_taobao_farm_page(snapshot.items)
                else None
            ),
            timeout=int(timeout * 1000),
            interval=500,
            error="点击淘宝首页“芭芭农场”后未进入农场页面",
        )
        if destination == "tasks":
            print("已稳定进入淘宝肥料任务列表")
            return
        self.open_fertilizer_tasks_from_farm()

    def ensure_fertilizer_tasks_page(self, timeout: float = 60) -> None:
        """从任意设备页面进入淘宝芭芭农场肥料任务列表。"""
        if is_taobao_fertilizer_tasks_page(self.scan().items):
            print("检测到已在淘宝肥料任务列表")
            return

        self.adb.start_activity(self.HOME_ACTIVITY)
        print("已启动淘宝主页 Activity")
        deadline = time.monotonic() + timeout
        unknown_since = time.monotonic()

        while time.monotonic() < deadline:
            snapshot = self.scan()
            if is_taobao_fertilizer_tasks_page(snapshot.items):
                print("已稳定进入淘宝肥料任务列表")
                return

            now = time.monotonic()
            on_farm_page = is_taobao_farm_page(snapshot.items)
            if on_farm_page:
                self.open_fertilizer_tasks_from_farm()
                return

            if not on_farm_page:
                entry = find_taobao_farm_entry(snapshot.items)
                if entry is not None:
                    self.adb.tap(entry.center)
                    print("已点击淘宝首页“芭芭农场”")
                    self.wait_after_farm_entry_click()
                    return

            if now - unknown_since >= 10:
                self.adb.back()
                print("当前页面无法识别，尝试返回以关闭遮挡页面")
                unknown_since = now
            time.sleep(0.5)

        raise AutomationError("未能从当前页面稳定进入淘宝肥料任务列表")

    def open_search_task(
        self, task_name: str, button: OcrText, timeout: float = 20
    ) -> None:
        print(f"开始执行“{task_name}”")
        self.tap_and_wait(
            button.center,
            lambda snapshot: (
                snapshot if is_taobao_search_reward_page(snapshot.items) else None
            ),
            timeout=int(timeout * 1000),
            interval=500,
            error=f"点击“{task_name}”后未进入搜索奖励页面",
        )
        print(f"已打开“{task_name}”任务")

    def browse_recommended_search_result(
        self, duration_seconds: float = 18, timeout: float = 20
    ) -> None:
        keyword = self.wait_for_screen(
            lambda snapshot: find_taobao_recommended_keyword(snapshot.items),
            timeout=int(timeout * 1000),
            interval=500,
            error="搜索奖励页面未找到推荐关键词",
        )
        print(f"点击推荐关键词：{keyword.text.strip()}")
        self.tap_and_wait(
            keyword.center,
            lambda snapshot: (
                snapshot if is_taobao_search_results_page(snapshot.items) else None
            ),
            timeout=int(timeout * 1000),
            interval=500,
            error="点击推荐关键词后未进入搜索结果列表",
        )
        swipe_browse(self.adb, duration_seconds=duration_seconds)

    def return_to_fertilizer_tasks(self, timeout: float = 30) -> None:
        result = back_until(
            self.adb,
            self,
            lambda snapshot: is_taobao_fertilizer_tasks_page(snapshot.items),
            timeout=int(timeout * 1000),
            error="多次返回后仍未回到淘宝肥料任务列表",
        )
        print(f"已返回淘宝肥料任务列表，共返回 {result.back_count} 次")

    def complete_supported_tasks(self) -> None:
        completed = 0
        while True:
            snapshot = self.scan()
            found = find_available_taobao_task(snapshot.items, snapshot.shape)
            if found is None:
                print(
                    f"所有已接入任务均不可执行，今日任务已清空，共完成 {completed} 次"
                )
                return

            task, button = found
            if task.operation is TaobaoTaskOperation.SIGN_IN:
                print("点击“去签到”")
                self.tap_and_wait(
                    button.center,
                    lambda current: (
                        current
                        if is_taobao_fertilizer_tasks_page(current.items)
                        and not self.has_text(current.items, "去签到", exact=True)
                        else None
                    ),
                    error="签到后未确认任务列表中的“去签到”按钮消失",
                )
                completed += 1
                continue
            if task.operation is TaobaoTaskOperation.SEARCH:
                self.open_search_task(task.name, button)
                self.browse_recommended_search_result()
            elif task.operation is TaobaoTaskOperation.SWIPE_BROWSE:
                print(f"开始执行“{task.name}”")
                self.tap_and_wait(
                    button.center,
                    lambda current: (
                        current if is_taobao_discovery_page(current.items) else None
                    ),
                    timeout=20000,
                    interval=500,
                    error=f"点击“{task.name}”后未进入商品浏览页面",
                )
                swipe_browse(self.adb, duration_seconds=18)
            elif task.operation is TaobaoTaskOperation.COINS_STAY:
                print(f"开始执行“{task.name}”")
                self.tap_and_wait(
                    button.center,
                    lambda current: (
                        current if is_taobao_coins_page(current.items) else None
                    ),
                    timeout=20000,
                    interval=500,
                    error="点击“去淘金币”后未进入淘金币页面",
                )
                print("淘金币页面停留 5 秒")
                time.sleep(5)
            elif task.operation is TaobaoTaskOperation.STAY:
                print("开始执行“看严选推荐商品”")
                self.tap_and_wait(
                    button.center,
                    lambda current: (
                        current
                        if is_taobao_recommended_video_page(current.items)
                        else None
                    ),
                    timeout=20000,
                    interval=500,
                    error="点击“看严选推荐商品”后未进入视频页面",
                )
                print("视频页面停留 18 秒")
                time.sleep(18)
            else:
                raise AutomationError(f"不支持的淘宝任务操作：{task.operation.value}")

            self.return_to_fertilizer_tasks()
            completed += 1

    def run(self) -> None:
        self.ensure_fertilizer_tasks_page()
        self.complete_supported_tasks()
