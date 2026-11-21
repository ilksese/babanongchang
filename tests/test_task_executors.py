import unittest

from babanongchang.farm.alipay.task_executors import (
    TASK_EXECUTORS,
    ClickAndReturnExecutor,
    SwipeBrowseExecutor,
)
from babanongchang.farm.alipay.task_pool import TASK_POOL, TaskDefinition, TaskMatcher, TaskOperation


class FakeExecutionContext:
    def __init__(self, texts: tuple[str, ...] = ()) -> None:
        self.texts = texts
        self.events: list[object] = []

    def tap_task_button(self, point: tuple[int, int]) -> None:
        self.events.append(("tap", point))

    def wait_for_task_page(self) -> None:
        self.events.append("wait")

    def wait_for_task_list_departure(self) -> None:
        self.events.append("depart")

    def read_task_page_texts(self) -> tuple[str, ...]:
        self.events.append("read")
        return self.texts

    def run_swipe_browse(self, duration_seconds: float) -> None:
        self.events.append(("browse", duration_seconds))


def task(
    operation: TaskOperation,
    duration_seconds: float = 18,
    stay_seconds: float = 0,
) -> TaskDefinition:
    return TaskDefinition(
        key="test",
        name="测试任务",
        operation=operation,
        matchers=(TaskMatcher(fixed_text="测试任务"),),
        duration_seconds=duration_seconds,
        stay_seconds=stay_seconds,
    )


class SwipeBrowseExecutorTest(unittest.TestCase):
    def test_local_flavors_task_uses_registered_browse_executor(self) -> None:
        definition = next(
            task for task in TASK_POOL if task.key == "browse-local-flavors"
        )
        context = FakeExecutionContext()
        TASK_EXECUTORS[definition.operation].execute(context, definition, (100, 200))
        self.assertEqual(
            context.events,
            [("tap", (100, 200)), "wait", "read", ("browse", 18)],
        )

    def test_browses_for_configured_duration(self) -> None:
        context = FakeExecutionContext()
        SwipeBrowseExecutor().execute(
            context, task(TaskOperation.SWIPE_BROWSE), (100, 200)
        )
        self.assertEqual(
            context.events,
            [("tap", (100, 200)), "wait", "read", ("browse", 18)],
        )

    def test_multiplies_duration_by_iteration(self) -> None:
        context = FakeExecutionContext(("任务第 3 次",))
        SwipeBrowseExecutor().execute(
            context, task(TaskOperation.SWIPE_BROWSE), (100, 200)
        )
        self.assertEqual(context.events[-1], ("browse", 54))


class ClickAndReturnExecutorTest(unittest.TestCase):
    def test_returns_immediately_when_stay_is_zero(self) -> None:
        context = FakeExecutionContext()
        delays: list[float] = []
        ClickAndReturnExecutor().execute(
            context,
            task(TaskOperation.CLICK_AND_RETURN),
            (100, 200),
            sleep=delays.append,
        )
        self.assertEqual(context.events, [("tap", (100, 200)), "depart"])
        self.assertEqual(delays, [])

    def test_waits_and_stays_when_duration_is_configured(self) -> None:
        context = FakeExecutionContext()
        delays: list[float] = []
        ClickAndReturnExecutor().execute(
            context,
            task(TaskOperation.CLICK_AND_RETURN, stay_seconds=300),
            (100, 200),
            sleep=delays.append,
        )
        self.assertEqual(
            context.events,
            [("tap", (100, 200)), "depart", "wait"],
        )
        self.assertEqual(delays, [300])


if __name__ == "__main__":
    unittest.main()
