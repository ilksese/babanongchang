import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from babanongchang.adb_devices import parse_adb_devices
from babanongchang.app_core import (
    TaskProcess,
    build_arguments,
    defaults_for,
    effective_parameters,
    FEATURE_BY_KEY,
    requires_device,
    save_ocr_config,
    validate_settings,
)
from babanongchang.cli import main
from babanongchang.desktop_runtime import DesktopRuntimeBackend


class AppDispatchTest(unittest.TestCase):
    def test_app_dispatch_does_not_create_adb(self) -> None:
        with (
            patch("babanongchang.app.run_app") as run_app,
            patch("babanongchang.cli.Adb") as adb,
        ):
            main(["app"])
        run_app.assert_called_once_with()
        adb.assert_not_called()

    def test_app_rejects_every_other_argument(self) -> None:
        for arguments in (["app", "--threshold", "100"], ["app", "--help"], ["--serial", "x", "app"]):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                main(arguments)


class AdbDeviceParsingTest(unittest.TestCase):
    def test_preserves_all_states_and_details(self) -> None:
        devices = parse_adb_devices(
            "List of devices attached\n"
            "ABC\tdevice product:p model:Pixel_8 transport_id:1\n"
            "DEF\tunauthorized usb:2-1\n"
            "GHI\toffline\n\n"
        )
        self.assertEqual([(item.serial, item.state) for item in devices], [
            ("ABC", "device"), ("DEF", "unauthorized"), ("GHI", "offline")
        ])
        self.assertEqual(devices[0].model, "Pixel_8")


class AppArgumentTest(unittest.TestCase):
    def test_builds_common_and_game_arguments(self) -> None:
        values = defaults_for(FEATURE_BY_KEY["fertilize"])
        values["threshold"] = "900"
        values["max_clicks"] = "2"
        self.assertEqual(
            build_arguments("fertilize", values, "phone"),
            ["fertilize", "--serial", "phone", "--threshold", "900", "--max-clicks", "2"],
        )
        self.assertEqual(
            build_arguments("majiang", {}, "phone"),
            ["games", "--majiang", "--serial", "phone"],
        )

    def test_offline_screenshot_needs_no_device_and_hides_online_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "board.png"
            screenshot.touch()
            values = defaults_for(FEATURE_BY_KEY["nlgj"])
            values.update({"screenshot": str(screenshot), "ocr": True, "target": "12"})
            self.assertFalse(requires_device("nlgj", values))
            arguments = build_arguments("nlgj", values, None)
            self.assertEqual(arguments[:2], ["games", "--nlgj"])
            self.assertIn("--screenshot", arguments)
            self.assertIn("--ocr", arguments)
            self.assertNotIn("--target", arguments)
            self.assertNotIn("--levels", arguments)
            labels = dict(effective_parameters("nlgj", values))
            self.assertNotIn("通关次数", labels)
            self.assertNotIn("允许广告复活", labels)
            self.assertEqual(labels["离线报告包含 OCR"], "是")

    def test_validates_linked_game_fields(self) -> None:
        values = defaults_for(FEATURE_BY_KEY["nlgj"])
        values["board_top"] = "0.9"
        values["board_bottom"] = "0.2"
        values["ocr"] = True
        errors = validate_settings("nlgj", values)
        self.assertIn("board_bottom", errors)
        self.assertIn("ocr", errors)

    def test_hidden_online_values_do_not_block_offline_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "board.png"
            screenshot.touch()
            values = defaults_for(FEATURE_BY_KEY["nlgj"])
            values.update({"screenshot": str(screenshot), "levels": "bad", "max_minutes": "bad"})
            self.assertEqual(validate_settings("nlgj", values), {})


class OcrConfigWritingTest(unittest.TestCase):
    def test_preserves_comments_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "babanongchang.toml"
            path.write_text("# keep me\n[other]\nvalue = 7\n", encoding="utf-8")
            save_ocr_config(path, 250, 12000)
            text = path.read_text(encoding="utf-8")
            self.assertIn("# keep me", text)
            self.assertIn("[other]", text)
            self.assertIn("value = 7", text)
            self.assertIn("screenshot_interval_ms = 250", text)
            self.assertFalse(path.with_suffix(".toml.tmp").exists())


class DesktopCancellationTest(unittest.TestCase):
    def test_control_file_interrupts_sleep(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cancel = Path(directory) / "cancel"
            backend = DesktopRuntimeBackend(cancel)
            cancel.touch()
            with self.assertRaises(KeyboardInterrupt):
                backend.sleepMillis(1000)

    def test_task_process_streams_output_and_reports_exit(self) -> None:
        events = queue.Queue()
        process = TaskProcess(events)
        with tempfile.TemporaryDirectory() as directory, patch(
            "babanongchang.app_core.sys.executable", os.environ.get("PYTHON", os.sys.executable)
        ):
            process.start(["--help"], Path(directory))
            kinds = []
            while "exit" not in kinds:
                kind, _payload = events.get(timeout=10)
                kinds.append(kind)
        self.assertIn("log", kinds)
        self.assertEqual(kinds[-1], "exit")


if __name__ == "__main__":
    unittest.main()
