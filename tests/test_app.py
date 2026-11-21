import os
from pathlib import Path
import queue
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from babanongchang.adb_devices import AdbDevice, parse_adb_devices
from babanongchang.winproc import hidden_subprocess_kwargs
from babanongchang.app_core import (
    DeviceBoard,
    TaskProcess,
    build_arguments,
    defaults_for,
    effective_parameters,
    FEATURE_BY_KEY,
    nlgj_progress_from_values,
    progress_ratio,
    progress_text,
    save_ocr_config,
    validate_settings,
)
from babanongchang.app import FarmApp
from babanongchang.cli import main
from babanongchang.desktop_runtime import DesktopRuntimeBackend
from babanongchang.launch import cli_command, desktop_argv


class WindowIconTest(unittest.TestCase):
    def test_packaged_icon_is_readable(self) -> None:
        from importlib.resources import files

        icon = files("babanongchang").joinpath("icon.png")
        self.assertTrue(icon.is_file())
        self.assertGreater(icon.stat().st_size, 1000)


class AppDispatchTest(unittest.TestCase):
    def test_frozen_app_reinvokes_itself_without_python_module(self) -> None:
        executable = r"C:\app\babanongchang.exe"
        self.assertEqual(
            cli_command(["games", "--nlgj"], executable),
            [executable, "-m", "babanongchang.cli", "games", "--nlgj"],
        )
        with patch("babanongchang.launch.sys") as frozen_sys:
            frozen_sys.frozen = True
            self.assertEqual(desktop_argv([]), ["app"])
            self.assertEqual(
                cli_command(["games", "--nlgj"], executable),
                [executable, "games", "--nlgj"],
            )
            self.assertEqual(desktop_argv(["games", "--nlgj"]), ["games", "--nlgj"])

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
    def test_refresh_hides_the_adb_console_on_windows(self) -> None:
        with patch("babanongchang.adb_devices.subprocess.check_output", return_value="") as run:
            from babanongchang.adb_devices import list_adb_devices

            list_adb_devices()
        if os.name == "nt":
            self.assertEqual(run.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW, subprocess.CREATE_NO_WINDOW)
        else:
            self.assertNotIn("creationflags", run.call_args.kwargs)
        self.assertEqual(hidden_subprocess_kwargs(1).get("creationflags", 0) & 1, 1 if os.name == "nt" else 0)

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
            build_arguments("nlgj", defaults_for(FEATURE_BY_KEY["nlgj"]), "phone"),
            ["games", "--nlgj", "--serial", "phone"],
        )

    def test_game_requires_device_even_when_only_inspecting(self) -> None:
        values = defaults_for(FEATURE_BY_KEY["nlgj"])
        self.assertNotIn("screenshot", values)
        self.assertNotIn("ocr", values)
        for dry_run in (False, True):
            values["dry_run"] = dry_run
            with self.subTest(dry_run=dry_run), self.assertRaisesRegex(ValueError, "已授权设备"):
                build_arguments("nlgj", values, None)
        self.assertEqual(
            build_arguments("nlgj", values, "phone"),
            ["games", "--nlgj", "--serial", "phone", "--dry-run"],
        )

    def test_validates_linked_game_fields(self) -> None:
        values = defaults_for(FEATURE_BY_KEY["nlgj"])
        values["board_top"] = "0.9"
        values["board_bottom"] = "0.2"
        errors = validate_settings("nlgj", values)
        self.assertIn("board_bottom", errors)

    def test_target_overrides_game_limits(self) -> None:
        values = defaults_for(FEATURE_BY_KEY["nlgj"])
        values.update({"target": "12", "levels": "bad", "max_minutes": "bad"})
        self.assertEqual(validate_settings("nlgj", values), {})
        self.assertEqual(
            build_arguments("nlgj", values, "phone"),
            ["games", "--nlgj", "--serial", "phone", "--target", "12"],
        )
        labels = dict(effective_parameters("nlgj", values))
        self.assertNotIn("通关次数", labels)
        self.assertNotIn("最长运行时间（分钟）", labels)


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
                backend.sleep(1)

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


def _device(serial: str, state: str = "device", model: str | None = None) -> AdbDevice:
    details = (("model", model),) if model else ()
    return AdbDevice(serial, state, details)


class _FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled: list[str] = []
        self._next = 0

    def after(self, delay: int, callback) -> str:
        self._next += 1
        token = f"after-{self._next}"
        self.after_calls.append((delay, callback))
        return token

    def after_cancel(self, token: str) -> None:
        self.cancelled.append(token)


