import unittest
from unittest.mock import Mock, patch

import numpy as np

from babanongchang.handle import OcrText, ScreenSnapshot
from babanongchang.taobao import (
    TaobaoAutomation,
    TaobaoTaskOperation,
    find_available_taobao_task,
    find_available_taobao_search_task,
    find_taobao_farm_entry,
    find_taobao_fertilizer_entry,
    find_taobao_recommended_keyword,
    find_taobao_task_action,
    is_taobao_discovery_page,
    is_taobao_farm_page,
    is_taobao_fertilizer_tasks_page,
    is_taobao_recommended_video_page,
    is_taobao_search_reward_page,
    is_taobao_search_results_page,
)


def item(text: str, x: int, y: int, score: float = 0.99) -> OcrText:
    box = np.array([[x - 10, y - 5], [x + 10, y - 5], [x + 10, y + 5], [x - 10, y + 5]])
    return OcrText(text=text, score=score, box=box)


class FakeAdb:
    def __init__(self) -> None:
        self.started_activities: list[str] = []

    def start_activity(self, component: str) -> None:
        self.started_activities.append(component)


class TestableTaobaoAutomation(TaobaoAutomation):
    def __init__(self, adb: FakeAdb) -> None:
        self.adb = adb  # type: ignore[assignment]
        self.entered_fertilizer_tasks = False
        self.completed_supported_tasks = False

    def ensure_fertilizer_tasks_page(self, timeout: float = 60) -> None:
        self.adb.start_activity(self.HOME_ACTIVITY)
        self.entered_fertilizer_tasks = True

    def complete_supported_tasks(self) -> None:
        self.completed_supported_tasks = True


class TaobaoAutomationTest(unittest.TestCase):
    def test_coins_task_waits_three_seconds_stays_eight_seconds_and_returns(
        self,
    ) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        button = item("去完成", 614, 955)
        titles = (item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345))
        before = ScreenSnapshot(
            image, (*titles, item("去淘金币逛买更省钱(0/1)", 306, 934), button)
        )
        automation = TaobaoAutomation.__new__(TaobaoAutomation)
        automation.adb = Mock()
        automation.scan = Mock(side_effect=[before, ScreenSnapshot(image, titles)])
        events = []

        automation.adb.tap = Mock(
            side_effect=lambda point: events.append(("tapped", point))
        )
        automation.return_to_fertilizer_tasks = Mock(
            side_effect=lambda: events.append("returned")
        )
        with patch(
            "babanongchang.taobao.time.sleep",
            side_effect=lambda seconds: events.append(("slept", seconds)),
        ) as sleep:
            automation.complete_supported_tasks()

        automation.adb.tap.assert_called_once_with(button.center)
        self.assertEqual(
            [entry.args for entry in sleep.call_args_list], [(3,), (8,)]
        )
        automation.return_to_fertilizer_tasks.assert_called_once_with()
        automation.adb.swipe.assert_not_called()
        self.assertEqual(
            events,
            [("tapped", button.center), ("slept", 3), ("slept", 8), "returned"],
        )

    def test_browses_selected_products_for_eighteen_seconds_and_returns(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        button = item("去完成", 614, 955)
        titles = (item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345))
        before = ScreenSnapshot(
            image, (*titles, item("逛精选好物(0/3)", 306, 934), button)
        )
        discovery = ScreenSnapshot(
            image,
            (item("浏览得奖励", 135, 101), item("下单得肥料+167000", 203, 671)),
        )
        automation = TaobaoAutomation.__new__(TaobaoAutomation)
        automation.adb = Mock()
        automation.scan = Mock(
            side_effect=[before, ScreenSnapshot(image, titles)]
        )
        events = []

        def tap_and_wait(point, matcher, **kwargs):
            self.assertEqual(point, button.center)
            self.assertIsNone(matcher(before))
            self.assertIsNone(matcher(ScreenSnapshot(image, titles)))
            self.assertIs(matcher(discovery), discovery)
            events.append("entered")

        automation.tap_and_wait = Mock(side_effect=tap_and_wait)
        automation.return_to_fertilizer_tasks = Mock(
            side_effect=lambda: events.append("returned")
        )
        with patch(
            "babanongchang.taobao.swipe_browse",
            side_effect=lambda adb, duration_seconds: events.append(
                ("browsed", duration_seconds)
            ),
        ) as swipe:
            automation.complete_supported_tasks()

        automation.tap_and_wait.assert_called_once()
        swipe.assert_called_once()
        automation.return_to_fertilizer_tasks.assert_called_once_with()
        self.assertEqual(events, ["entered", ("browsed", 18), "returned"])

    def test_reuses_current_task_list_without_starting_home_activity(self) -> None:
        snapshot = ScreenSnapshot(
            np.zeros((1600, 720, 3), dtype=np.uint8),
            (item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345)),
        )
        automation = TaobaoAutomation.__new__(TaobaoAutomation)
        automation.adb = Mock()
        automation.scan = Mock(return_value=snapshot)
        automation.complete_supported_tasks = Mock()

        automation.run()

        automation.adb.start_activity.assert_not_called()
        automation.adb.tap.assert_not_called()
        automation.adb.back.assert_not_called()
        automation.complete_supported_tasks.assert_called_once_with()

    def test_starts_home_activity_when_current_page_is_not_task_list(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        tasks = ScreenSnapshot(
            image,
            (item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345)),
        )
        automation = TaobaoAutomation.__new__(TaobaoAutomation)
        automation.adb = Mock()
        automation.scan = Mock(side_effect=[ScreenSnapshot(image, ()), tasks])

        automation.ensure_fertilizer_tasks_page()

        automation.adb.start_activity.assert_called_once_with(automation.HOME_ACTIVITY)
        self.assertEqual(automation.scan.call_count, 2)

    def test_sign_in_clicks_once_and_rescans_without_returning(self) -> None:
        button = item("去签到", 600, 464)
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        titles = (item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345))
        before = ScreenSnapshot(image, (*titles, button))
        after = ScreenSnapshot(image, (*titles, item("已签到", 600, 464)))
        automation = TaobaoAutomation.__new__(TaobaoAutomation)
        automation.scan = Mock(side_effect=[before, after])
        automation.return_to_fertilizer_tasks = Mock()

        def tap_and_wait(point, matcher, **kwargs):
            self.assertEqual(point, button.center)
            self.assertIsNone(matcher(before))
            self.assertIs(matcher(after), after)

        automation.tap_and_wait = Mock(side_effect=tap_and_wait)

        automation.complete_supported_tasks()

        automation.tap_and_wait.assert_called_once()
        automation.return_to_fertilizer_tasks.assert_not_called()
        self.assertEqual(automation.scan.call_count, 2)

    def test_starts_home_activity_and_runs_complete_flow(self) -> None:
        adb = FakeAdb()
        automation = TestableTaobaoAutomation(adb)

        automation.run()

        self.assertEqual(
            adb.started_activities,
            ["com.taobao.taobao/com.taobao.tao.welcome.Welcome"],
        )
        self.assertTrue(automation.entered_fertilizer_tasks)
        self.assertTrue(automation.completed_supported_tasks)


