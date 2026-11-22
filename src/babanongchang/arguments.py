from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import fields

from babanongchang.nlgj.cli import add_arguments
from babanongchang.nlgj.options import GameOptions
from babanongchang.workflow import FARM_MODULES, FarmOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="支付宝/淘宝芭芭农场自动化脚本")
    parser.add_argument(
        "module", nargs="?", choices=(*FARM_MODULES, "games", "app"), default="all",
        help="运行模块：app（桌面界面，不接受其他参数）、all（默认）、fertilize、goods、tasks、taobao 或 games",
    )
    parser.add_argument("--serial", help="ADB 设备序列号；仅连接一台设备时可省略")
    parser.add_argument("--debug", action="store_true", help="打印运行日志，并追加写入当前目录的 babanongchang.log")
    parser.add_argument("--nlgj", action="store_true", help="games 模块：挪了个箭，默认最多通关 3 次或运行 15 分钟")
    add_arguments(parser)
    defaults = FarmOptions()
    parser.add_argument("--threshold", type=int, default=defaults.threshold,
                        help=f"停止施肥的余额阈值（默认：{defaults.threshold}）")
    parser.add_argument("--browse-seconds", type=float, default=defaults.browse_seconds,
                        help=f"浏览奖励页面的往复滑动秒数（默认：{defaults.browse_seconds:g}）")
    parser.add_argument("--max-clicks", type=int, help="最多点击几次施肥；用于小范围测试")
    return parser


def parse_arguments(parser: argparse.ArgumentParser, argv: Sequence[str]) -> argparse.Namespace:
    if "app" in argv and list(argv) != ["app"]:
        parser.error("app 不接受其他参数")
    args = parser.parse_args(argv)
    if (args.module == "games") != args.nlgj:
        raise SystemExit("游戏请使用 games --nlgj")
    return args


def farm_options(args: argparse.Namespace, *, taobao_min_score: float = FarmOptions.taobao_min_score) -> FarmOptions:
    return FarmOptions(args.threshold, args.browse_seconds, args.max_clicks, taobao_min_score)


def game_options(parser: argparse.ArgumentParser, args: argparse.Namespace) -> GameOptions:
    try:
        return GameOptions(**{field.name: getattr(args, field.name) for field in fields(GameOptions)})
    except ValueError as exc:
        parser.error(str(exc))
