from subprocess import CompletedProcess
import unittest
from unittest.mock import ANY, Mock, call, patch

import numpy as np

from babanongchang.adapters.adb import Adb
from babanongchang.automation.handle import AutomationError, OcrText, ScreenSnapshot, TextHandle, WaitTimeoutError
from babanongchang.cli import build_parser, main
from babanongchang.config import ProjectConfig
from babanongchang.farm.alipay.flow import (
    ALIPAY_HOME_ACTIVITY, ALIPAY_PACKAGE, AlipayAutomation, TaskAutomation,
    describe_recognized_tasks, find_fertilizer_entry, find_goods_entry, find_task_action,
    has_task_dialog, parse_fertilizer,
)
from babanongchang.workflow import FarmOptions, run_farm
from babanongchang.farm.alipay.task_pool import TASK_POOL


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


class ReturnToFarmTest(unittest.TestCase):
    def test_closes_dialog_before_accepting_visible_farm_controls(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        home = (item("肥料600", 360, 1150), item("施肥", 360, 1200))
        dialog = ScreenSnapshot(image, (*home, item("做任务领肥料", 360, 527)))
        farm = ScreenSnapshot(image, home)
        device = Mock()
        automation = TaskAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(side_effect=[dialog, farm, farm, farm])

        with patch("time.sleep"):
            automation.return_to_farm()

        automation.adb.back.assert_not_called()
        automation.adb.tap.assert_called_once()
        self.assertEqual(automation.screen.scan.call_count, 4)

    def test_does_not_go_back_when_already_on_farm(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        farm = ScreenSnapshot(
            image, (item("肥料0", 360, 1150), item("施肥", 360, 1200))
        )
        device = Mock()
        automation = TaskAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=farm)

        with patch("time.sleep"):
            automation.return_to_farm()

        automation.adb.back.assert_not_called()
        self.assertEqual(automation.screen.scan.call_count, 3)

    def test_stops_when_mask_click_does_not_close_dialog(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        dialog = ScreenSnapshot(image, (item("做任务集肥料", 360, 527),))
        device = Mock()
        automation = TaskAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=dialog)
        automation.screen.wait_for_screen = Mock(side_effect=WaitTimeoutError("弹窗未关闭"))
        automation.screen.wait_for_stable_screen = Mock()

        with self.assertRaisesRegex(WaitTimeoutError, "弹窗未关闭"):
            automation.return_to_farm(timeout=3)

        automation.adb.tap.assert_called_once_with((360, 309))
        automation.adb.back.assert_not_called()
        self.assertEqual(automation.screen.wait_for_screen.call_args.kwargs["timeout"], 3000)
        automation.screen.wait_for_stable_screen.assert_not_called()

    def test_does_not_click_unknown_page_or_unsafe_mask(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        for texts in ((), (item("做任务集肥料", 360, 200),)):
            with self.subTest(texts=texts):
                device = Mock()
                automation = TaskAutomation(device, TextHandle(device, ocr=Mock()))
                automation.screen.scan = Mock(return_value=ScreenSnapshot(image, texts))
                with self.assertRaises(AutomationError):
                    automation.return_to_farm()
                automation.adb.tap.assert_not_called()
                automation.adb.back.assert_not_called()


class InstalledPackagesTest(unittest.TestCase):
    def test_reads_exact_package_names(self) -> None:
        adb = Adb.__new__(Adb)
        adb._run = Mock(return_value=Mock(
            stdout=b"package:com.eg.android.AlipayGphone\npackage:com.taobao.taobao.extra\n"
        ))

        self.assertEqual(
            adb.installed_packages(),
            {ALIPAY_PACKAGE, "com.taobao.taobao.extra"},
        )
        adb._run.assert_called_once_with("shell", "pm", "list", "packages")

    def test_accepts_empty_list_and_propagates_query_errors(self) -> None:
        adb = Adb.__new__(Adb)
        adb._run = Mock(return_value=Mock(stdout=b""))
        self.assertEqual(adb.installed_packages(), set())
        adb._run.side_effect = AutomationError("设备断开")
        with self.assertRaisesRegex(AutomationError, "设备断开"):
            adb.installed_packages()

    def test_rejects_error_output_instead_of_reporting_no_apps(self) -> None:
        adb = Adb.__new__(Adb)
        adb._run = Mock(return_value=Mock(stdout=b"Error: permission denied\n"))
        with self.assertRaisesRegex(AutomationError, "无法读取"):
            adb.installed_packages()


class DeviceSelectionTest(unittest.TestCase):
    def make_adb(self, output: bytes) -> Adb:
        adb = Adb.__new__(Adb)
        adb.prefix = ["adb"]
        adb._run = Mock(return_value=Mock(stdout=output))
        return adb

    def test_uses_the_only_authorized_device_without_prompting(self) -> None:
        adb = self.make_adb(b"List of devices attached\nonly-device\tdevice\n")
        with patch("builtins.input") as prompt:
            self.assertEqual(adb._select_device(), "only-device")
        prompt.assert_not_called()

    def test_prompts_for_one_of_multiple_authorized_devices(self) -> None:
        adb = self.make_adb(
            b"List of devices attached\nfirst\tdevice\nsecond\tdevice\n"
            b"unauthorized\tunauthorized\n"
        )
        with patch("builtins.input", return_value="2") as prompt:
            self.assertEqual(adb._select_device(), "second")
        prompt.assert_called_once_with("请输入设备序号：")

    def test_reprompts_until_a_valid_device_number_is_entered(self) -> None:
        adb = self.make_adb(b"List of devices attached\nfirst\tdevice\nsecond\tdevice\n")
        with patch("builtins.input", side_effect=["0", "x", "1"]):
            self.assertEqual(adb._select_device(), "first")

    def test_fails_when_no_authorized_device_is_available(self) -> None:
        adb = self.make_adb(b"List of devices attached\nwaiting\tunauthorized\n")
        with self.assertRaisesRegex(AutomationError, "设备未连接或未授权"):
            adb._select_device()


class AdbCleanupTest(unittest.TestCase):
    def test_restores_screen_sleep_if_cancelled_during_setup(self) -> None:
        clock = Mock()

        def command(arguments, **kwargs):
            if arguments[-1] == "true":
                clock.checkpoint.side_effect = KeyboardInterrupt
            return CompletedProcess(arguments, 0, stdout=b"device\n", stderr=b"")

        with patch("babanongchang.adapters.adb.subprocess.run", side_effect=command) as run:
            with self.assertRaises(KeyboardInterrupt):
                Adb("device", clock=clock)

        self.assertEqual(run.call_args.args[0], ["adb", "-s", "device", "shell", "svc", "power", "stayon", "false"])


class AlipayAutomationTest(unittest.TestCase):
    def test_runs_alipay_stages_in_order(self) -> None:
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.threshold = 900
        automation.browse_seconds = 21
        automation.ensure_farm_page = Mock()
        automation.tasks.return_to_farm = Mock()
        with (
            patch.object(TaskAutomation, "run") as tasks,
            patch("babanongchang.farm.alipay.flow.GoodsAutomation") as goods,
            patch("babanongchang.farm.alipay.flow.FarmAutomation") as farm,
        ):
            calls = Mock()
            calls.attach_mock(automation.ensure_farm_page, "enter")
            calls.attach_mock(tasks, "tasks")
            calls.attach_mock(automation.tasks.return_to_farm, "return_home")
            calls.attach_mock(goods, "goods")
            calls.attach_mock(farm, "farm")
            automation.run(max_clicks=2)
            self.assertEqual(calls.mock_calls, [
                call.enter(), call.tasks(), call.return_home(),
                call.goods(automation.adb, automation.screen, 21, log=ANY), call.goods().run(),
                call.farm(automation.adb, automation.screen, threshold=900, browse_seconds=21, log=ANY),
                call.farm().run(max_clicks=2),
            ])

    def test_initializes_threshold_and_browse_duration(self) -> None:
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()), threshold=900, browse_seconds=21)
        self.assertEqual(automation.threshold, 900)
        self.assertEqual(automation.browse_seconds, 21)

    def test_enters_farm_from_home_with_one_click(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        entry = item("芭芭农场", 200, 500)
        home = ScreenSnapshot(image, (
            item("首页", 70, 1500), item("扫一扫", 100, 200), entry,
        ))
        farm = ScreenSnapshot(image, (
            item("肥料600", 360, 1150), item("施肥", 360, 1200),
        ))
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(side_effect=[home, home, home, farm, farm, farm])
        with patch("time.sleep"):
            automation.ensure_farm_page()
        automation.adb.start_activity.assert_called_once_with(ALIPAY_HOME_ACTIVITY)
        automation.adb.tap.assert_called_once_with(entry.center)
        automation.adb.back.assert_not_called()
        self.assertEqual(automation.screen.scan.call_count, 6)

    def test_enters_farm_when_home_label_is_not_recognized(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        entry = item("芭芭农场", 637, 403)
        home = ScreenSnapshot(image, (
            item("扫一扫", 88, 250), item("收付款", 270, 250), entry,
            item("理财", 269, 1544), item("消息", 449, 1544), item("我的", 629, 1544),
        ))
        farm = ScreenSnapshot(image, (
            item("肥料600", 360, 1150), item("施肥", 360, 1200),
        ))
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(side_effect=[home, home, home, farm, farm, farm])
        self.assertTrue(automation.is_home(home))
        with patch("time.sleep"):
            automation.ensure_farm_page()
        automation.adb.tap.assert_called_once_with(entry.center)
        automation.adb.back.assert_not_called()

    def test_accepts_existing_farm_without_clicking_entry(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        farm = ScreenSnapshot(image, (
            item("肥料600", 360, 1150), item("施肥", 360, 1200),
        ))
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=farm)
        with patch("time.sleep"):
            automation.ensure_farm_page()
        automation.adb.tap.assert_not_called()
        automation.adb.back.assert_not_called()

    def test_does_not_click_farm_text_outside_alipay_home(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=ScreenSnapshot(
            image, (item("芭芭农场", 200, 500),)
        ))
        with patch("time.monotonic", side_effect=[0, 0, 11, 61]), patch("time.sleep"):
            with self.assertRaisesRegex(AutomationError, "未能识别支付宝"):
                automation.ensure_farm_page()
        automation.adb.tap.assert_not_called()
        automation.adb.back.assert_not_called()

    def test_unrecognized_page_does_not_back_out_to_launcher(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=ScreenSnapshot(image, ()))
        with (
            patch("time.monotonic", side_effect=[0, 0, 0, 11, 11, 61]),
            patch("time.sleep"),
        ):
            with self.assertRaises(AutomationError):
                automation.ensure_farm_page()
        automation.adb.back.assert_not_called()

    def test_stops_if_home_entry_is_missing(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=ScreenSnapshot(image, (
            item("首页", 70, 1500), item("扫一扫", 100, 200),
        )))
        automation.screen.wait_for_stable_text = Mock(side_effect=WaitTimeoutError("未找到入口"))
        with self.assertRaisesRegex(WaitTimeoutError, "未找到入口"):
            automation.ensure_farm_page()
        automation.adb.tap.assert_not_called()

    def test_stops_without_reclicking_when_farm_does_not_open(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        entry = item("芭芭农场", 200, 500)
        home = ScreenSnapshot(image, (
            item("首页", 70, 1500), item("扫一扫", 100, 200), entry,
        ))
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=home)
        automation.screen.wait_for_stable_text = Mock(return_value=entry)
        automation.screen.wait_for_screen = Mock(side_effect=WaitTimeoutError("未进入农场"))
        with self.assertRaisesRegex(WaitTimeoutError, "未进入农场"):
            automation.ensure_farm_page()
        automation.adb.tap.assert_called_once_with(entry.center)
        automation.adb.back.assert_not_called()

    def test_accepts_open_task_dialog(self) -> None:
        image = np.zeros((1600, 720, 3), dtype=np.uint8)
        device = Mock()
        automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
        automation.screen.scan = Mock(return_value=ScreenSnapshot(
            image, (item("做任务领肥料", 360, 527),)
        ))
        automation.tasks.wait_for_task_list_stable = Mock()
        automation.ensure_farm_page()
        automation.tasks.wait_for_task_list_stable.assert_called_once_with()
        automation.adb.tap.assert_not_called()

    def test_does_not_continue_after_a_stage_fails(self) -> None:
        for stage in ("enter", "tasks", "return", "goods"):
            with (
                self.subTest(stage=stage),
                patch.object(TaskAutomation, "run") as tasks,
                patch("babanongchang.farm.alipay.flow.GoodsAutomation") as goods,
                patch("babanongchang.farm.alipay.flow.FarmAutomation") as farm,
            ):
                device = Mock()
                automation = AlipayAutomation(device, TextHandle(device, ocr=Mock()))
                automation.browse_seconds = 18
                automation.threshold = 600
                automation.ensure_farm_page = Mock()
                automation.tasks.return_to_farm = Mock()
                action = {
                    "enter": automation.ensure_farm_page,
                    "tasks": tasks,
                    "return": automation.tasks.return_to_farm,
                    "goods": goods.return_value.run,
                }[stage]
                action.side_effect = AutomationError("阶段失败")
                with self.assertRaisesRegex(AutomationError, "阶段失败"):
                    automation.run()
                farm.assert_not_called()
                if stage != "goods":
                    goods.assert_not_called()


class WorkflowTest(unittest.TestCase):
    def test_runs_only_installed_apps_in_alipay_first_order(self) -> None:
        taobao_package = "com.taobao.taobao"
        for packages, expected in (
            (set(), []),
            ({ALIPAY_PACKAGE}, ["alipay"]),
            ({taobao_package}, ["taobao"]),
            ({ALIPAY_PACKAGE, taobao_package}, ["alipay", "taobao"]),
            ({taobao_package + ".extra"}, []),
        ):
            with (
                self.subTest(packages=packages),
                patch("babanongchang.workflow.AlipayAutomation") as alipay,
                patch("babanongchang.workflow.TaobaoAutomation") as taobao,
                patch("builtins.print") as output,
            ):
                taobao.PACKAGE = taobao_package
                adb = Mock()
                adb.installed_packages.return_value = packages
                order = []
                alipay.return_value.run.side_effect = lambda **kwargs: order.append("alipay")
                taobao.return_value.run.side_effect = lambda: order.append("taobao")
                run_farm("all", FarmOptions(900, 21, 2), device=adb, ocr=Mock(), config=ProjectConfig(), log=output)
                self.assertEqual(order, expected)
                if "alipay" in expected:
                    alipay.assert_called_once_with(adb, ANY, 900, 21, log=output)
                    alipay.return_value.run.assert_called_once_with(max_clicks=2)
                else:
                    alipay.assert_not_called()
                if "taobao" in expected:
                    taobao.assert_called_once_with(adb, ANY, log=output)
                    taobao.return_value.run.assert_called_once_with()
                else:
                    taobao.assert_not_called()
                if not expected:
                    output.assert_called_once_with("未安装支付宝或淘宝，流程结束")

    def test_checks_for_alipay_after_taobao_without_repeating_apps(self) -> None:
        with (
            patch("babanongchang.workflow.AlipayAutomation") as alipay,
            patch("babanongchang.workflow.TaobaoAutomation") as taobao,
        ):
            taobao.PACKAGE = "com.taobao.taobao"
            adb = Mock()
            adb.installed_packages.side_effect = [
                {taobao.PACKAGE}, {ALIPAY_PACKAGE, taobao.PACKAGE},
                {ALIPAY_PACKAGE, taobao.PACKAGE},
            ]
            calls = Mock()
            calls.attach_mock(taobao, "taobao")
            calls.attach_mock(alipay, "alipay")
            run_farm("all", FarmOptions(), device=adb, ocr=Mock(), config=ProjectConfig())
            self.assertEqual(calls.mock_calls, [
                call.taobao(adb, ANY, log=ANY), call.taobao().run(),
                call.alipay(adb, ANY, 600, 18, log=ANY),
                call.alipay().run(max_clicks=None),
            ])

    def test_stops_without_switching_apps_after_failure(self) -> None:
        with (
            patch("babanongchang.workflow.AlipayAutomation") as alipay,
            patch("babanongchang.workflow.TaobaoAutomation") as taobao,
        ):
            taobao.PACKAGE = "com.taobao.taobao"
            adb = Mock()
            adb.installed_packages.return_value = {ALIPAY_PACKAGE, taobao.PACKAGE}
            alipay.return_value.run.side_effect = AutomationError("支付宝失败")
            with self.assertRaisesRegex(AutomationError, "支付宝失败"):
                run_farm("all", FarmOptions(), device=adb, ocr=Mock(), config=ProjectConfig())
            taobao.assert_not_called()


class CliDispatchTest(unittest.TestCase):
    def test_defaults_to_all_and_preserves_explicit_modules(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args([]).module, "all")
        for module in ("all", "fertilize", "goods", "tasks", "taobao"):
            with self.subTest(module=module):
                self.assertEqual(parser.parse_args([module]).module, module)

    def test_dispatches_default_workflow_and_restores_screen_sleep(self) -> None:
        with (
            patch(
                "sys.argv",
                [
                    "babanongchang",
                    "--serial", "device",
                    "--threshold", "900",
                    "--browse-seconds", "21",
                    "--max-clicks", "2",
                ],
            ),
            patch("babanongchang.cli.Adb") as adb,
            patch("babanongchang.cli.run_farm") as workflow,
        ):
            main()

            adb.assert_called_once_with("device", clock=ANY)
            workflow.assert_called_once_with(
                "all", FarmOptions(900, 21, 2), device=adb.return_value, ocr=ANY,
                config=ANY, clock=adb.call_args.kwargs["clock"],
            )
            adb.return_value.allow_screen_sleep.assert_called_once_with()

    def test_stops_safely_and_restores_screen_sleep_when_workflow_fails(self) -> None:
        with (
            patch("sys.argv", ["babanongchang"]),
            patch("babanongchang.cli.Adb") as adb,
            patch("babanongchang.cli.run_farm", side_effect=AutomationError("阶段失败")),
        ):
            with self.assertRaisesRegex(SystemExit, "自动化已安全停止：阶段失败"):
                main()

            adb.return_value.allow_screen_sleep.assert_called_once_with()

    def test_explicit_modules_do_not_run_workflow(self) -> None:
        for module, target in (
            ("fertilize", "FarmAutomation"),
            ("goods", "GoodsAutomation"),
            ("tasks", "TaskAutomation"),
            ("taobao", "TaobaoAutomation"),
        ):
            with (
                self.subTest(module=module),
                patch("sys.argv", ["babanongchang", module]),
                patch("babanongchang.cli.Adb") as adb,
                patch(f"babanongchang.workflow.{target}") as automation,
            ):
                main()

                adb.return_value.installed_packages.assert_not_called()
                automation.assert_called_once()
                if module == "fertilize":
                    automation.return_value.run.assert_called_once_with(max_clicks=None)
                else:
                    automation.return_value.run.assert_called_once_with()
                adb.return_value.allow_screen_sleep.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
