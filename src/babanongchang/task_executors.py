from __future__ import annotations

from babanongchang import runtime as time
from collections.abc import Callable
from typing import Protocol, Sequence

from babanongchang.browsing import find_browse_iteration
from babanongchang.task_pool import TaskDefinition, TaskOperation


class TaskExecutionContext(Protocol):
    def tap_task_button(self, point: tuple[int, int]) -> None: ...

    def wait_for_task_page(self) -> None: ...

    def wait_for_task_list_departure(self) -> None: ...

    def read_task_page_texts(self) -> Sequence[str]: ...

    def run_swipe_browse(self, duration_seconds: float) -> None: ...


class TaskExecutor(Protocol):
    def execute(
        self,
        context: TaskExecutionContext,
        task: TaskDefinition,
        button: tuple[int, int],
    ) -> None: ...


class SwipeBrowseExecutor:
    def execute(
        self,
        context: TaskExecutionContext,
        task: TaskDefinition,
        button: tuple[int, int],
    ) -> None:
        context.tap_task_button(button)
        context.wait_for_task_page()
        iteration = find_browse_iteration(context.read_task_page_texts())
        duration_seconds = task.duration_seconds
        if iteration is not None:
            duration_seconds *= iteration
            print(f"识别到“第 {iteration} 次”，本轮浏览 {duration_seconds:g} 秒")
        context.run_swipe_browse(duration_seconds)


class ClickAndReturnExecutor:
    def __init__(self, sleep: Callable[[float], None] = time.sleep) -> None:
        self.sleep = sleep

    def execute(
        self,
        context: TaskExecutionContext,
        task: TaskDefinition,
        button: tuple[int, int],
    ) -> None:
        context.tap_task_button(button)
        context.wait_for_task_list_departure()
        if task.stay_seconds == 0:
            return
        context.wait_for_task_page()
        print(f"任务页面停留 {task.stay_seconds:g} 秒后返回")
        self.sleep(task.stay_seconds)


TASK_EXECUTORS: dict[TaskOperation, TaskExecutor] = {
    TaskOperation.SWIPE_BROWSE: SwipeBrowseExecutor(),
    TaskOperation.CLICK_AND_RETURN: ClickAndReturnExecutor(),
}
