import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from babanongchang import android
from babanongchang.adapters.android import AndroidClock, AndroidDevice, AndroidGameDevice, AndroidOcr, AndroidScreenReader
from babanongchang.automation.handle import TextHandle


def fake_engine(ocr):
    def recognize(image):
        png = cv2.imencode(".png", image)[1].tobytes()
        lines = json.loads(str(ocr.bridge.recognize(png)))
        return SimpleNamespace(txts=[line[0] for line in lines],
                               boxes=[line[1] for line in lines],
                               scores=[line[2] for line in lines])
    engine = Mock(side_effect=recognize)
    engine.text_det = engine.text_cls = engine.text_rec = None
    return engine


class AndroidDeviceTest(unittest.TestCase):
    def setUp(self):
        loader = patch.object(AndroidOcr, "_load_engine", autospec=True, side_effect=fake_engine)
        loader.start()
        self.addCleanup(loader.stop)
        self.bridge = Mock()
        self.device = AndroidDevice(self.bridge)

    def test_screenshot_and_ocr_use_platform_without_desktop_engine(self):
        image = np.full((60, 100, 3), (12, 40, 200), np.uint8)
        self.bridge.capture.return_value = cv2.imencode(".png", image)[1].tobytes()
        self.bridge.recognize.return_value = json.dumps([
            ["肥料1200", [[10, 20], [90, 20], [90, 40], [10, 40]], .98],
        ])
        frame = TextHandle(self.device, ocr=self.device.ocr).scan()
        np.testing.assert_array_equal(frame.image, image)
        self.assertEqual(frame.texts, ("肥料1200",))
        self.assertEqual(frame.items[0].center, (50, 30))
        supplied = cv2.imdecode(np.frombuffer(self.bridge.recognize.call_args.args[0], np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(supplied, image)

    def test_game_coordinates_scale_back_to_original_screen(self):
        self.bridge.foreground.return_value = "game"
        image = np.full((2400, 1080, 3), 255, np.uint8)
        self.bridge.capture.return_value = cv2.imencode(".png", image)[1].tobytes()
        game = AndroidGameDevice(self.device)
        self.assertEqual(game.screenshot().shape, (1600, 720, 3))
        game.tap(360, 800)
        self.bridge.tap.assert_called_once_with(540, 1200)
        game.swipe_ad(True)
        self.bridge.swipe.assert_called_once_with(540, 1872, 540, 720, 650)

    def test_game_does_not_tap_or_capture_after_foreground_changes(self):
        self.bridge.foreground.side_effect = ["game", "other", "other", "other"]
        game = AndroidGameDevice(self.device)
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
        lines = AndroidScreenReader(self.device.ocr).read(np.zeros((60, 100, 3), np.uint8))
        self.assertEqual(json.loads(json.dumps(lines))[0][2:], [50, 30])

    def test_native_low_confidence_text_does_not_pass_shared_ocr_filter(self):
        self.bridge.capture.return_value = cv2.imencode(".png", np.zeros((60, 100, 3), np.uint8))[1].tobytes()
        self.bridge.recognize.return_value = json.dumps([
            ["肥料1200", [[10, 20], [90, 20], [90, 40], [10, 40]], .3],
        ])
        self.assertEqual(TextHandle(self.device, ocr=self.device.ocr).scan().items, ())


class AndroidEntryTest(unittest.TestCase):
    def setUp(self):
        loader = patch.object(AndroidOcr, "_load_engine", autospec=True, side_effect=fake_engine)
        loader.start()
        self.addCleanup(loader.stop)

    def test_taobao_confidence_is_applied_only_to_taobao(self):
        from babanongchang.farm.taobao.flow import is_taobao_farm_page

        bridge = Mock()
        bridge.capture.return_value = cv2.imencode(".png", np.zeros((1600, 720, 3), np.uint8))[1].tobytes()
        bridge.recognize.return_value = json.dumps([
            ["芭芭农场1免费领水果", [[100, 70], [440, 70], [440, 110], [100, 110]], .523],
            ["施肥", [[320, 1130], [400, 1130], [400, 1170], [320, 1170]], .688],
        ])
        observations = []

        def observe(automation, *args, **kwargs):
            observations.append(is_taobao_farm_page(automation.screen.scan().items))

        with (
            tempfile.TemporaryDirectory() as output,
            patch("babanongchang.workflow.TaobaoAutomation.run", autospec=True, side_effect=observe),
            patch("babanongchang.workflow.FarmAutomation.run", autospec=True, side_effect=observe),
        ):
            android.run(bridge, "taobao", "", output, .5)
            android.run(bridge, "fertilize", "", output, .5)
            android.run(bridge, "taobao", "", output)
        self.assertEqual(observations, [True, False, False])

    def test_rejects_invalid_taobao_confidence_before_device_access(self):
        bridge = Mock()
        for value in (-.01, 1.01, float("nan")):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "置信度"):
                android.run(bridge, "taobao", "", "unused", value)
        bridge.capture.assert_not_called()

    def test_farm_modules_use_native_dependencies_without_changing_working_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory() as output:
            (Path(output) / "babanongchang.toml").write_text("[ocr]\nscreenshot_interval_ms = 321\n")

            def observe(module, options, **kwargs):
                self.assertEqual(Path.cwd(), original)
                self.assertEqual(kwargs["config"].screenshot_interval_ms, 321)
                self.assertIsInstance(kwargs["device"], AndroidDevice)
                self.assertIsInstance(kwargs["clock"], AndroidClock)
                self.assertEqual((options.threshold, options.max_clicks), (700, 2))
                kwargs["log"](module)

            for module in ("all", "fertilize", "goods", "tasks", "taobao"):
                with self.subTest(module=module), patch.object(android, "run_farm", side_effect=observe) as run:
                    bridge = Mock()
                    android.run(bridge, module, "--threshold 700 --max-clicks 2", output)
                    self.assertEqual(run.call_args.args[0], module)
                    bridge.log.assert_called_once_with(f"{module}\n")

    def test_closes_native_ocr_on_failure(self):
        with (
            tempfile.TemporaryDirectory() as output,
            patch.object(android, "run_farm", side_effect=RuntimeError("failed")),
            patch.object(AndroidOcr, "close") as close,
        ):
            with self.assertRaisesRegex(RuntimeError, "failed"):
                android.run(Mock(), "all", "", output)
        close.assert_called_once_with()

    def test_offline_recognition_runs_without_device_calls(self):
        bridge = Mock()
        bridge.capture.side_effect = AssertionError("offline captured device")
        bridge.foreground.side_effect = AssertionError("offline queried device")
        bridge.recognize.return_value = "[]"
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "board with spaces.png"
            cv2.imwrite(str(image), np.full((1600, 720, 3), 255, np.uint8))
            android.run(bridge, "games", "--nlgj --screenshot 'board with spaces.png' --output report --ocr", directory)
            self.assertTrue((Path(directory) / "report/report.json").is_file())
            self.assertTrue((Path(directory) / "report/annotated.png").is_file())
        bridge.tap.assert_not_called()
        bridge.capture.assert_not_called()
        bridge.foreground.assert_not_called()

    def test_rejects_adb_options_on_phone(self):
        for options in ("--serial device", "--adb custom-adb"):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "不支持"):
                android.run(Mock(), "all", options, "/tmp/output")

    def test_routes_to_game_with_native_dependencies(self):
        bridge = Mock()
        bridge.foreground.return_value = "game"
        with tempfile.TemporaryDirectory() as output, patch("babanongchang.nlgj.runner.play") as play:
            android.run(bridge, "games", "--nlgj --mode fast --target 100", output)
        self.assertEqual(play.call_args.args[0].target, 100)
        self.assertEqual(play.call_args.args[0].mode, "fast")
        self.assertEqual(play.call_args.args[0].output, Path(output).resolve())
        self.assertIsInstance(play.call_args.kwargs["device"], AndroidGameDevice)
        self.assertIsInstance(play.call_args.kwargs["reader"], AndroidScreenReader)


class AndroidRuntimeTest(unittest.TestCase):
    def test_native_clock_and_wait_are_used(self):
        bridge = Mock()
        bridge.activeMillis.return_value = 5000
        clock = AndroidClock(bridge)
        self.assertEqual(clock.monotonic(), 5)
        clock.sleep(.65)
        bridge.sleepMillis.assert_called_once_with(650)


if __name__ == "__main__":
    unittest.main()
