"""Main play loop: observe, tap, verify, and handle popups and ads."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import re
from babanongchang import runtime as time

import cv2
import numpy as np

from babanongchang.nlgj.device import AdScroller, Device
from babanongchang.nlgj.fast import fast_sequence, tap_sequence
from babanongchang.nlgj.models import Board
from babanongchang.nlgj.ocr import ScreenReader
from babanongchang.nlgj.overlay import dark_board, tap_point
from babanongchang.nlgj.popups import AD_SCROLL_SECONDS, AdWait, popup_action, revive_action, streak_action
from babanongchang.nlgj.recognition import annotate, predict_removal, recognize, report
from babanongchang.nlgj.verification import arrow_has_left, heart_count, heart_lost, white_board_background


def play(args: argparse.Namespace, *, device=None, reader=None) -> None:
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    reader = reader if reader is not None else ScreenReader()
    if args.screenshot:
        image = cv2.imread(str(args.screenshot))
        if image is None:
            raise RuntimeError("Cannot read --screenshot")
        board = recognize(image, args.board_top, args.board_bottom)
        cv2.imwrite(str(out / "annotated.png"), annotate(board))
        data = report(board)
        if args.ocr:
            data["ocr"] = reader.read(board.image)
            data["popup_action"] = popup_action(board.image, data["ocr"])
            data["streak_action"] = streak_action(board.image, data["ocr"], args.streak_policy)
            data["revive_action"] = revive_action(board.image, data["ocr"]) if args.revive_ads else None
        (out / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(json.dumps(data, ensure_ascii=False), flush=True)
        return

    device = device if device is not None else Device(args.serial, args.adb)
    deadline = time.monotonic() + args.max_minutes * 60
    log = (out / "events.jsonl").open("a", buffering=1)

    def event(kind: str, **data: object) -> None:
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": kind, **data}
        line = json.dumps(entry, ensure_ascii=False)
        print(line, flush=True)
        log.write(line + "\n")

    event("start", package=device.package)
    completed = 0
    last_action = time.monotonic()
    last_count = None
    last_hearts = None
    pending = None
    pending_mask = None
    pending_after = None
    previous_mask = None
    pending_since = 0.
    last_level = None
    level_active = False
    won = False
    restarts = 0
    ad_wait = None
    coin_attempted = False
    coin_attempted_at = 0.
    predicted_board = None
    ad_scroller = None
    next_level_ready_at = None
    fast_round_count = None
    fast_no_progress = 0
    try:
        # Finish an in-progress revival ad before honoring the normal run deadline.
        while args.target is not None or time.monotonic() < deadline or ad_wait is not None:
            image = device.screenshot()
            cv2.imwrite(str(out / "latest.png"), image)
            mask = dark_board(image, args.board_top, args.board_bottom)
            stable = previous_mask is not None and np.count_nonzero(mask != previous_mask) <= 2
            previous_mask = mask.copy()
            background_ready = white_board_background(image, args.board_top, args.board_bottom)
            if (ad_wait is None and predicted_board is not None and pending_after is not None
                    and np.array_equal(mask, pending_after) and background_ready):
                # Reuse geometry only when every remaining foreground pixel is unchanged.
                board = replace(predicted_board, image=image)
            elif (ad_wait is None and pending is not None and background_ready
                  and time.monotonic() - pending_since < 5):
                hearts = heart_count(image)
                if heart_lost(last_hearts, hearts, final_tap=last_count == 1):
                    event("stop", reason="Lost a heart; saving screen for diagnosis")
                    break
                time.sleep(.15)
                continue
            elif ad_wait is not None and not (background_ready and heart_count(image)):
                board = Board(image, np.zeros(mask.shape, np.int32), {}, {}, [], reason="Ad")
            else:
                board = recognize(image, args.board_top, args.board_bottom)
            if ad_wait is not None:
                needs_ocr = ad_wait.entered_at is None or ad_wait.return_requested_at is not None
                lines = reader.read(image) if needs_ocr else []
                header_matches = [re.search(r"\u5173\u5361[:\uff1a]?(\d+)", line[0]) for line in lines
                                  if line[3] < .14 * image.shape[0] and line[1] >= .90]
                levels = [int(match[1]) for match in header_matches if match]
                header_level = bool(levels) and (last_level is None or last_level in levels)
                if header_level and heart_count(image) and (board.valid or board.reason == "No arrows"):
                    if ad_scroller is not None:
                        ad_scroller.stop()
                        ad_scroller = None
                    if last_level is None:
                        last_level = levels[0]
                        level_active = True
                    event("revived", level=last_level)
                    ad_wait = None
                    last_count = last_hearts = pending = pending_mask = pending_after = None
                    fast_round_count = None
                    fast_no_progress = 0
                    predicted_board = None
                    previous_mask = None
                    last_action = time.monotonic()
                    continue
                now = time.monotonic()
                if now - ad_wait.started > args.ad_timeout:
                    event("stop", reason="Rewarded-ad entry/return not confirmed before timeout",
                          visible_text=" ".join(line[0] for line in lines))
                    break
                if ad_wait.return_requested_at is not None:
                    event("ad-return-wait", seconds=round(now - ad_wait.return_requested_at, 1))
                    time.sleep(1.)
                    continue
                if not ad_wait.confirm_entry(lines, image.shape[0], now):
                    event("ad-wait-entry", visible_text=" ".join(line[0] for line in lines))
                    time.sleep(.5)
                    continue
                ad_scroller = AdScroller(device)
                ad_scroller.start()
                ad_wait.start_scrolling(time.monotonic())
                event("ad-scroll-start", mode="continuous-up-down", seconds=AD_SCROLL_SECONDS)
                time.sleep(ad_wait.remaining(time.monotonic()) or 0.)
                ad_scroller.stop()
                if ad_scroller.error is not None:
                    raise RuntimeError(f"Ad scrolling failed: {ad_scroller.error}")
                event("ad-scroll-stop", swipes=ad_scroller.swipes, reason="fixed-33-seconds-finished")
                ad_scroller = None

                reward_image = device.screenshot()
                cv2.imwrite(str(out / "latest.png"), reward_image)
                reward_lines = reader.read(reward_image)
                reward_text = " ".join(line[0] for line in reward_lines)
                now = time.monotonic()
                if not ad_wait.reward_issued(reward_lines, reward_image.shape[0]):
                    event("stop", reason="Reward not confirmed after fixed 33-second ad browse",
                          visible_text=reward_text)
                    break
                action = ad_wait.close_action(reward_image, reward_lines, now)
                if action is None:
                    event("stop", reason="Reward confirmed but no safe return control found",
                          visible_text=reward_text)
                    break
                x, y, reason = action
                event("ad-close", action=reason, x=x, y=y)
                device.tap(x, y)
                ad_wait.return_requested_at = time.monotonic()
                time.sleep(1.)
                continue
            if board.valid:
                coin_attempted = False
                if not stable and pending is None:
                    time.sleep(.25)
                    continue
                hearts = heart_count(image)
                if last_hearts and hearts and hearts < last_hearts:
                    event("stop", reason="Lost a heart; saving screen for diagnosis")
                    break
                if hearts:
                    last_hearts = hearts
                count = len(board.arrows)
                if not level_active:
                    lines = reader.read(image[:round(image.shape[0] * .14)])
                    for text, _, _, _ in lines:
                        match = re.search(r"\u5173\u5361[:\uff1a]?(\d+)", text)
                        if match:
                            last_level = int(match[1])
                    level_active = True
                    event("level", level=last_level, arrows=count)
                    cv2.imwrite(str(out / f"level-{last_level}-start.png"), image)
                if last_count is not None and count > last_count:
                    event("stop", reason="Unexpected board growth/change; refusing stale actions")
                    break
                if pending is not None:
                    if not arrow_has_left(mask, pending_mask, count, last_count, pending_after):
                        if time.monotonic() - pending_since >= 10:
                            event("stop", reason="Arrow did not leave after tap; no repeated guessing")
                            break
                        time.sleep(.4)
                        continue
                    event("verified", remaining=count)
                    pending = None
                    pending_mask = None
                cv2.imwrite(str(out / "annotated.png"), annotate(board))
                if args.dry_run:
                    (out / "report.json").write_text(json.dumps(report(board), indent=2))
                    event("dry-run", arrows=count, order=board.order)
                    break
                if args.mode == "fast":
                    if fast_round_count is not None:
                        fast_no_progress = fast_no_progress + 1 if count >= fast_round_count else 0
                        if fast_no_progress >= 2:
                            event("stop", reason="Fast mode removed no arrows in two rounds; refusing to guess")
                            break
                    sequence = fast_sequence(board)
                    if not sequence:
                        event("stop", reason="Only arrows covered by an app overlay are free; tap manually")
                        break
                    event("fast-round", remaining=count, taps=len(sequence))

                    def fast_tap(index: int, label: int, x: int, y: int) -> None:
                        arrow = board.arrows[label]
                        event("tap-arrow", mode="fast", index=index, x=x, y=y,
                              direction=[arrow.dx, arrow.dy], confidence=round(arrow.confidence, 3),
                              **({} if (x, y) == (arrow.x, arrow.y) else {"head": [arrow.x, arrow.y]}))

                    tap_sequence(device, sequence, fast_tap)
                    last_count = fast_round_count = count
                    previous_mask = None
                    last_action = time.monotonic()
                    continue
                points = {i: tap_point(board, i) for i, deps in board.blockers.items() if not deps}
                ready = [i for i, point in points.items() if point is not None]
                if not ready:
                    event("stop", reason="Only arrows covered by an app overlay are free; tap manually")
                    break
                # Remove short arrows first to reduce animation time.
                label = min(ready, key=lambda i: np.count_nonzero(board.labels == i))
                arrow = board.arrows[label]
                x, y = points[label]
                event("tap-arrow", remaining=count, x=x, y=y,
                      direction=[arrow.dx, arrow.dy], confidence=round(arrow.confidence, 3),
                      **({} if (x, y) == (arrow.x, arrow.y) else {"head": [arrow.x, arrow.y]}))
                device.tap(x, y)
                last_count = count
                pending = (x, y)
                pending_mask = board.labels == label
                pending_after = mask.copy()
                pending_after[pending_mask] = 0
                predicted_board = predict_removal(board, label)
                pending_since = time.monotonic()
                last_action = time.monotonic()
                time.sleep(args.delay)
                continue

            if args.dry_run:
                event("dry-run", reason=board.reason)
                break
            # A moving arrow can be temporarily split into unrecognizable fragments.
            moving = ("Unrecognized strokes/animation" in board.reason
                      or "touches the board crop" in board.reason)
            if (moving and (pending is not None or fast_round_count is not None)
                    and time.monotonic() - last_action < 5):
                time.sleep(.2)
                continue
            lines = reader.read(image)
            text = " ".join(line[0] for line in lines)
            if args.revive_ads:
                resumed_ad = AdWait(time.monotonic())
                if resumed_ad.confirm_entry(lines, image.shape[0], time.monotonic()):
                    ad_wait = resumed_ad
                    event("ad-entered", resumed=True)
                    continue
            if args.revive_ads:
                action = revive_action(image, lines)
                if action:
                    x, y, reason = action
                    if last_level is None:
                        for word, _, _, y_text in lines:
                            match = re.search(r"\u5173\u5361[:\uff1a]?(\d+)", word)
                            if match and y_text < .14 * image.shape[0]:
                                last_level = int(match[1])
                                level_active = True
                    event("revive", action=reason, x=x, y=y)
                    device.tap(x, y)
                    if reason == "revive-watch-ad":
                        ad_wait = AdWait(time.monotonic())
                    last_action = time.monotonic()
                    time.sleep(1.)
                    continue
            decision = streak_action(image, lines, args.streak_policy)
            if decision:
                if coin_attempted:
                    if time.monotonic() - coin_attempted_at >= 10:
                        event("stop", reason="Streak transaction did not leave dialog; no duplicate spending")
                        break
                    time.sleep(.5)
                    continue
                confirmation = device.screenshot()
                confirmed = streak_action(confirmation, reader.read(confirmation), args.streak_policy)
                if confirmed != decision:
                    event("wait", reason="Streak price/balance/dialog changed during confirmation")
                    time.sleep(.5)
                    continue
                x, y, reason, balance, price = decision
                event("streak", action=reason, balance=balance, cost=price, x=x, y=y)
                device.tap(x, y)
                coin_attempted = True
                coin_attempted_at = last_action = time.monotonic()
                time.sleep(1.)
                continue
            if ("\u6062\u590d\u60a8\u7684\u8fde\u80dc" in text
                    and "\u6b8b\u5fcd\u653e\u5f03" in text and "\u514d\u8d39" not in text
                    and "\u83b7\u5f97\u798f\u5229" not in text):
                event("stop", reason="Streak policy disabled or balance/price not confidently recognized",
                      visible_text=text)
                break
            victory_words = ("\u4e0b\u4e00\u5173", "\u606d\u559c\u901a\u5173", "\u901a\u5173\u6210\u529f", "\u6311\u6218\u6210\u529f", "\u95ef\u5173\u6210\u529f")
            if level_active and not won and any(word in text for word in victory_words):
                completed += 1
                won = True
                event("completed", level=last_level, completed=completed)
                cv2.imwrite(str(out / f"level-{last_level}-win.png"), image)
                if args.target is not None and last_level is not None and last_level >= args.target:
                    event("stop", reason=f"Target reached (completed level {last_level} >= {args.target})")
                    break
                if args.target is None and args.levels and completed >= args.levels:
                    event("stop", reason="Requested number of wins reached")
                    break
            failure_offer = args.revive_ads and "\u7ee7\u7eed\u6e38\u620f" in text and "\u6062\u590d" in text
            action = None if failure_offer else popup_action(
                image, lines, allow_restart=restarts < args.max_restarts)
            advance = ("\u4e0b\u4e00\u5173", "\u4e0b\u4e00\u5173\u5361", "\u7ee7\u7eed\u6311\u6218")
            if "\u83b7\u5f97\u798f\u5229" in text:
                next_level_ready_at = None
                if action and action[2] in advance:
                    action = None
            elif action and action[2] in advance:
                now = time.monotonic()
                if next_level_ready_at is None or now < next_level_ready_at:
                    if next_level_ready_at is None:
                        next_level_ready_at = now + 1.5
                        event("wait-next", seconds=1.5)
                    time.sleep(max(0., next_level_ready_at - time.monotonic()))
                    continue
            if action:
                x, y, reason = action
                event("popup", action=reason, x=x, y=y)
                device.tap(x, y)
                if reason == "restart":
                    restarts += 1
                    event("restart", used=restarts, limit=args.max_restarts)
                    level_active = False
                    won = False
                    last_count = None
                    fast_round_count = None
                    fast_no_progress = 0
                    last_hearts = None
                    pending = None
                    predicted_board = None
                if won and reason in ("\u4e0b\u4e00\u5173", "\u4e0b\u4e00\u5173\u5361", "\u7ee7\u7eed\u6311\u6218"):
                    level_active = False
                    won = False
                    last_count = None
                    fast_round_count = None
                    fast_no_progress = 0
                    last_hearts = None
                    pending = None
                    predicted_board = None
                    next_level_ready_at = None
                last_action = time.monotonic()
                time.sleep(1.)
                continue
            idle_seconds = time.monotonic() - last_action
            if idle_seconds >= args.idle_timeout:
                reason = f"Idle timeout: no safe action for {idle_seconds:.1f}s; {board.reason}"
                event("stop", reason=reason, recognition_reason=board.reason,
                      idle_seconds=round(idle_seconds, 1), timeout_seconds=args.idle_timeout,
                      visible_text=text)
                raise RuntimeError(reason)
            event("wait", reason=board.reason, visible_text=text)
            time.sleep(1.)
        else:
            event("stop", reason="Time limit reached")
    finally:
        if ad_scroller is not None:
            ad_scroller.stop()
        log.close()
