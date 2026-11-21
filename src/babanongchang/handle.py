from __future__ import annotations

import logging
import re
from babanongchang import runtime as time
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar, cast

import numpy as np

from babanongchang.config import PROJECT_CONFIG


def RapidOCR():
    from rapidocr import RapidOCR as Engine

    return Engine()


class AutomationError(RuntimeError):
    pass


class WaitTimeoutError(AutomationError):
    pass


def normalize_text(text: str) -> str:
    """移除 OCR 文案中的全部空白字符。"""
    return re.sub(r"\s+", "", text)


@dataclass(frozen=True)
class OcrText:
    text: str
    score: float
    box: np.ndarray

    @property
    def center(self) -> tuple[int, int]:
        return int(self.box[:, 0].mean()), int(self.box[:, 1].mean())

    @property
    def normalized_text(self) -> str:
        return normalize_text(self.text)


@dataclass(frozen=True)
class ScreenSnapshot:
    image: np.ndarray
    items: tuple[OcrText, ...]

    @property
    def shape(self) -> tuple[int, ...]:
        return self.image.shape

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.items)


@dataclass(frozen=True)
class RelativeRegion:
    left: float = 0
    top: float = 0
    right: float = 1
    bottom: float = 1

    def __post_init__(self) -> None:
        if not (
            0 <= self.left < self.right <= 1
            and 0 <= self.top < self.bottom <= 1
        ):
            raise ValueError("相对区域坐标必须满足 0 <= left < right <= 1 且 0 <= top < bottom <= 1")

    def contains(self, point: tuple[int, int], image_shape: tuple[int, ...]) -> bool:
        height, width = image_shape[:2]
        x, y = point
        return (
            self.left * width < x < self.right * width
            and self.top * height < y < self.bottom * height
        )


class TextDevice(Protocol):
    def screenshot(self) -> np.ndarray: ...

    def tap(self, point: tuple[int, int]) -> None: ...


class OcrResult(Protocol):
    txts: Sequence[str] | None
    boxes: Sequence[Any] | None
    scores: Sequence[float] | None


class OcrEngine(Protocol):
    def __call__(self, image: np.ndarray) -> OcrResult: ...


T = TypeVar("T")
ScreenMatcher = Callable[[ScreenSnapshot], T | None]
ScreenPredicate = Callable[[ScreenSnapshot], bool]


