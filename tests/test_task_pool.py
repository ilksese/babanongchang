import unittest

from babanongchang.task_pool import TASK_POOL, TaskMatcher, TaskOperation


class TaskMatcherTest(unittest.TestCase):
    def test_matches_fixed_text(self) -> None:
        matcher = TaskMatcher(fixed_text="看精选商品得肥料")
        self.assertTrue(matcher.matches("看精选商品得肥料 (0/3)"))
        self.assertFalse(matcher.matches("任意下单领大额肥料"))

    def test_matches_regular_expression(self) -> None:
        matcher = TaskMatcher(pattern=r"逛好物立得\d+肥料?")
        self.assertTrue(matcher.matches("逛好物立得1000肥"))
        self.assertTrue(matcher.matches("逛好物立得1500肥料"))

    def test_requires_exactly_one_matching_strategy(self) -> None:
        with self.assertRaises(ValueError):
            TaskMatcher()
        with self.assertRaises(ValueError):
            TaskMatcher(fixed_text="任务", pattern="任务")


class SwipeBrowseTaskPoolTest(unittest.TestCase):
    def test_local_flavors_task_browses_for_eighteen_seconds(self) -> None:
        for title in ("逛乡土寻味专场得肥料", "逛乡土寻味专场得肥料 (0/1)"):
            with self.subTest(title=title):
                matched = [task for task in TASK_POOL if task.matches(title)]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0].operation, TaskOperation.SWIPE_BROWSE)
                self.assertEqual(matched[0].duration_seconds, 18)
                self.assertEqual(matched[0].action_labels, ("去完成", "去逛逛"))


class ClickAndReturnTaskPoolTest(unittest.TestCase):
    def test_matches_fixed_click_and_return_tasks(self) -> None:
        titles = (
            "逛支付宝得金豆 (0/1)",
            "逛支付宝金豆得宝 (0/1)",
            "逛一逛蚂蚁庄园 (0/1)",
            "逛一逛森林组队种 (0/1)",
            "逛一逛支付宝会员 (0/1)",
            "逛一逛金豆乐园 (0/1)",
        )
        click_tasks = [
            task
            for task in TASK_POOL
            if task.operation is TaskOperation.CLICK_AND_RETURN
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(any(task.matches(title) for task in click_tasks))

    def test_play_my_game_stays_for_ten_minutes(self) -> None:
        matched = [task for task in TASK_POOL if task.matches("玩一玩我的花园世界")]
        self.assertEqual(len(matched), 1)
        self.assertTrue(matched[0].enabled)
        self.assertEqual(matched[0].stay_seconds, 600)

    def test_click_and_return_defaults_to_immediate_return(self) -> None:
        task = next(task for task in TASK_POOL if task.key == "visit-ant-manor")
        self.assertEqual(task.stay_seconds, 0)

    def test_alipay_member_accepts_go_browse_action(self) -> None:
        task = next(task for task in TASK_POOL if task.key == "visit-alipay-member")
        self.assertIn("去逛逛", task.action_labels)


if __name__ == "__main__":
    unittest.main()
