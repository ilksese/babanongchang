import unittest

import numpy as np

from babanongchang.cli import (
    OcrText,
    TaskAutomation,
    describe_recognized_tasks,
    find_fertilizer_entry,
    find_goods_entry,
    find_task_action,
    has_task_dialog,
    parse_fertilizer,
)
from babanongchang.task_pool import TASK_POOL


GOODS_TASK = TASK_POOL[0]
SELECTED_GOODS_TASK = TASK_POOL[1]


def item(text: str, x: int, y: int, score: float = 0.99) -> OcrText:
    box = np.array([[x - 10, y - 5], [x + 10, y - 5], [x + 10, y + 5], [x - 10, y + 5]])
    return OcrText(text=text, score=score, box=box)


class ParseFertilizerTest(unittest.TestCase):
    def test_parses_combined_balance(self) -> None:
        items = [item("肥料68989", 360, 1150)]
        self.assertEqual(parse_fertilizer(items, (1600, 720, 3)), 68989)

    def test_ignores_product_reward(self) -> None:
        items = [item("肥料+70000", 200, 1450)]
        self.assertIsNone(parse_fertilizer(items, (1600, 720, 3)))

    def test_parses_split_balance(self) -> None:
        items = [item("肥料", 330, 1150), item("700", 390, 1150)]
        self.assertEqual(parse_fertilizer(items, (1600, 720, 3)), 700)


class FindGoodsEntryTest(unittest.TestCase):
    def test_finds_home_entry(self) -> None:
        entry = item("百县百品", 70, 350)
        self.assertIs(find_goods_entry([entry], (1600, 720, 3)), entry)

    def test_accepts_alternate_entry_text(self) -> None:
        entry = item("逛农货", 70, 350)
        self.assertIs(find_goods_entry([entry], (1600, 720, 3)), entry)

    def test_ignores_center_banner_with_same_text(self) -> None:
        entry = item("百县百品", 70, 350, score=0.90)
        banner = item("百县百品", 300, 350, score=0.99)
        self.assertIs(find_goods_entry([entry, banner], (1600, 720, 3)), entry)


class FindFertilizerEntryTest(unittest.TestCase):
    def test_finds_bottom_right_entry(self) -> None:
        entry = item("领肥料", 650, 1400)
        self.assertIs(find_fertilizer_entry([entry], (1600, 720, 3)), entry)

    def test_ignores_other_claim_text(self) -> None:
        other = item("领肥料", 200, 800)
        self.assertIsNone(find_fertilizer_entry([other], (1600, 720, 3)))


class HasTaskDialogTest(unittest.TestCase):
    def test_accepts_both_dialog_titles(self) -> None:
        for title in ("做任务集肥料", "做任务领肥料"):
            with self.subTest(title=title):
                self.assertTrue(has_task_dialog([item(title, 360, 527)]))

    def test_rejects_farm_home(self) -> None:
        self.assertFalse(has_task_dialog([item("支付宝·芭芭农场", 200, 100)]))


class FindTaskActionTest(unittest.TestCase):
    def test_finds_action_on_target_row(self) -> None:
        title = item("逛好物最高得3000肥", 250, 700)
        target = item("去完成", 640, 700)
        other = item("去完成", 640, 900)
        self.assertIs(
            find_task_action([title, target, other], (1600, 720, 3), GOODS_TASK),
            target,
        )

    def test_does_not_use_action_from_another_row(self) -> None:
        title = item("看精选商品得肥料", 250, 700)
        other = item("领取", 640, 900)
        self.assertIsNone(
            find_task_action(
                [title, other], (1600, 720, 3), SELECTED_GOODS_TASK, "领取"
            )
        )

    def test_finds_selected_goods_task(self) -> None:
        title = item("看精选商品得肥料 (0/3)", 250, 700)
        action = item("去完成", 640, 700)
        self.assertIs(
            find_task_action(
                [title, action], (1600, 720, 3), SELECTED_GOODS_TASK
            ),
            action,
        )

    def test_accepts_dynamic_goods_reward(self) -> None:
        action = item("去完成", 640, 700)
        for text in (
            "逛好物最高得3000肥 (0/1)",
            "逛一逛最高得2000肥 (0/2)",
            "逛好物最高得1500肥料",
            "逛好物立得1000肥",
        ):
            with self.subTest(text=text):
                title = item(text, 250, 700)
                self.assertIs(
                    find_task_action(
                        [title, action], (1600, 720, 3), GOODS_TASK
                    ),
                    action,
                )

    def test_accepts_go_browse_action(self) -> None:
        title = item("逛好物最高得1500肥料 (0/1)", 250, 700)
        action = item("去逛逛", 640, 700)
        self.assertIs(
            find_task_action(
                [title, action],
                (1600, 720, 3),
                GOODS_TASK,
            ),
            action,
        )


class TaskListSignatureTest(unittest.TestCase):
    def test_ignores_dynamic_non_task_text(self) -> None:
        first = [
            item("看精选商品得肥料 (1/3)", 250, 700),
            item("领取", 640, 700),
            item("12:30", 100, 30),
        ]
        second = [
            item("看精选商品得肥料 (1/3)", 250, 700),
            item("领取", 640, 700),
            item("12:31", 100, 30),
        ]
        self.assertEqual(
            TaskAutomation.task_list_signature(first),
            TaskAutomation.task_list_signature(second),
        )


class DescribeRecognizedTasksTest(unittest.TestCase):
    def test_describes_title_operation_and_action(self) -> None:
        descriptions = describe_recognized_tasks(
            [
                item("逛一逛支付宝会员 (0/1)", 250, 700),
                item("去逛逛", 640, 700),
            ],
            (1600, 720, 3),
        )
        self.assertEqual(
            descriptions,
            ["逛一逛支付宝会员 (0/1) -> click_and_return [去逛逛]"],
        )

    def test_reports_task_without_action(self) -> None:
        descriptions = describe_recognized_tasks(
            [item("看精选商品得肥料 (3/3)", 250, 700)],
            (1600, 720, 3),
        )
        self.assertEqual(
            descriptions,
            ["看精选商品得肥料 (3/3) -> swipe_browse [无可执行按钮]"],
        )


if __name__ == "__main__":
    unittest.main()
