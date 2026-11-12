"""Popup, streak, revive, and rewarded-ad decisions from OCR and X buttons."""

from __future__ import annotations

from dataclasses import dataclass
import re

import cv2
import numpy as np


AD_COUNTDOWN_SECONDS = 30.
AD_REWARD_GRACE_SECONDS = 3.
AD_SCROLL_SECONDS = AD_COUNTDOWN_SECONDS + AD_REWARD_GRACE_SECONDS


def cross_candidates(image: np.ndarray, ad_corners: bool = False) -> list[tuple[float, int, int]]:
    h, w = image.shape[:2]
    targets = []
    for thickness in ((2, 3, 5, 7, 9) if ad_corners else (5, 7, 9)):
        target = np.zeros((32, 32), np.uint8)
        cv2.line(target, (5, 5), (26, 26), 255, thickness)
        cv2.line(target, (5, 26), (26, 5), 255, thickness)
        if ad_corners:
            x, y, tw, th = cv2.boundingRect(target)
            target = cv2.resize(target[y:y + th, x:x + tw], (32, 32))
        targets.append(target)
    candidates = []
    # Cream/white X buttons on colored backgrounds and dark X on light backgrounds.
    masks = [cv2.inRange(image, (145, 180, 200), (255, 255, 255)),
             cv2.inRange(image, (0, 0, 0), (205, 205, 205))]
    for mask in masks:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        for label in range(1, n):
            x, y, width, height, area = map(int, stats[label])
            if not (10 <= width <= 70 and 10 <= height <= 70 and .7 < width / height < 1.4):
                continue
            cx, cy = x + width // 2, y + height // 2
            # Never touch the mini-app exit capsule, settings, or bottom controls.
            inside = .04 * w < cx < .96 * w and .18 * h < cy < .90 * h
            if ad_corners:
                inside = (0 < cx < w and 0 < cy < h and (cx < .18 * w or cx > .82 * w)
                          and (cy < .25 * h or cy > .82 * h))
                if cx > .74 * w and cy < .095 * h:
                    inside = False
            if not inside:
                continue
            shape = np.uint8(labels[y:y + height, x:x + width] == label) * 255
            shape = cv2.resize(shape, (32, 32))
            score = max(float(cv2.matchTemplate(shape, target, cv2.TM_CCOEFF_NORMED)[0, 0])
                        for target in targets)
            if score >= .82 and (.15 if ad_corners else .30) < area / (width * height) < .85:
                candidates.append((score, cx, cy))
    return sorted(candidates, reverse=True)


def streak_action(image: np.ndarray, lines: list[tuple[str, float, int, int]],
                  policy: str = "stop") -> tuple[int, int, str, int, int] | None:
    if policy != "coins-or-abandon":
        return None
    h, w = image.shape[:2]
    text = " ".join(line[0] for line in lines)
    if "\u6062\u590d\u60a8\u7684\u8fde\u80dc" not in text or "\u83b7\u5f97\u798f\u5229" in text:
        return None
    abandon = [(x, y) for word, confidence, x, y in lines
               if word == "\u6b8b\u5fcd\u653e\u5f03" and confidence >= .95
               and .15 * w < x < .5 * w and .4 * h < y < .8 * h]
    balances = [int(word.rstrip("+")) for word, confidence, x, y in lines
                if confidence >= .95 and re.fullmatch(r"\d+\+?", word)
                and .12 * w < x < .4 * w and 0 < y < .13 * h]
    if len(abandon) != 1 or len(balances) != 1:
        return None
    prices = [(int(word), x, y) for word, confidence, x, y in lines
              if confidence >= .95 and re.fullmatch(r"\d+", word)
              and .5 * w < x < .85 * w and abs(y - abandon[0][1]) < 30]
    if len(prices) != 1 or prices[0][0] <= 0:
        return None
    price, x, y = prices[0]
    balance = balances[0]
    if balance >= price:
        return x, y, "restore-streak-coins", balance, price
    return *abandon[0], "abandon-streak-insufficient-coins", balance, price


def revive_action(image: np.ndarray, lines: list[tuple[str, float, int, int]]) -> tuple[int, int, str] | None:
    text = " ".join(line[0] for line in lines)
    if "\u83b7\u5f97\u798f\u5229" in text or "\u6062\u590d\u60a8\u7684\u8fde\u80dc" in text:
        return None
    restart_confirmation = "\u91cd\u65b0\u5f00\u59cb" in text and "\u4f53\u529b" in text
    offer = "\u7ee7\u7eed\u6e38\u620f" in text and any(
        token in text for token in ("\u6062\u590d", "\u5c31\u5dee", "\u590d\u6d3b"))
    if not (restart_confirmation or offer):
        return None
    for word, confidence, x, y in lines:
        if (confidence >= .85 and re.fullmatch(r"[D0O\u53e3\u56de\u25b6\u25b7]*\u7ee7\u7eed", word)
                and .3 * image.shape[1] < x < .7 * image.shape[1]
                and .45 * image.shape[0] < y < .8 * image.shape[0]):
            return x, y, "cancel-restart-for-revive" if restart_confirmation else "revive-watch-ad"
    return None


