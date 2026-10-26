import unittest

import numpy as np

from babanongchang.handle import OcrText, ScreenSnapshot, TextHandle
from babanongchang.navigation import back_until


IMAGE = np.zeros((1600, 720, 3), dtype=np.uint8)


def snapshot(text: str) -> ScreenSnapshot:
    box = np.array([[90, 95], [110, 95], [110, 105], [90, 105]])
    return ScreenSnapshot(
        image=IMAGE,
        items=(OcrText(text=text, score=0.99, box=box),),
    )


class FakeBackDevice:
    def __init__(self) -> None:
        self.back_count = 0

    def back(self) -> None:
        self.back_count += 1


class SequenceHandle:
    def __init__(self, frames: list[ScreenSnapshot]) -> None:
        self.frames = frames

    def scan(self) -> ScreenSnapshot:
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


class BackUntilTest(unittest.TestCase):
    def test_returns_until_target_screen_appears(self) -> None:
        device = FakeBackDevice()
        handle = SequenceHandle([snapshot("其他页"), snapshot("任务列表")])

        result = back_until(
            device,
            handle,
            lambda current: TextHandle.has_text(current.items, "任务列表"),
            timeout=1000,
            interval=1,
        )

        self.assertEqual(result.back_count, 1)
        self.assertEqual(device.back_count, 1)

    def test_does_not_go_back_when_already_on_target(self) -> None:
        device = FakeBackDevice()
        handle = SequenceHandle([snapshot("任务列表")])

        result = back_until(
            device,
            handle,
            lambda current: TextHandle.has_text(current.items, "任务列表"),
            timeout=1000,
            interval=1,
        )

        self.assertEqual(result.back_count, 0)
        self.assertEqual(device.back_count, 0)
