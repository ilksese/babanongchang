import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from babanongchang import android, runtime
from babanongchang.handle import TextHandle


class AndroidDeviceTest(unittest.TestCase):
    def setUp(self):
        self.bridge = Mock()
        self.device = android.AndroidDevice(self.bridge)

    def test_screenshot_and_ocr_use_platform_without_desktop_engine(self):
        image = np.full((60, 100, 3), (12, 40, 200), np.uint8)
        self.bridge.capture.return_value = cv2.imencode(".png", image)[1].tobytes()
        self.bridge.recognize.return_value = json.dumps([
            ["肥料1200", [[10, 20], [90, 20], [90, 40], [10, 40]], .98],
        ])
        with patch("babanongchang.handle.RapidOCR", side_effect=AssertionError("desktop OCR")):
            frame = TextHandle(self.device).scan()
        np.testing.assert_array_equal(frame.image, image)
        self.assertEqual(frame.texts, ("肥料1200",))
        self.assertEqual(frame.items[0].center, (50, 30))
        supplied = cv2.imdecode(np.frombuffer(self.bridge.recognize.call_args.args[0], np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(supplied, image)

    def test_game_coordinates_scale_back_to_original_screen(self):
        self.bridge.foreground.return_value = "game"
        image = np.full((2400, 1080, 3), 255, np.uint8)
        self.bridge.capture.return_value = cv2.imencode(".png", image)[1].tobytes()
        game = android.AndroidGameDevice(self.device)
        self.assertEqual(game.screenshot().shape, (1600, 720, 3))
        game.tap(360, 800)
        self.bridge.tap.assert_called_once_with(540, 1200)
        game.swipe_ad(True)
        self.bridge.swipe.assert_called_once_with(540, 1872, 540, 720, 650)

    def test_game_does_not_tap_or_capture_after_foreground_changes(self):
        self.bridge.foreground.side_effect = ["game", "other", "other", "other"]
        game = android.AndroidGameDevice(self.device)
        for action in (lambda: game.tap(10, 20), game.screenshot, lambda: game.swipe_ad(True)):
            with self.assertRaisesRegex(RuntimeError, "前台应用"):
                action()
        self.bridge.tap.assert_not_called()
        self.bridge.swipe.assert_not_called()
        self.bridge.capture.assert_not_called()

    def test_ocr_centers_can_be_serialized_in_offline_report(self):
        self.bridge.recognize.return_value = json.dumps([
            ["下一关", [[10, 20], [90, 20], [90, 40], [10, 40]], .97],
        ])
        lines = android.AndroidScreenReader(self.device.ocr).read(np.zeros((60, 100, 3), np.uint8))
        self.assertEqual(json.loads(json.dumps(lines))[0][2:], [50, 30])

    def test_native_low_confidence_text_does_not_pass_shared_ocr_filter(self):
        self.bridge.capture.return_value = cv2.imencode(".png", np.zeros((60, 100, 3), np.uint8))[1].tobytes()
        self.bridge.recognize.return_value = json.dumps([
            ["肥料1200", [[10, 20], [90, 20], [90, 40], [10, 40]], .3],
        ])
        self.assertEqual(TextHandle(self.device).scan().items, ())


class AndroidEntryTest(unittest.TestCase):
    def test_taobao_confidence_is_applied_only_to_taobao(self):
        from babanongchang.cli import FarmAutomation
        from babanongchang.taobao import TaobaoAutomation, is_taobao_farm_page

        bridge = Mock()
        bridge.capture.return_value = cv2.imencode(".png", np.zeros((1600, 720, 3), np.uint8))[1].tobytes()
        bridge.recognize.return_value = json.dumps([
            ["芭芭农场1免费领水果", [[100, 70], [440, 70], [440, 110], [100, 110]], .523],
            ["施肥", [[320, 1130], [400, 1130], [400, 1170], [320, 1170]], .688],
        ])
        with tempfile.TemporaryDirectory() as output, patch("babanongchang.cli.main") as main:
            android.run(bridge, "taobao", "", output, .5)
            device = main.call_args.kwargs["device_factory"](None)
            self.assertTrue(is_taobao_farm_page(TaobaoAutomation(device).scan().items))
            self.assertFalse(is_taobao_farm_page(FarmAutomation(device).scan().items))

            android.run(bridge, "all", "", output)
            reset_device = main.call_args.kwargs["device_factory"](None)
            self.assertEqual(TaobaoAutomation(reset_device).min_score, .75)
            self.assertEqual(device.taobao_min_score, .5)

    def test_rejects_invalid_taobao_confidence_before_device_access(self):
        bridge = Mock()
        for value in (-.01, 1.01, float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "置信度"):
                android.run(bridge, "taobao", "", "unused", value)
        bridge.capture.assert_not_called()

    def test_all_modules_use_injected_device_and_original_arguments(self):
        with tempfile.TemporaryDirectory() as output:
            for module in ("all", "fertilize", "goods", "tasks", "taobao", "games"):
                with self.subTest(module=module), patch("babanongchang.cli.main") as main:
                    bridge = Mock()
                    options = "--majiang" if module == "games" else "--threshold 700 --max-clicks 2"
                    android.run(bridge, module, options, output)
                    args, kwargs = main.call_args
                    self.assertEqual(args[0][0], module)
                    self.assertEqual(args[0][-2:], ["--output", output])
                    self.assertIsInstance(kwargs["device_factory"](None), android.AndroidDevice)
                    self.assertIsNone(runtime.backend)

    def test_native_backend_is_reset_on_failure(self):
        with patch("babanongchang.cli.main", side_effect=RuntimeError("failed")):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                android.run(Mock(), "all", "", "/tmp/output")
        self.assertIsNone(runtime.backend)

    def test_nlgj_injects_native_game_device_and_reader(self):
        bridge = Mock()
        bridge.foreground.return_value = "game"
        with patch("babanongchang.cli.main") as main:
            android.run(bridge, "games", "--nlgj --mode fast --target 100", "/tmp/output")
        self.assertIsInstance(main.call_args.kwargs["game_device"], android.AndroidGameDevice)
        self.assertIsInstance(main.call_args.kwargs["game_reader"], android.AndroidScreenReader)

    def test_offline_recognition_runs_without_device_calls(self):
        bridge = Mock()
        bridge.capture.side_effect = AssertionError("offline captured device")
        bridge.foreground.side_effect = AssertionError("offline queried device")
        bridge.recognize.return_value = "[]"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "board with spaces.png"
            cv2.imwrite(str(image), np.full((1600, 720, 3), 255, np.uint8))
            android.run(bridge, "games", f"--nlgj --screenshot '{image}' --ocr", directory)
            self.assertTrue((Path(directory) / "report.json").is_file())
            self.assertTrue((Path(directory) / "annotated.png").is_file())
        bridge.tap.assert_not_called()
        bridge.capture.assert_not_called()
        bridge.foreground.assert_not_called()

    def test_rejects_adb_options_on_phone(self):
        for options in ("--serial device", "--adb custom-adb"):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "不支持"):
                android.run(Mock(), "all", options, "/tmp/output")

    def test_real_cli_routes_to_workflow_with_native_device(self):
        with tempfile.TemporaryDirectory() as output, patch("babanongchang.cli.run_workflow") as workflow:
            bridge = Mock()
            android.run(bridge, "all", "--threshold 700 --max-clicks 2", output)
        self.assertIsInstance(workflow.call_args.args[0], android.AndroidDevice)
        self.assertEqual(workflow.call_args.kwargs, {"threshold": 700, "browse_seconds": 18, "max_clicks": 2})

    def test_real_cli_routes_to_game_with_native_dependencies(self):
        bridge = Mock()
        bridge.foreground.return_value = "game"
        with tempfile.TemporaryDirectory() as output, patch("babanongchang.nlgj.runner.play") as play:
            android.run(bridge, "games", "--nlgj --mode fast --target 100", output)
        self.assertEqual(play.call_args.args[0].target, 100)
        self.assertEqual(play.call_args.args[0].mode, "fast")
        self.assertIsInstance(play.call_args.kwargs["device"], android.AndroidGameDevice)
        self.assertIsInstance(play.call_args.kwargs["reader"], android.AndroidScreenReader)


class AndroidRuntimeTest(unittest.TestCase):
    def test_native_clock_and_wait_are_used(self):
        bridge = Mock()
        bridge.activeMillis.return_value = 5000
        with patch.object(runtime, "backend", bridge):
            self.assertEqual(runtime.monotonic(), 5)
            runtime.sleep(.65)
        bridge.sleepMillis.assert_called_once_with(650)


if __name__ == "__main__":
    unittest.main()