@dataclass
class AdWait:
    started: float
    entered_at: float | None = None
    scroll_started_at: float | None = None
    return_requested_at: float | None = None

    def confirm_entry(self, lines: list[tuple[str, float, int, int]], height: int, now: float) -> bool:
        if self.entered_at is not None:
            return True
        for text, confidence, _, y in lines:
            corner = y < .22 * height or y > .80 * height
            if confidence >= .85 and corner and re.search(r"\u6d4f\u89c830\u79d2\u5f97\u5956\u52b1", text):
                self.entered_at = now
                return True
        return False

    def start_scrolling(self, now: float) -> None:
        if self.entered_at is None:
            raise RuntimeError("Cannot scroll before the rewarded-ad page is confirmed")
        if self.scroll_started_at is None:
            self.scroll_started_at = now

    def remaining(self, now: float) -> float | None:
        if self.scroll_started_at is None:
            return None
        return max(0., self.scroll_started_at + AD_SCROLL_SECONDS - now)

    def reward_issued(self, lines: list[tuple[str, float, int, int]], height: int) -> bool:
        for text, confidence, _, y in lines:
            corner = y < .22 * height or y > .80 * height
            if confidence >= .85 and corner and re.search(r"\u5956\u52b1\u4e86?\u5df2\u53d1\u653e", text):
                return True
        return False

    def close_action(self, image: np.ndarray, lines: list[tuple[str, float, int, int]],
                     now: float) -> tuple[int, int, str] | None:
        remaining = self.remaining(now)
        if remaining is None or remaining > 0 or not self.reward_issued(lines, image.shape[0]):
            return None
        for text, confidence, x, y in lines:
            if confidence >= .90 and text in ("\u5173\u95ed", "\u5173\u95ed\u5e7f\u544a", "\u8fd4\u56de\u6e38\u620f", "\u8df3\u8fc7\u5e7f\u544a", "\u8df3\u8fc7"):
                return x, y, "close-finished-ad"
        candidates = cross_candidates(image, ad_corners=True)
        if candidates:
            _, x, y = candidates[0]
            return x, y, "close-finished-ad-X"
        return None


def popup_action(image: np.ndarray, lines: list[tuple[str, float, int, int]],
                 allow_next: bool = True, allow_restart: bool = False) -> tuple[int, int, str] | None:
    h = image.shape[0]
    modal_lines = [line for line in lines if .18 * h < line[3] < .84 * h]
    text = " ".join(line[0] for line in modal_lines)
    # Leave purchases, authorizations, installs, and login prompts for the human.
    sensitive = ("\u652f\u4ed8", "\u8d2d\u4e70", "\u6388\u6743", "\u767b\u5f55", "\u5b89\u88c5")
    if any(word in text for word in sensitive):
        return None
    dismiss = {"\u5173\u95ed", "\u6682\u4e0d", "\u4e0d\u7528\u4e86", "\u4ee5\u540e\u518d\u8bf4",
               "\u653e\u5f03\u5956\u52b1", "\u4e0d\u9886\u53d6", "\u7ee7\u7eed\u6e38\u620f", "\u8fd4\u56de\u6e38\u620f"}
    advance = {"\u4e0b\u4e00\u5173", "\u4e0b\u4e00\u5173\u5361", "\u7ee7\u7eed\u6311\u6218"}
    w, h = image.shape[1], image.shape[0]
    # Reward popups can cover the next action. Their close controls are red X
    # marks whose OCR labels are unreliable, so close them before any claim button.
    # Welfare normally appears about 10 seconds after interaction stops, outside
    # an in-progress clear. If it is visible anyway, still close only its X.
    if "\u83b7\u5f97\u798f\u5229" in text or "\u52a9\u529b\u793c\u5305" in text:
        candidates = cross_candidates(image)
        if candidates:
            _, x, y = candidates[0]
            roi = image[max(0, y - 28):y + 29, max(0, x - 28):x + 29]
            red = cv2.inRange(roi, (20, 20, 160), (140, 140, 255))
            if "\u83b7\u5f97\u798f\u5229" in text and np.count_nonzero(red) < 80:
                return None
            reason = "close-welfare" if "\u83b7\u5f97\u798f\u5229" in text else "close-gift"
            return x, y, reason
        return None
    for word, confidence, x, y in lines:
        if confidence < .85 or not .18 * h < y < .90 * h:
            continue
        lower_right = x > .55 * w and y > .70 * h
        if word in dismiss or (allow_next and word in advance and lower_right):
            return x, y, word
        if allow_restart and word == "\u91cd\u6765" and "\u91cd\u65b0\u5f00\u59cb" in text:
            return x, y, "restart"
        if word == "\u514d\u8d39" and "\u6062\u590d\u60a8\u7684\u8fde\u80dc" in text:
            return x, y, "restore-free-streak"
        if word.startswith("\u8df3\u8fc7") and not re.search(r"\d", word):
            return x, y, word
    # A recognized reward/ad/pause modal supplies context for an otherwise unlabeled X.
    modal_words = ("\u798f\u5229", "\u5956\u52b1", "\u9886\u53d6", "\u5e7f\u544a", "\u6682\u505c", "\u63d0\u793a", "\u606d\u559c", "\u7ee7\u7eed\u6e38\u620f")
    if any(word in text for word in modal_words):
        candidates = cross_candidates(image)
        if candidates:
            _, x, y = candidates[0]
            return x, y, "close-X"
    return None
