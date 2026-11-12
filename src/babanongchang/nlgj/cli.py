"""挪了个箭的命令参数与运行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def add_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("挪了个箭参数（games --nlgj）")
    group.add_argument("--adb", default="adb")
    group.add_argument("--levels", type=int, default=3, help="Stop after this many wins; 0 = time limit only")
    group.add_argument("--target", type=int,
                        help="Stop after completing this level or higher; overrides --levels and --max-minutes")
    group.add_argument("--max-minutes", type=float, default=15)
    group.add_argument("--mode", choices=("safe", "fast"), default="safe",
                        help="safe: verify every arrow; fast: tap the whole analyzed order every 0.3 s")
    group.add_argument("--delay", type=float, default=.65, help="Minimum delay after an arrow tap (safe mode)")
    group.add_argument("--idle-timeout", type=float, default=35)
    group.add_argument("--max-restarts", type=int, default=0,
                        help="Maximum stamina-consuming restarts; 0 disables restarting")
    group.add_argument("--streak-policy", choices=("coins-or-abandon", "stop"), default="coins-or-abandon",
                        help="Use existing coins if sufficient; otherwise abandon streak (no top-up)")
    group.add_argument("--no-revive-ads", action="store_false", dest="revive_ads",
                        help="Disable prioritizing video-ad revival over restart")
    group.add_argument("--ad-timeout", type=float, default=180,
                        help="Maximum wait for rewarded-ad entry/return; fixed browsing takes 33 seconds")
    group.add_argument("--board-top", type=float, default=.165)
    group.add_argument("--board-bottom", type=float, default=.83)
    group.add_argument("--output", type=Path, default=Path("artifacts/nlgj"))
    group.add_argument("--dry-run", action="store_true", help="Inspect the current device without tapping")
    group.add_argument("--screenshot", type=Path, help="Offline recognition; no device actions")
    group.add_argument("--ocr", action="store_true", help="Include OCR and popup action in offline report")


def run(parser: argparse.ArgumentParser, args: argparse.Namespace, *, device=None, reader=None) -> None:
    if not (0 <= args.board_top < args.board_bottom <= 1):
        parser.error("Require 0 <= --board-top < --board-bottom <= 1")
    if args.target is not None and args.target < 1:
        parser.error("Require --target >= 1")
    if min(args.levels, args.max_restarts) < 0 or min(args.max_minutes, args.delay, args.idle_timeout, args.ad_timeout) <= 0:
        parser.error("Require nonnegative --levels and positive timing values")
    from babanongchang.nlgj.runner import play

    try:
        play(args, device=device, reader=reader)
    except KeyboardInterrupt:
        print("Stopped by user. No further taps.")
    except (RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Stopped safely: {exc}\n")
