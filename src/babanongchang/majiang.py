from __future__ import annotations

import re

import cv2
import numpy as np

from babanongchang.browsing import swipe_browse
from babanongchang.handle import AutomationError, OcrText, ScreenSnapshot, TextHandle


def is_majiang_page(snapshot: ScreenSnapshot) -> bool:
    bottom = "".join(
        item.normalized_text for item in sorted(snapshot.items, key=lambda item: item.center[0])
        if item.center[1] > snapshot.shape[0] * 0.9
    )
    return all(label in bottom for label in ("消除", "洗牌", "翻牌", "磁铁"))


def magnet_button(snapshot: ScreenSnapshot) -> OcrText | None:
    return next((
        item for item in snapshot.items
        if item.normalized_text == "磁铁"
        and item.center[1] > snapshot.shape[0] * 0.9
    ), None)


def magnet_count(snapshot: ScreenSnapshot) -> int | None:
    button = magnet_button(snapshot)
    if button is None:
        return None
    height, width = snapshot.shape[:2]
    numbers = [
        item for item in snapshot.items
        if re.fullmatch(r"\d+", item.normalized_text)
        and 0 < item.center[1] - button.center[1] < height * 0.05
        and abs(item.center[0] - button.center[0]) < width * 0.08
    ]
    return int(numbers[0].normalized_text) if len(numbers) == 1 else None


def remaining_tiles(snapshot: ScreenSnapshot) -> int | None:
    height, width = snapshot.shape[:2]
    for label in snapshot.items:
        if not height * 0.65 < label.center[1] < height * 0.85:
            continue
        match = re.fullmatch(r"剩余数量(\d+)", label.normalized_text)
        if match:
            return int(match[1])
        if label.normalized_text != "剩余数量":
            continue
        for number in snapshot.items:
            if (
                re.fullmatch(r"\d+", number.normalized_text)
                and 0 < number.center[0] - label.center[0] < width * 0.2
                and abs(number.center[1] - label.center[1]) < height * 0.02
            ):
                return int(number.normalized_text)
    return None


def has_won(snapshot: ScreenSnapshot) -> bool:
    return any(
        text == item.normalized_text
        for item in snapshot.items
        for text in ("关卡完成", "通关成功", "挑战成功", "恭喜通关")
    )


def is_reward_ad(snapshot: ScreenSnapshot) -> bool:
    return any(
        item.center[1] < snapshot.shape[0] * 0.2
        and ("秒得奖" in item.normalized_text or "已获得奖励" in item.normalized_text)
        for item in snapshot.items
    )


def has_time_dialog(snapshot: ScreenSnapshot) -> bool:
    return TextHandle.has_text(snapshot.items, "时间到了", exact=True)


def has_idle_prop_dialog(snapshot: ScreenSnapshot) -> bool:
    height = snapshot.shape[0]
    middle = [
        item.normalized_text for item in snapshot.items
        if height * 0.5 < item.center[1] < height * 0.73
    ]
    return is_majiang_page(snapshot) and "使用" in middle and any(
        prop in middle for prop in ("消除", "洗牌", "翻牌", "磁铁")
    )


