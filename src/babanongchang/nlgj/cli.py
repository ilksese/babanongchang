"""挪了个箭的命令参数与运行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from babanongchang.nlgj.options import GameOptions


def add_arguments(parser: argparse.ArgumentParser) -> None:
    defaults = GameOptions()
    group = parser.add_argument_group("挪了个箭参数（games --nlgj）")
    group.add_argument("--adb", default="adb")
    group.add_argument("--levels", type=int, default=defaults.levels, help="Stop after this many wins; 0 = time limit only")
    group.add_argument("--target", type=int,
                        help="Stop after completing this level or higher; overrides --levels and --max-minutes")
    group.add_argument("--max-minutes", type=float, default=defaults.max_minutes)
    group.add_argument("--mode", choices=("safe", "fast"), default=defaults.mode,
                        help="safe: verify every arrow; fast: tap the whole analyzed order every 0.3 s")
    group.add_argument("--delay", type=float, default=defaults.delay, help="Minimum delay after an arrow tap (safe mode)")
    group.add_argument("--idle-timeout", type=float, default=defaults.idle_timeout)
    group.add_argument("--max-restarts", type=int, default=defaults.max_restarts,
                        help="Maximum stamina-consuming restarts; 0 disables restarting")
    group.add_argument("--streak-policy", choices=("coins-or-abandon", "stop"), default=defaults.streak_policy,
                        help="Use existing coins if sufficient; otherwise abandon streak (no top-up)")
    group.add_argument("--no-revive-ads", action="store_false", dest="revive_ads",
                        help="Disable prioritizing video-ad revival over restart")
    group.add_argument("--ad-timeout", type=float, default=defaults.ad_timeout,
                        help="Maximum wait for rewarded-ad entry/return; fixed browsing takes 33 seconds")
    group.add_argument("--board-top", type=float, default=defaults.board_top)
    group.add_argument("--board-bottom", type=float, default=defaults.board_bottom)
    group.add_argument("--output", type=Path, default=defaults.output)
    group.add_argument("--dry-run", action="store_true", help="Inspect the current device without tapping")
    group.add_argument("--screenshot", type=Path, help="Offline recognition; no device actions")
    group.add_argument("--ocr", action="store_true", help="Include OCR and popup action in offline report")