class DevicePollTest(unittest.TestCase):
    def test_poll_refreshes_quietly_and_reschedules(self) -> None:
        app = FarmApp.__new__(FarmApp)
        app.root = _FakeRoot()
        app.board = DeviceBoard()
        app.close_after_stop = False
        app._discovering = False
        app._device_poll_ms = 3000
        app._device_poll_timer = None
        app.refresh_button = type("Button", (), {"configure": lambda *args, **kwargs: None})()
        statuses: list[tuple[str, str]] = []
        started: list[bool] = []
        app._set_status = lambda title, detail: statuses.append((title, detail))
        app._discover_devices = lambda: started.append(True)

        app._schedule_device_poll()
        self.assertEqual(app.root.after_calls[-1][0], 3000)
        app.root.after_calls[-1][1]()

        self.assertTrue(started)
        self.assertEqual(statuses, [])
        self.assertIsNotNone(app._device_poll_timer)
        self.assertEqual(len(app.root.after_calls), 2)

    def test_close_cancels_pending_poll(self) -> None:
        app = FarmApp.__new__(FarmApp)
        app.root = _FakeRoot()
        app.runners = {}
        app.close_after_stop = False
        app._device_poll_timer = "after-1"
        destroyed: list[bool] = []
        app.root.destroy = lambda: destroyed.append(True)

        app._close()

        self.assertEqual(app.root.cancelled, ["after-1"])
        self.assertIsNone(app._device_poll_timer)
        self.assertTrue(destroyed)


