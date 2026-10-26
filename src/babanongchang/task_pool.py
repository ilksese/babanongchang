from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskOperation(Enum):
    SWIPE_BROWSE = "swipe_browse"
    CLICK_AND_RETURN = "click_and_return"


@dataclass(frozen=True)
class TaskMatcher:
    fixed_text: str | None = None
    pattern: str | None = None

    def __post_init__(self) -> None:
        if (self.fixed_text is None) == (self.pattern is None):
            raise ValueError("任务匹配器必须且只能配置 fixed_text 或 pattern")
        if self.pattern is not None:
            re.compile(self.pattern)

    def matches(self, text: str) -> bool:
        normalized = text.replace(" ", "")
        if self.fixed_text is not None:
            return self.fixed_text.replace(" ", "") in normalized
        assert self.pattern is not None
        return re.search(self.pattern, normalized) is not None


@dataclass(frozen=True)
class TaskDefinition:
    key: str
    name: str
    operation: TaskOperation
    matchers: tuple[TaskMatcher, ...]
    action_labels: tuple[str, ...] = ("去完成",)
    duration_seconds: float = 18
    stay_seconds: float = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.matchers:
            raise ValueError("任务必须至少配置一个匹配器")
        if self.duration_seconds <= 0:
            raise ValueError("任务时长必须大于 0")
        if self.stay_seconds < 0:
            raise ValueError("任务停留时间不能小于 0")

    def matches(self, text: str) -> bool:
        return any(matcher.matches(text) for matcher in self.matchers)


TASK_CATALOG = (
    TaskDefinition(
        key="browse-goods",
        name="逛好物浏览任务",
        operation=TaskOperation.SWIPE_BROWSE,
        matchers=(
            TaskMatcher(pattern=r"逛(?:好物|一逛)(?:最高得|立得)\d+肥料?"),
        ),
        action_labels=("去完成", "去逛逛"),
        duration_seconds=18,
    ),
    TaskDefinition(
        key="browse-selected-goods",
        name="看精选商品得肥料",
        operation=TaskOperation.SWIPE_BROWSE,
        matchers=(TaskMatcher(fixed_text="看精选商品得肥料"),),
        action_labels=("去完成", "去逛逛"),
        duration_seconds=18,
    ),
    TaskDefinition(
        key="visit-alipay-for-beans",
        name="逛支付宝得金豆",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛支付宝得金豆"),),
    ),
    TaskDefinition(
        key="visit-alipay-beans-for-treasure",
        name="逛支付宝金豆得宝",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛支付宝金豆得宝"),),
    ),
    TaskDefinition(
        key="visit-ant-manor",
        name="逛一逛蚂蚁庄园",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛一逛蚂蚁庄园"),),
    ),
    TaskDefinition(
        key="visit-forest-team-planting",
        name="逛一逛森林组队种",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛一逛森林组队种"),),
    ),
    TaskDefinition(
        key="visit-alipay-member",
        name="逛一逛支付宝会员",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛一逛支付宝会员"),),
        action_labels=("去完成", "去逛逛"),
    ),
    TaskDefinition(
        key="visit-bean-park",
        name="逛一逛金豆乐园",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(fixed_text="逛一逛金豆乐园"),),
    ),
    TaskDefinition(
        key="play-my-game",
        name="玩一玩…",
        operation=TaskOperation.CLICK_AND_RETURN,
        matchers=(TaskMatcher(pattern=r"^玩一玩.*"),),
        stay_seconds=600,
        enabled=True,
    ),
)

TASK_POOL = tuple(task for task in TASK_CATALOG if task.enabled)
