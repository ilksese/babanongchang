import unittest
from types import SimpleNamespace

import numpy as np

from babanongchang.handle import (
    OcrText,
    RelativeRegion,
    ScreenSnapshot,
    TextHandle,
    normalize_text,
)


IMAGE = np.zeros((1600, 720, 3), dtype=np.uint8)


def item(text: str, x: int, y: int, score: float = 0.99) -> OcrText:
    box = np.array(
        [[x - 10, y - 5], [x + 10, y - 5], [x + 10, y + 5], [x - 10, y + 5]]
    )
    return OcrText(text=text, score=score, box=box)


def snapshot(*items: OcrText) -> ScreenSnapshot:
    return ScreenSnapshot(image=IMAGE, items=items)


class FakeTapAdb:
    def __init__(self) -> None:
        self.taps: list[tuple[int, int]] = []

    def tap(self, point: tuple[int, int]) -> None:
        self.taps.append(point)


class FakeScreenAdb(FakeTapAdb):
    def screenshot(self) -> np.ndarray:
        return IMAGE


class TextOperationHandle(TextHandle):
    def __init__(self, frames: list[ScreenSnapshot]) -> None:
        self.adb = FakeTapAdb()
        self.frames = frames

    def scan(self) -> ScreenSnapshot:
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


class ScanTest(unittest.TestCase):
    def test_scans_and_filters_low_confidence_text(self) -> None:
        ocr = lambda image: SimpleNamespace(  # noqa: E731
            txts=["保留", "过滤"],
            scores=[0.9, 0.5],
            boxes=[item("", 100, 200).box, item("", 300, 400).box],
        )
        handle = TextHandle(FakeScreenAdb(), ocr=ocr, min_score=0.75)

        result = handle.scan()

        self.assertIs(result.image, IMAGE)
        self.assertEqual(result.texts, ("保留",))


class TextMatchingTest(unittest.TestCase):
    def test_normalizes_all_whitespace(self) -> None:
        self.assertEqual(normalize_text("做 任务\n赚\t肥料"), "做任务赚肥料")

    def test_finds_all_text_in_reading_order_and_region(self) -> None:
        top = item("去 完成", 620, 500, score=0.8)
        bottom = item("去完成", 620, 700, score=0.99)
        outside = item("去完成", 200, 400)

        matches = TextHandle.find_texts(
            [bottom, outside, top],
            "去完成",
            region=RelativeRegion(left=0.55),
            image_shape=IMAGE.shape,
            order="reading",
        )

        self.assertEqual(matches, [top, bottom])

    def test_finds_target_on_same_row(self) -> None:
        title = item("搜索商品", 250, 700)
        target = item("去完成", 640, 700)
        other = item("去完成", 640, 900)

        found = TextHandle.find_same_row_text(
            [title, target, other],
            IMAGE.shape,
            anchor_matcher=lambda value: "搜索商品" in value.normalized_text,
            target_texts="去完成",
            target_region=RelativeRegion(left=0.55),
        )

        self.assertIs(found, target)


class TextWaitingTest(unittest.TestCase):
    def test_wait_for_text_returns_center(self) -> None:
        handle = TextOperationHandle([snapshot(item("立即领取", 320, 640))])
        self.assertEqual(handle.wait_for_text("立即领取"), (320, 640))

    def test_waits_until_all_texts_appear_in_same_scan(self) -> None:
        handle = TextOperationHandle(
            [
                snapshot(item("做任务赚肥料", 360, 345)),
                snapshot(
                    item("做任务赚肥料", 360, 345),
                    item("肥料明细", 81, 345),
                ),
            ]
        )
        self.assertEqual(
            handle.wait_for_all_text(
                ["做任务赚肥料", "肥料明细"], timeout=1000
            ),
            [(360, 345), (81, 345)],
        )

    def test_duplicate_targets_require_distinct_ocr_items(self) -> None:
        handle = TextOperationHandle(
            [snapshot(item("去完成", 620, 500), item("去完成", 620, 700))]
        )
        self.assertEqual(
            handle.wait_for_all_text(["去完成", "去完成"]),
            [(620, 500), (620, 700)],
        )

    def test_waits_for_any_text_in_input_priority_order(self) -> None:
        handle = TextOperationHandle(
            [snapshot(item("施肥", 360, 1100), item("逛一逛", 360, 800))]
        )
        self.assertEqual(
            handle.wait_for_any_text(["逛一逛", "施肥"]),
            ("逛一逛", (360, 800)),
        )

    def test_waits_for_text_to_disappear(self) -> None:
        handle = TextOperationHandle(
            [snapshot(item("加载中", 360, 800)), snapshot(item("完成", 360, 800))]
        )
        result = handle.wait_for_text_gone("加载中", timeout=1000)
        self.assertEqual(result.texts, ("完成",))

    def test_waits_for_stable_text_position(self) -> None:
        stable = item("集肥料", 540, 1200)
        handle = TextOperationHandle(
            [
                snapshot(item("集肥料", 500, 1150)),
                snapshot(stable),
                snapshot(item("集肥料", 544, 1203)),
            ]
        )
        found = handle.wait_for_stable_text(
            "集肥料",
            stable_scans=2,
            position_tolerance=8,
            timeout=1000,
            interval=1,
        )
        self.assertEqual(found.center, (544, 1203))

    def test_waits_for_same_stable_screen_signature(self) -> None:
        handle = TextOperationHandle(
            [
                snapshot(item("任务 A", 100, 100)),
                snapshot(item("任务 B", 100, 100)),
                snapshot(item("任务 B", 100, 100)),
            ]
        )
        result = handle.wait_for_stable_screen(
            lambda current: bool(current.items),
            signature=lambda current: TextHandle.screen_signature(current.items),
            stable_scans=2,
            timeout=1000,
            interval=1,
        )
        self.assertEqual(result.texts, ("任务 B",))


class TextClickTest(unittest.TestCase):
    def test_click_text_waits_and_clicks_center(self) -> None:
        handle = TextOperationHandle([snapshot(item("集肥料", 539, 1205))])
        point = handle.click_text("集肥料")
        self.assertEqual(point, (539, 1205))
        self.assertEqual(handle.adb.taps, [(539, 1205)])

    def test_click_text_can_scan_current_screen_once(self) -> None:
        handle = TextOperationHandle([snapshot(item("去完成", 614, 591))])
        point = handle.click_text("去完成", wait=False)
        self.assertEqual(point, (614, 591))

    def test_tap_and_wait_never_repeats_click_while_waiting(self) -> None:
        handle = TextOperationHandle(
            [snapshot(item("加载中", 360, 800)), snapshot(item("目标页", 360, 800))]
        )
        result = handle.tap_and_wait(
            (100, 200),
            lambda current: current if TextHandle.has_text(current.items, "目标页") else None,
            timeout=1000,
            interval=1,
        )
        self.assertEqual(result.texts, ("目标页",))
        self.assertEqual(handle.adb.taps, [(100, 200)])

    def test_click_text_and_wait_combines_both_operations(self) -> None:
        handle = TextOperationHandle(
            [snapshot(item("打开", 100, 200)), snapshot(item("目标页", 360, 800))]
        )
        result = handle.click_text_and_wait(
            "打开",
            lambda current: current if TextHandle.has_text(current.items, "目标页") else None,
            timeout=1000,
            interval=1,
        )
        self.assertEqual(result.texts, ("目标页",))
        self.assertEqual(handle.adb.taps, [(100, 200)])