class DeviceBoardTest(unittest.TestCase):
    def test_jobs_stay_independent_and_new_phones_do_not_start(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A", model="Pixel"), _device("B", "unauthorized"), _device("C", "offline")))
        board.select("A")
        self.assertFalse(board.can_start("B"))
        self.assertFalse(board.can_start("C"))
        board.begin("A", "all", "一键照料", None)
        board.apply_devices((_device("A", model="Pixel"), _device("D", model="New")))
        self.assertNotIn("D", board.runs)
        self.assertFalse(board.runs["A"].disconnected)
        self.assertFalse(board.can_start("A"))
        self.assertFalse(board.can_start())
        self.assertTrue(board.can_stop("A"))
        board.select(None)
        self.assertFalse(board.can_start())
        self.assertFalse(board.can_stop())
        self.assertEqual(board.header(), ("1 台运行中", "选择一台设备查看日志"))

    def test_missing_live_serial_stays_until_exit(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A", model="Pixel"), _device("B")))
        board.select("A")
        board.begin("A", "all", "一键照料", None)
        board.append_log("A", "hello\n")
        board.apply_devices((_device("B"),))
        self.assertIn("A", board.order)
        self.assertTrue(board.runs["A"].disconnected)
        self.assertEqual(board.selected, "A")
        self.assertEqual(board.header(), ("已断开", "ADB 已看不到此设备，任务仍在运行"))
        board.request_stop("A")
        self.assertEqual(board.header()[1], "已请求安全停止；ADB 已看不到此设备")
        board.finish("A", code=0, stopped=True, forced=False)
        self.assertNotIn("A", board.order)
        self.assertNotIn("A", board.logs)
        self.assertIsNone(board.selected)

    def test_same_serial_reappearing_clears_disconnected(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A", model="Pixel"),))
        board.begin("A", "all", "一键照料", None)
        board.apply_devices(())
        board.apply_devices((_device("A", model="Pixel 2"),))
        self.assertFalse(board.runs["A"].disconnected)
        self.assertEqual(board.runs["A"].model, "Pixel 2")
        self.assertEqual(board.order.count("A"), 1)

    def test_idle_disappearance_drops_log_and_result(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"), _device("B")))
        board.logs["A"] = "session"
        board.results["A"] = ("已完成", "流程正常结束；业务结果请以日志为准")
        board.select("A")
        board.apply_devices((_device("B"),))
        self.assertEqual(board.order, ("B",))
        self.assertNotIn("A", board.logs)
        self.assertNotIn("A", board.results)
        self.assertIsNone(board.selected)

    def test_nlgj_output_conflict_uses_resolved_path(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"), _device("B")))
        board.begin("A", "nlgj", "挪了个箭", "")
        message = "另一台正在把挪了个箭写入同一输出目录，请改输出目录。"
        self.assertEqual(board.output_conflict("nlgj", None), message)
        self.assertEqual(board.output_conflict("nlgj", str(Path("artifacts/nlgj").resolve())), message)
        self.assertIsNone(board.output_conflict("nlgj", "artifacts/other"))
        self.assertIsNone(board.output_conflict("fertilize", "artifacts/nlgj"))

    def test_restart_clears_only_that_devices_log(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"), _device("B")))
        board.begin("A", "all", "一键照料", None)
        board.begin("B", "fertilize", "施肥", None)
        board.append_log("A", "old-a")
        board.append_log("B", "keep-b")
        board.finish("A", code=0, stopped=False, forced=False)
        self.assertEqual(board.results["A"][0], "已完成")
        board.begin("A", "all", "一键照料", None)
        self.assertEqual(board.logs["A"], "")
        self.assertEqual(board.logs["B"], "keep-b")
        self.assertNotIn("A", board.results)

    def test_finish_results_and_row_text(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A", model="Pixel"), _device("B", "unauthorized")))
        board.begin("A", "all", "一键照料", None)
        board.finish("A", code=2, stopped=False, forced=False)
        board.select("A")
        self.assertEqual(board.header(), ("运行失败", "子进程退出码：2"))
        self.assertIn("Pixel", board.row_text("A"))
        self.assertIn("运行失败", board.row_text("A"))
        board.select("B")
        self.assertEqual(board.header(), ("无法开始", "设备未授权或未连接"))
        self.assertIn("未授权", board.row_text("B"))
        board.finish("missing", code=0, stopped=False, forced=True)
        self.assertEqual(board.order, ("A", "B"))


class NlgjProgressTest(unittest.TestCase):
    def test_target_progress_uses_current_level(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A", model="Pixel"),))
        board.begin("A", "nlgj", "挪了个箭", None, nlgj_progress_from_values({"target": "100", "levels": "bad"}))
        changed = board.append_log("A", '{"event": "level", "level": 50, "arrows": 3}\n')
        progress = board.progress["A"]
        self.assertTrue(changed)
        self.assertEqual(progress_text(progress), "第 50 关 / 目标 100")
        self.assertEqual(progress_ratio(progress), (50, 100))
        self.assertIn("第 50 关", board.row_text("A"))
        board.select("A")
        board.append_log("A", '{"event": "stop", "reason": "Time limit reached"}\n')
        board.finish("A", code=0, stopped=False, forced=False)
        self.assertEqual(progress_text(board.progress["A"]), "超时停止 · 第 50 关 / 目标 100")
        self.assertEqual(progress_ratio(board.progress["A"]), (50, 100))
        self.assertEqual(board.header(), ("超时停止", "停在第 50 关"))

    def test_levels_progress_counts_wins_and_keeps_level(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"),))
        board.begin("A", "nlgj", "挪了个箭", None, nlgj_progress_from_values({"target": "  ", "levels": "3"}))
        board.append_log("A", "不是进度\n{not json}\n")
        board.append_log("A", '{"event": "completed", "level": 12, "completed": 1}\n')
        progress = board.progress["A"]
        self.assertEqual(progress_text(progress), "第 12 关 · 已通关 1/3")
        self.assertEqual(progress_ratio(progress), (1, 3))

    def test_timeout_stop_keeps_progress(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"),))
        board.select("A")
        board.begin("A", "nlgj", "挪了个箭", None, nlgj_progress_from_values({"target": "", "levels": "3"}))
        board.append_log("A", '{"event": "level", "level": 50}\n')
        board.append_log("A", '{"event": "stop", "reason": "Time limit reached"}\n')
        board.finish("A", code=0, stopped=False, forced=False)
        progress = board.progress["A"]
        self.assertTrue(progress.stopped)
        self.assertEqual(progress_text(progress), "超时停止 · 第 50 关 · 已通关 0/3")
        self.assertEqual(board.header(), ("超时停止", "停在第 50 关"))
        self.assertIn("第 50 关", board.row_text("A"))

    def test_new_job_clears_previous_progress(self) -> None:
        board = DeviceBoard()
        board.apply_devices((_device("A"), _device("B")))
        board.begin("A", "nlgj", "挪了个箭", None, nlgj_progress_from_values({"levels": "0"}))
        board.append_log("A", '{"event": "revived", "level": 4}\n')
        board.finish("A", code=1, stopped=False, forced=False)
        self.assertEqual(progress_text(board.progress["A"]), "已停止 · 第 4 关")
        self.assertIsNone(progress_ratio(board.progress["A"]))
        board.begin("A", "fertilize", "施肥", None)
        self.assertNotIn("A", board.progress)
        board.apply_devices((_device("B"),))
        self.assertNotIn("A", board.progress)


if __name__ == "__main__":
    unittest.main()