def idle_dialog_close(snapshot: ScreenSnapshot) -> tuple[int, int]:
    height, width = snapshot.shape[:2]
    # 关闭图标没有 OCR 文案，定位弹窗右上区域的白色圆环，不猜固定坐标。
    mask = cv2.inRange(snapshot.image, (210, 210, 210), (255, 255, 255))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (
            width * 0.65 < x < width * 0.85
            and height * 0.25 < y < height * 0.45
            and width * 0.05 < w < width * 0.1
            and 0.85 < w / h < 1.15
            and 0.65 < cv2.contourArea(contour) / (w * h) < 0.85
        ):
            candidates.append((x + w // 2, y + h // 2))
    if len(candidates) != 1:
        raise AutomationError("识别到闲置道具弹窗，但无法唯一定位关闭圆环")
    return candidates[0]


class MajiangAutomation(TextHandle):
    """免费获取磁铁并连续闯关，直到用户中断或步骤失败。"""

    def scan(self) -> ScreenSnapshot:
        snapshot = super().scan()
        # 原图 OCR 会漏掉“翻牌”的单字，放大该标签区域重识别，保留置信度要求。
        if not is_majiang_page(snapshot):
            height, width = snapshot.shape[:2]
            x, y = int(width * 0.51), int(height * 0.925)
            crop = snapshot.image[y:int(height * 0.97), x:int(width * 0.74)]
            result = self.ocr(cv2.resize(crop, None, fx=3, fy=3))
            if result.txts is not None and result.boxes is not None and result.scores is not None:
                extra = tuple(
                    OcrText(text, float(score), np.asarray(box) / 3 + (x, y))
                    for text, box, score in zip(result.txts, result.boxes, result.scores)
                    if text.strip() == "翻牌" and float(score) >= self.min_score
                )
                if extra:
                    items = tuple(item for item in snapshot.items if not (
                        x < item.center[0] < width * 0.74
                        and y < item.center[1] < height * 0.97
                    ))
                    snapshot = ScreenSnapshot(snapshot.image, (*items, *extra))
        if is_majiang_page(snapshot) and remaining_tiles(snapshot) is None:
            height, width = snapshot.shape[:2]
            x, y = int(width * 0.68), int(height * 0.74)
            crop = snapshot.image[y:int(height * 0.77), x:int(width * 0.94)]
            result = self.ocr(cv2.resize(crop, None, fx=3, fy=3))
            if result.txts is not None and result.boxes is not None and result.scores is not None:
                extra = tuple(
                    OcrText(text, float(score), np.asarray(box) / 3 + (x, y))
                    for text, box, score in zip(result.txts, result.boxes, result.scores)
                    if float(score) >= self.min_score
                )
                snapshot = ScreenSnapshot(snapshot.image, (*snapshot.items, *extra))
        if not is_majiang_page(snapshot) and not has_time_dialog(snapshot):
            # 半透明广告条叠在商品文字上时，只提取其白字，避免 OCR 串行。
            height = snapshot.shape[0]
            y = int(height * 0.047)
            crop = snapshot.image[y:int(height * 0.082)]
            mask = 255 - cv2.inRange(crop, (215, 215, 215), (255, 255, 255))
            result = self.ocr(cv2.resize(cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), None, fx=3, fy=3))
            if result.txts is not None and result.boxes is not None and result.scores is not None:
                extra = tuple(
                    OcrText(text, float(score), np.asarray(box) / 3 + (0, y))
                    for text, box, score in zip(result.txts, result.boxes, result.scores)
                    if float(score) >= self.min_score
                    and ("已获得奖励" in text or "秒得奖" in text or text.strip() == "关闭")
                )
                snapshot = ScreenSnapshot(snapshot.image, (*snapshot.items, *extra))
        return snapshot

    def wait_for_game(self) -> ScreenSnapshot:
        closed_idle_dialog = False

        def ready(snapshot: ScreenSnapshot) -> bool:
            nonlocal closed_idle_dialog
            if has_idle_prop_dialog(snapshot):
                if not closed_idle_dialog:
                    self.adb.tap(idle_dialog_close(snapshot))
                    closed_idle_dialog = True
                    print("已点击闲置道具推荐弹窗的关闭按钮")
                return False
            return is_majiang_page(snapshot) or has_won(snapshot) or has_time_dialog(snapshot)

        return self.wait_for_stable_screen(
            ready,
            stable_scans=2, timeout=20000, interval=500,
            error="未识别到麻将游戏或通关页面，请先手动进入当前关卡",
        )

    def close_reward_ad(self) -> None:
        swipe_browse(self.adb, duration_seconds=30)
        downward = False

        def rewarded(snapshot: ScreenSnapshot) -> ScreenSnapshot | None:
            nonlocal downward
            if any(
                "已获得奖励" in item.normalized_text
                and item.center[1] < snapshot.shape[0] * 0.2
                for item in snapshot.items
            ):
                return snapshot
            if is_reward_ad(snapshot):
                height, width = snapshot.shape[:2]
                upper = (width // 2, int(height * 0.36))
                lower = (width // 2, int(height * 0.74))
                start, end = (upper, lower) if downward else (lower, upper)
                self.adb.swipe(start, end, duration_ms=650)
                downward = not downward
            return None

        snapshot = self.wait_for_screen(
            rewarded,
            timeout=120000, interval=1000,
            error="广告未显示已获得奖励，保留当前页面，不提前关闭",
        )
        close = next((
            item for item in snapshot.items
            if item.normalized_text == "关闭"
            and item.center[0] > snapshot.shape[1] * 0.7
            and item.center[1] < snapshot.shape[0] * 0.2
        ), None)
        if close is None:
            raise AutomationError("广告已领奖，但未找到右上角关闭按钮")
        # 系统返回键会退出游戏，必须使用广告自己的关闭按钮。
        self.adb.tap(close.center)

    def extend_time(self, snapshot: ScreenSnapshot) -> ScreenSnapshot:
        height, width = snapshot.shape[:2]
        buttons = [
            item for item in snapshot.items
            if item.normalized_text == "加时"
            and width * 0.15 < item.center[0] < width * 0.5
            and height * 0.6 < item.center[1] < height * 0.72
        ]
        if len(buttons) != 1:
            raise AutomationError("时间已到，但无法唯一定位左侧免费广告加时按钮")
        print("时间已到，看广告免费加时，不使用金币")
        self.tap_and_wait(
            buttons[0].center,
            lambda snapshot: snapshot if is_reward_ad(snapshot) else None,
            timeout=20000, interval=500,
            error="点击免费加时后未进入奖励广告",
        )
        self.close_reward_ad()
        return self.wait_for_stable_screen(
            lambda snapshot: is_majiang_page(snapshot) and not has_time_dialog(snapshot),
            stable_scans=2, timeout=20000, interval=500,
            error="关闭加时广告后未确认回到游戏，保留当前页面",
        )

    def finish_ad(self) -> ScreenSnapshot:
        self.close_reward_ad()
        confirm = self.wait_for_screen(
            lambda snapshot: self.find_text(snapshot.items, "确定", exact=True)
            if self.has_text(snapshot.items, "恭喜获得") else None,
            timeout=20000, interval=200,
            error="关闭广告后未出现磁铁奖励确认弹窗",
        )
        return self.tap_and_wait(
            confirm.center,
            lambda snapshot: snapshot if (
                is_majiang_page(snapshot)
                and not self.has_text(snapshot.items, "恭喜获得")
                and (magnet_count(snapshot) or 0) > 0
            ) else None,
            timeout=15000, interval=200,
        )

    def acquire_magnet(self, snapshot: ScreenSnapshot) -> ScreenSnapshot:
        button = magnet_button(snapshot)
        if button is None:
            raise AutomationError("未找到底部磁铁按钮")
        dialog = self.tap_and_wait(
            button.center,
            lambda snapshot: snapshot if (
                has_time_dialog(snapshot) or (
                self.has_text(snapshot.items, "消除多组牌")
                and self.has_text(snapshot.items, "免费", exact=True)
                )
            ) else None,
            timeout=15000, interval=200,
            error="磁铁数量为零，但未出现免费获取弹窗",
        )
        if has_time_dialog(dialog):
            return dialog
        free = self.find_text(dialog.items, "免费", exact=True)
        assert free is not None
        self.tap_and_wait(
            free.center,
            lambda snapshot: snapshot if is_reward_ad(snapshot) else None,
            timeout=20000, interval=200,
            error="点击免费后未识别到奖励广告",
        )
        return self.finish_ad()

    def run(self) -> None:
        snapshot = self.scan()
        snapshot = self.finish_ad() if is_reward_ad(snapshot) else self.wait_for_game()
        while True:
            self.complete_level(snapshot)
            print("本关麻将已通关，准备进入下一关")
            self.click_text_and_wait(
                "下一关",
                lambda snapshot: snapshot if (
                    is_majiang_page(snapshot)
                    and not has_won(snapshot)
                    and not self.has_text(snapshot.items, "下一关", exact=True)
                    and (remaining := remaining_tiles(snapshot)) is not None
                    and remaining > 0
                    and magnet_count(snapshot) is not None
                ) else None,
                exact=True, timeout=20000, interval=500,
                error="点击下一关后未确认进入新关卡，已停止",
            )
            snapshot = self.wait_for_shuffle()

    def wait_for_shuffle(self) -> ScreenSnapshot:
        previous: np.ndarray | None = None

        def board_is_still(snapshot: ScreenSnapshot) -> bool:
            nonlocal previous
            if (
                not is_majiang_page(snapshot) or has_won(snapshot)
                or has_time_dialog(snapshot) or has_idle_prop_dialog(snapshot)
                or remaining_tiles(snapshot) is None or magnet_count(snapshot) is None
            ):
                previous = None
                return False
            height = snapshot.shape[0]
            board = cv2.resize(
                snapshot.image[int(height * 0.15):int(height * 0.74), :],
                (180, 240),
            )
            still = previous is not None and float(
                np.mean(cv2.absdiff(board, previous) > 20)
            ) < 0.005
            previous = board
            return still

        print("等待下一关洗牌动画结束")
        return self.wait_for_stable_screen(
            board_is_still, stable_scans=4, timeout=40000, interval=500,
            error="下一关洗牌画面持续未稳定，已停止，未点击磁铁",
        )

    def complete_level(self, snapshot: ScreenSnapshot) -> None:
        while not has_won(snapshot):
            if has_time_dialog(snapshot):
                snapshot = self.extend_time(snapshot)
                continue
            count = magnet_count(snapshot)
            before = remaining_tiles(snapshot)
            if count is None or before is None:
                raise AutomationError("无法确认磁铁数量或剩余牌数，停止以避免误点")
            if before == 0:
                snapshot = self.wait_for_stable_screen(
                    has_won, stable_scans=2, timeout=20000, interval=500,
                    error="剩余牌数为零，但未出现通关弹窗，已停止",
                )
                continue
            if count == 0:
                print(f"剩余 {before} 张牌，开始看广告获取磁铁")
                snapshot = self.acquire_magnet(snapshot)
                if has_time_dialog(snapshot):
                    continue
                count = magnet_count(snapshot)
            button = magnet_button(snapshot)
            if button is None or count is None or count < 1:
                raise AutomationError("领取后未确认磁铁可用")
            print(f"使用磁铁，当前剩余 {before} 张牌")
            snapshot = self.tap_and_wait(
                button.center,
                lambda snapshot: snapshot if has_won(snapshot) or has_time_dialog(snapshot) or (
                    is_majiang_page(snapshot)
                    and magnet_count(snapshot) == count - 1
                    and (remaining := remaining_tiles(snapshot)) is not None
                    and remaining < before
                ) else None,
                timeout=20000, interval=200,
                error="使用磁铁后未确认牌数减少，停止以避免重复点击",
            )
            if has_won(snapshot) or has_time_dialog(snapshot):
                continue
            snapshot = self.wait_for_stable_screen(
                lambda snapshot: has_won(snapshot) or has_time_dialog(snapshot) or (
                    is_majiang_page(snapshot)
                    and magnet_count(snapshot) is not None
                    and (remaining := remaining_tiles(snapshot)) is not None
                    and remaining < before
                ),
                signature=lambda snapshot: (
                    magnet_count(snapshot), remaining_tiles(snapshot), has_won(snapshot)
                ),
                stable_scans=2, timeout=20000, interval=200,
                error="磁铁消除后页面未稳定",
            )