class TextHandle:
    """提供截图 OCR、文案定位、页面等待和安全点击操作。"""

    def __init__(
        self,
        adb: TextDevice,
        *,
        ocr: OcrEngine | None = None,
        min_score: float = 0.75,
    ) -> None:
        if not 0 <= min_score <= 1:
            raise ValueError("OCR 最低置信度必须在 0 到 1 之间")
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        self.adb = adb
        self.ocr = ocr if ocr is not None else getattr(adb, "ocr", None)
        if self.ocr is None:
            self.ocr = cast(OcrEngine, RapidOCR())
        self.min_score = min_score

    def scan(self) -> ScreenSnapshot:
        time.checkpoint()
        image = self.adb.screenshot()
        time.checkpoint()
        result = self.ocr(image)
        time.checkpoint()
        if result.txts is None or result.boxes is None or result.scores is None:
            return ScreenSnapshot(image=image, items=())
        items = tuple(
            OcrText(text=text, score=float(score), box=np.asarray(box))
            for text, score, box in zip(result.txts, result.scores, result.boxes)
            if float(score) >= self.min_score
        )
        return ScreenSnapshot(image=image, items=items)

    @staticmethod
    def find_texts(
        items: Sequence[OcrText],
        target: str,
        *,
        exact: bool = False,
        region: RelativeRegion | None = None,
        image_shape: tuple[int, ...] | None = None,
        order: Literal["confidence", "reading"] = "confidence",
    ) -> list[OcrText]:
        normalized_target = normalize_text(target)
        if not normalized_target:
            raise ValueError("查找文案不能为空")
        if region is not None and image_shape is None:
            raise ValueError("使用区域过滤时必须提供 image_shape")

        matches = []
        for item in items:
            matched = (
                item.normalized_text == normalized_target
                if exact
                else normalized_target in item.normalized_text
            )
            if not matched:
                continue
            if region is not None and not region.contains(item.center, image_shape):
                continue
            matches.append(item)

        if order == "confidence":
            return sorted(matches, key=lambda item: item.score, reverse=True)
        if order == "reading":
            return sorted(matches, key=lambda item: (item.center[1], item.center[0]))
        raise ValueError(f"不支持的文字排序方式：{order}")

    @staticmethod
    def find_text(
        items: Sequence[OcrText],
        target: str,
        exact: bool = False,
        *,
        region: RelativeRegion | None = None,
        image_shape: tuple[int, ...] | None = None,
    ) -> OcrText | None:
        matches = TextHandle.find_texts(
            items,
            target,
            exact=exact,
            region=region,
            image_shape=image_shape,
        )
        return matches[0] if matches else None

    @staticmethod
    def has_text(
        items: Sequence[OcrText], target: str, exact: bool = False
    ) -> bool:
        return TextHandle.find_text(items, target, exact=exact) is not None

    @staticmethod
    def find_same_row_text(
        items: Sequence[OcrText],
        image_shape: tuple[int, ...],
        *,
        anchor_matcher: Callable[[OcrText], bool],
        target_texts: str | Sequence[str],
        target_region: RelativeRegion | None = None,
        target_on_right: bool = True,
        max_vertical_ratio: float = 0.06,
    ) -> OcrText | None:
        if max_vertical_ratio <= 0:
            raise ValueError("同行文字纵向容差必须大于 0")
        targets = [target_texts] if isinstance(target_texts, str) else list(target_texts)
        if not targets or any(not normalize_text(target) for target in targets):
            raise ValueError("目标文案不能为空")

        height = image_shape[0]
        anchors = [item for item in items if anchor_matcher(item)]
        candidates = [
            item
            for item in items
            if any(normalize_text(target) in item.normalized_text for target in targets)
            and (
                target_region is None
                or target_region.contains(item.center, image_shape)
            )
        ]
        pairs = [
            (anchor, candidate)
            for anchor in anchors
            for candidate in candidates
            if (not target_on_right or candidate.center[0] > anchor.center[0])
            and abs(candidate.center[1] - anchor.center[1])
            < max_vertical_ratio * height
        ]
        if not pairs:
            return None
        return max(pairs, key=lambda pair: pair[0].score + pair[1].score)[1]

    @staticmethod
    def screen_signature(
        items: Sequence[OcrText],
        include: Callable[[OcrText], bool] | None = None,
    ) -> tuple[str, ...]:
        return tuple(
            sorted(
                item.normalized_text
                for item in items
                if item.normalized_text and (include is None or include(item))
            )
        )

    def wait_for_screen(
        self,
        matcher: ScreenMatcher[T],
        *,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        interval: int | None = None,
        error: str = "等待目标页面超时",
    ) -> T:
        """持续扫描，直到 matcher 从同一帧中返回非 None 结果。"""
        interval_seconds = self._validate_wait_arguments(timeout, interval)
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            result = matcher(self.scan())
            if result is not None:
                return result
            time.sleep(interval_seconds)
        raise WaitTimeoutError(error)

    def wait_for_stable_screen(
        self,
        predicate: ScreenPredicate,
        *,
        stable_scans: int = 2,
        signature: Callable[[ScreenSnapshot], Hashable] | None = None,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        interval: int | None = None,
        error: str = "等待页面稳定超时",
    ) -> ScreenSnapshot:
        """等待条件连续成立，并可要求连续帧签名一致。"""
        if stable_scans < 1:
            raise ValueError("稳定扫描次数必须大于 0")
        stable_count = 0
        previous_signature: Hashable | None = None

        def match(snapshot: ScreenSnapshot) -> ScreenSnapshot | None:
            nonlocal previous_signature, stable_count
            if not predicate(snapshot):
                previous_signature = None
                stable_count = 0
                return None

            current_signature = signature(snapshot) if signature is not None else None
            if signature is None or current_signature == previous_signature:
                stable_count += 1
            else:
                stable_count = 1
            previous_signature = current_signature
            return snapshot if stable_count >= stable_scans else None

        return self.wait_for_screen(
            match,
            timeout=timeout,
            interval=interval,
            error=error,
        )

    def wait_for_stable_text(
        self,
        text: str,
        *,
        stable_scans: int = 2,
        position_tolerance: int = 8,
        screen_predicate: ScreenPredicate | None = None,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        interval: int | None = None,
        exact: bool = False,
        error: str | None = None,
    ) -> OcrText:
        """等待文字连续出现且中心坐标保持稳定。"""
        if stable_scans < 1:
            raise ValueError("稳定扫描次数必须大于 0")
        if position_tolerance < 0:
            raise ValueError("位置容差不能小于 0")
        previous_center: tuple[int, int] | None = None
        stable_count = 0

        def match(snapshot: ScreenSnapshot) -> OcrText | None:
            nonlocal previous_center, stable_count
            found = self.find_text(snapshot.items, text, exact=exact)
            if found is None or (
                screen_predicate is not None and not screen_predicate(snapshot)
            ):
                previous_center = None
                stable_count = 0
                return None

            center = found.center
            if previous_center is not None and all(
                abs(current - previous) <= position_tolerance
                for current, previous in zip(center, previous_center)
            ):
                stable_count += 1
            else:
                stable_count = 1
            previous_center = center
            return found if stable_count >= stable_scans else None

        return self.wait_for_screen(
            match,
            timeout=timeout,
            interval=interval,
            error=error or f"等待“{text}”稳定出现超时",
        )

    def wait_for_text(
        self,
        text: str | Sequence[str] = "",
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        *,
        exact: bool = False,
        region: RelativeRegion | None = None,
    ) -> tuple[int, int] | list[tuple[int, int]]:
        """等待同一屏出现全部指定文案，并按传入顺序返回中心坐标。"""
        texts = [text] if isinstance(text, str) else list(text)
        if not texts or any(not normalize_text(value) for value in texts):
            raise ValueError("等待文案不能为空")

        def match(snapshot: ScreenSnapshot) -> list[tuple[int, int]] | None:
            selected: list[OcrText] = []
            used_items: set[int] = set()
            for value in texts:
                candidates = self.find_texts(
                    snapshot.items,
                    value,
                    exact=exact,
                    region=region,
                    image_shape=snapshot.shape,
                )
                found = next(
                    (item for item in candidates if id(item) not in used_items),
                    None,
                )
                if found is None:
                    return None
                selected.append(found)
                used_items.add(id(found))
            return [item.center for item in selected]

        description = "、".join(f"“{value}”" for value in texts)
        points = self.wait_for_screen(
            match,
            timeout=timeout,
            error=f"等待{description}超时，已停止以避免误点",
        )
        return points[0] if isinstance(text, str) else points

    def wait_for_all_text(
        self,
        texts: Sequence[str],
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        *,
        exact: bool = False,
        region: RelativeRegion | None = None,
    ) -> list[tuple[int, int]]:
        points = self.wait_for_text(
            texts,
            timeout=timeout,
            exact=exact,
            region=region,
        )
        assert isinstance(points, list)
        return points

    def wait_for_any_text(
        self,
        texts: Sequence[str],
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        *,
        exact: bool = False,
        region: RelativeRegion | None = None,
    ) -> tuple[str, tuple[int, int]]:
        values = list(texts)
        if not values or any(not normalize_text(value) for value in values):
            raise ValueError("等待文案不能为空")

        def match(snapshot: ScreenSnapshot) -> tuple[str, tuple[int, int]] | None:
            for value in values:
                found = self.find_text(
                    snapshot.items,
                    value,
                    exact=exact,
                    region=region,
                    image_shape=snapshot.shape,
                )
                if found is not None:
                    return value, found.center
            return None

        description = "、".join(f"“{value}”" for value in values)
        return self.wait_for_screen(
            match,
            timeout=timeout,
            error=f"等待任一文案 {description} 超时",
        )

    def wait_for_text_gone(
        self,
        text: str,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        *,
        exact: bool = False,
        stable_scans: int = 1,
    ) -> ScreenSnapshot:
        return self.wait_for_stable_screen(
            lambda snapshot: not self.has_text(snapshot.items, text, exact=exact),
            stable_scans=stable_scans,
            timeout=timeout,
            error=f"等待“{text}”消失超时",
        )

    def click_text(
        self,
        text: str = "",
        wait: bool = True,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        *,
        exact: bool = False,
        region: RelativeRegion | None = None,
    ) -> tuple[int, int]:
        """点击指定文案，并返回实际点击坐标。"""
        if wait:
            point = self.wait_for_text(
                text=text,
                timeout=timeout,
                exact=exact,
                region=region,
            )
            assert isinstance(point, tuple)
        else:
            if not normalize_text(text):
                raise ValueError("点击文案不能为空")
            snapshot = self.scan()
            found = self.find_text(
                snapshot.items,
                text,
                exact=exact,
                region=region,
                image_shape=snapshot.shape,
            )
            if found is None:
                raise AutomationError(f"当前屏幕未找到“{text}”，已停止以避免误点")
            point = found.center
        self.adb.tap(point)
        return point

    def tap_and_wait(
        self,
        point: tuple[int, int],
        matcher: ScreenMatcher[T],
        *,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        interval: int | None = None,
        error: str = "点击后未进入目标页面",
    ) -> T:
        """只点击一次，然后等待目标状态；等待期间绝不重复点击。"""
        self.adb.tap(point)
        return self.wait_for_screen(
            matcher,
            timeout=timeout,
            interval=interval,
            error=error,
        )

    def click_text_and_wait(
        self,
        text: str,
        matcher: ScreenMatcher[T],
        *,
        timeout: int = PROJECT_CONFIG.recognition_timeout_ms,
        click_timeout: int | None = None,
        interval: int | None = None,
        exact: bool = False,
        region: RelativeRegion | None = None,
        error: str = "点击文案后未进入目标页面",
    ) -> T:
        point = self.wait_for_text(
            text,
            timeout=timeout if click_timeout is None else click_timeout,
            exact=exact,
            region=region,
        )
        assert isinstance(point, tuple)
        return self.tap_and_wait(
            point,
            matcher,
            timeout=timeout,
            interval=interval,
            error=error,
        )

    @staticmethod
    def _validate_wait_arguments(timeout: int, interval: int | None) -> float:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        resolved_interval = (
            PROJECT_CONFIG.screenshot_interval_ms if interval is None else interval
        )
        if resolved_interval <= 0:
            raise ValueError("interval 必须大于 0")
        return resolved_interval / 1000
