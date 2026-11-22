from contextlib import ExitStack
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from babanongchang.nlgj import runner
from babanongchang.nlgj.options import GameOptions


class TargetPriorityTest(unittest.TestCase):
    def run_game(self, target, max_minutes=15, record_events=True):
        image = np.zeros((100, 100, 3), np.uint8)
        device = Mock(package="game")
        device.screenshot.side_effect = [image, image, image, RuntimeError("continued")]
        board = SimpleNamespace(valid=True, arrows={1: object()})
        victory = SimpleNamespace(valid=False, reason="No arrows")
        reader = Mock()
        reader.read.side_effect = [[("关卡279", .99, 0, 0)], [("下一关", .99, 90, 90)]]
        with tempfile.TemporaryDirectory() as output, ExitStack() as stack:
            options = GameOptions(
                output=Path(output),
                max_minutes=max_minutes, target=target, levels=1, mode="fast",
                board_top=.165, board_bottom=.83, dry_run=False,
                revive_ads=False, streak_policy="stop", max_restarts=0,
                idle_timeout=10000,
            )
            patches = {
                "recognize": Mock(side_effect=[board, board, victory]),
                "dark_board": Mock(return_value=np.zeros((100, 100), np.uint8)),
                "white_board_background": Mock(return_value=True),
                "heart_count": Mock(return_value=3),
                "fast_sequence": Mock(return_value=[(1, 50, 50)]),
                "tap_sequence": Mock(),
                "annotate": Mock(return_value=image),
                "popup_action": Mock(return_value=None),
                "streak_action": Mock(return_value=None),
            }
            for name, value in patches.items():
                stack.enter_context(patch.object(runner, name, value))
            stack.enter_context(patch.object(runner.cv2, "imwrite", return_value=True))
            clock = Mock()
            clock.monotonic.side_effect = range(0, 10000, 61)
            error = None
            try:
                runner.play(
                    options, device=device, reader=reader, clock=clock,
                    record_events=record_events,
                )
            except RuntimeError as exc:
                error = str(exc)
            log_path = Path(output) / "events.jsonl"
            return error, log_path.read_text() if log_path.is_file() else ""

    def test_does_not_write_event_log_unless_requested(self):
        error, log = self.run_game(target=None, record_events=False)
        self.assertIsNone(error)
        self.assertEqual(log, "")

    def test_target_ignores_win_limit(self):
        error, log = self.run_game(target=293)
        self.assertEqual(error, "continued")
        self.assertNotIn("Requested number of wins reached", log)

    def test_target_ignores_total_time_limit(self):
        error, log = self.run_game(target=293, max_minutes=1)
        self.assertEqual(error, "continued")
        self.assertNotIn("Time limit reached", log)

    def test_target_stops_after_target_victory(self):
        error, log = self.run_game(target=279)
        self.assertIsNone(error)
        self.assertIn("Target reached", log)

    def test_without_target_win_limit_still_applies(self):
        error, log = self.run_game(target=None)
        self.assertIsNone(error)
        self.assertIn("Requested number of wins reached", log)

    def test_without_target_time_limit_still_applies(self):
        error, log = self.run_game(target=None, max_minutes=1)
        self.assertIsNone(error)
        self.assertIn("Time limit reached", log)


if __name__ == "__main__":
    unittest.main()
