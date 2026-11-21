import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from babanongchang.cli import main
from babanongchang.nlgj.fast import fast_sequence
from babanongchang.nlgj.ocr import ScreenReader
from babanongchang.nlgj.recognition import head_template, recognize


def arrow_board():
    image = np.full((1600, 720, 3), 255, np.uint8)
    head = head_template() > 0
    for y in (400, 650):
        image[y:y + head.shape[0], 300:300 + head.shape[1]][head] = (60, 40, 20)
    return image


class NlgjIntegrationTest(unittest.TestCase):
    def test_offline_command_recognizes_board_and_writes_report_without_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "board.png"
            output = Path(directory) / "output"
            cv2.imwrite(str(image), arrow_board())
            with (
                patch("sys.argv", ["babanongchang", "games", "--nlgj",
                                   "--screenshot", str(image), "--output", str(output)]),
                patch("babanongchang.cli.Adb") as adb,
                patch("babanongchang.nlgj.runner.Device") as device,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                main()
            adb.assert_not_called()
            device.assert_not_called()
            report = json.loads((output / "report.json").read_text())
            self.assertTrue(report["valid"], report["reason"])
            self.assertEqual(report["arrows"], 2)
            self.assertEqual(report["order"], [2, 1])
            self.assertTrue((output / "annotated.png").is_file())

    def test_dispatch_preserves_serial_and_game_options_without_farm_adb(self):
        with (
            patch("sys.argv", ["babanongchang", "games", "--nlgj", "--serial", "device",
                               "--mode", "fast", "--target", "100", "--no-revive-ads"]),
            patch("babanongchang.cli.Adb") as adb,
            patch("babanongchang.nlgj.runner.play") as play,
        ):
            main()
        adb.assert_not_called()
        args = play.call_args.args[0]
        self.assertEqual((args.serial, args.mode, args.target), ("device", "fast", 100))
        self.assertFalse(args.revive_ads)

    def test_invalid_selection_and_options_never_access_device(self):
        for options in (
            ["games"], ["--nlgj"], ["games", "--nlgj", "--majiang"],
            ["games", "--nlgj", "--board-top", "0.9"],
            ["games", "--nlgj", "--target", "0"],
            ["games", "--nlgj", "--levels", "-1"],
            ["games", "--nlgj", "--delay", "0"],
        ):
            with (
                self.subTest(options=options),
                patch("sys.argv", ["babanongchang", *options]),
                patch("babanongchang.cli.Adb") as adb,
                patch("babanongchang.nlgj.runner.Device") as device,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                main()
            adb.assert_not_called()
            device.assert_not_called()

    def test_majiang_dispatch_still_restores_screen_sleep(self):
        with (
            patch("sys.argv", ["babanongchang", "games", "--majiang"]),
            patch("babanongchang.cli.Adb") as adb,
            patch("babanongchang.majiang.MajiangAutomation") as game,
        ):
            main()
        game.assert_called_once_with(adb.return_value)
        game.return_value.run.assert_called_once_with()
        adb.return_value.allow_screen_sleep.assert_called_once_with()

    def test_runtime_failure_becomes_safe_exit(self):
        with (
            patch("sys.argv", ["babanongchang", "games", "--nlgj"]),
            patch("babanongchang.nlgj.runner.play", side_effect=RuntimeError("foreground changed")),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as error,
        ):
            main()
        self.assertEqual(error.exception.code, 1)


class NlgjRecognitionTest(unittest.TestCase):
    def test_fast_sequence_respects_recognized_obstacles(self):
        board = recognize(arrow_board())
        self.assertTrue(board.valid, board.reason)
        self.assertEqual([step[0] for step in fast_sequence(board)], [2, 1])
        board.no_tap = [(0, 600, 719, 800)]
        self.assertEqual(fast_sequence(board), [])

    def test_dimmed_board_is_rejected(self):
        board = recognize(arrow_board() // 2)
        self.assertFalse(board.valid)
        self.assertIn("dimmed/covered", board.reason)

    def test_default_crop_includes_arrows_near_the_canvas_top(self):
        image = np.full((1600, 720, 3), 255, np.uint8)
        head = head_template() > 0
        image[250:250 + head.shape[0], 300:300 + head.shape[1]][head] = (60, 40, 20)
        board = recognize(image)
        self.assertTrue(board.valid, board.reason)
        self.assertEqual(len(board.arrows), 1)


class NlgjOcrTest(unittest.TestCase):
    def test_converts_project_rapidocr_result(self):
        reader = ScreenReader()
        result = SimpleNamespace(
            boxes=np.array([[[10, 20], [30, 20], [30, 40], [10, 40]]]),
            txts=("奖励 已发放",), scores=(.99,),
        )
        with patch("rapidocr.RapidOCR", return_value=Mock(return_value=result)) as engine:
            self.assertEqual(reader.read(arrow_board()), [("奖励已发放", .99, 20, 30)])
            reader.read(arrow_board())
        engine.assert_called_once_with()

    def test_empty_ocr_result(self):
        reader = ScreenReader()
        reader.engine = Mock(return_value=SimpleNamespace(boxes=None, txts=None, scores=None))
        self.assertEqual(reader.read(arrow_board()), [])