class TaobaoPageTest(unittest.TestCase):
    def test_finds_sign_in_button_without_task_title(self) -> None:
        button = item("去 签到", 600, 464)
        found = find_available_taobao_task([button], (1600, 720, 3))
        self.assertIsNotNone(found)
        assert found is not None
        self.assertIs(found[0].operation, TaobaoTaskOperation.SIGN_IN)
        self.assertIs(found[1], button)

    def test_does_not_select_completed_or_partial_sign_in_text(self) -> None:
        for text in ("已签到", "已完成", "去签到领肥料"):
            with self.subTest(text=text):
                self.assertIsNone(
                    find_available_taobao_task([item(text, 600, 464)], (1600, 720, 3))
                )

    def test_finds_farm_entry(self) -> None:
        entry = item("芭芭农场", 75, 431)
        self.assertIs(find_taobao_farm_entry([entry]), entry)

    def test_recognizes_farm_page(self) -> None:
        items = [item("芭芭农场 | 免费领水果", 270, 93), item("施肥", 360, 1154)]
        self.assertTrue(is_taobao_farm_page(items))

    def test_does_not_treat_home_entry_as_farm_page(self) -> None:
        self.assertFalse(is_taobao_farm_page([item("芭芭农场", 75, 431)]))

    def test_finds_fertilizer_entry(self) -> None:
        entry = item("集肥料", 539, 1205)
        self.assertIs(find_taobao_fertilizer_entry([entry]), entry)

    def test_recognizes_fertilizer_tasks_page(self) -> None:
        items = [item("做任务赚肥料", 360, 345), item("肥料明细", 81, 345)]
        self.assertTrue(is_taobao_fertilizer_tasks_page(items))

    def test_finds_search_task_action_on_same_row(self) -> None:
        target = item("去完成", 614, 591)
        other = item("去完成", 614, 719)
        items = [item("搜一搜你喜欢的商品(0/6)", 306, 570), target, other]
        self.assertIs(
            find_taobao_task_action(items, (1600, 720, 3), "搜一搜你喜欢的商品"),
            target,
        )

    def test_prefers_available_favorite_products_task(self) -> None:
        favorite = item("去完成", 614, 591)
        desired = item("去完成", 614, 976)
        items = [
            item("搜一搜你喜欢的商品(1/6)", 306, 570),
            favorite,
            item("搜一搜你心仪的宝贝(0/5)", 306, 957),
            desired,
        ]
        self.assertEqual(
            find_available_taobao_search_task(items, (1600, 720, 3)),
            ("搜一搜你喜欢的商品", favorite),
        )

    def test_uses_desired_products_when_favorite_is_unavailable(self) -> None:
        desired = item("去完成", 614, 976)
        items = [item("搜一搜你心仪的宝贝(0/5)", 306, 957), desired]
        self.assertEqual(
            find_available_taobao_search_task(items, (1600, 720, 3)),
            ("搜一搜你心仪的宝贝", desired),
        )

    def test_selects_supported_task_in_screen_order(self) -> None:
        discovery = item("去完成", 614, 591)
        search = item("去完成", 614, 719)
        recommended = item("去完成", 614, 976)
        items = [
            item("发现精选好物(3/6)", 269, 570),
            discovery,
            item("搜一搜你喜欢的商品(4/6)", 306, 699),
            search,
            item("看严选推荐商品(2/5)", 281, 957),
            recommended,
        ]

        found = find_available_taobao_task(items, (1600, 720, 3))

        self.assertIsNotNone(found)
        assert found is not None
        task, button = found
        self.assertEqual(task.name, "发现精选好物")
        self.assertIs(task.operation, TaobaoTaskOperation.SWIPE_BROWSE)
        self.assertIs(button, discovery)

    def test_screen_order_takes_priority_over_task_type(self) -> None:
        search = item("去完成", 614, 591)
        discovery = item("去完成", 614, 719)
        items = [
            item("搜一搜你心仪的宝贝(4/6)", 306, 570),
            search,
            item("发现精选好物(3/6)", 269, 699),
            discovery,
        ]

        found = find_available_taobao_task(items, (1600, 720, 3))

        self.assertIsNotNone(found)
        assert found is not None
        task, button = found
        self.assertEqual(task.name, "搜一搜你心仪的宝贝")
        self.assertIs(task.operation, TaobaoTaskOperation.SEARCH)
        self.assertIs(button, search)

    def test_finds_selected_products_browse_task(self) -> None:
        button = item("去完成", 614, 955)
        items = [item("逛精选好物(0/3)", 306, 934), button]

        found = find_available_taobao_task(items, (1600, 720, 3))

        self.assertIsNotNone(found)
        assert found is not None
        task, found_button = found
        self.assertEqual(task.name, "逛精选好物")
        self.assertIs(task.operation, TaobaoTaskOperation.SWIPE_BROWSE)
        self.assertIs(found_button, button)

    def test_recognizes_search_reward_page(self) -> None:
        items = [item("搜索有福利", 125, 99), item("搜索后浏览立得奖励", 572, 95)]
        self.assertTrue(is_taobao_search_reward_page(items))

    def test_finds_first_recommended_keyword(self) -> None:
        keyword = item("iphone18", 192, 678)
        items = [
            item("搜索发现", 80, 601),
            keyword,
            item("近一个月点击超10万", 215, 718),
        ]
        self.assertIs(find_taobao_recommended_keyword(items), keyword)

    def test_recognizes_search_results_page(self) -> None:
        items = [item("搜索有福利", 136, 101), item("滑动浏览得肥料", 520, 100)]
        self.assertTrue(is_taobao_search_results_page(items))

    def test_recognizes_discovery_product_page(self) -> None:
        items = [
            item("浏览得奖励", 135, 101),
            item("下单得肥料+167000", 203, 671),
        ]
        self.assertTrue(is_taobao_discovery_page(items))

    def test_does_not_treat_other_reward_page_as_discovery_page(self) -> None:
        self.assertFalse(is_taobao_discovery_page([item("浏览得奖励", 135, 101)]))

    def test_recognizes_recommended_product_video_page(self) -> None:
        items = [item("滑动浏览得", 646, 1007), item("肥料", 646, 1030)]
        self.assertTrue(is_taobao_recommended_video_page(items))
