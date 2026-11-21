"""Desktop and frozen-executable entry point."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Sequence

DISTRIBUTED_HOME = "BABANONGCHANG_HOME"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def frozen_home() -> Path:
    override = os.environ.get(DISTRIBUTED_HOME, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(sys.executable).resolve().parent


def cli_command(arguments: Sequence[str], executable: str) -> list[str]:
    if is_frozen():
        return [executable, *arguments]
    return [executable, "-m", "babanongchang.cli", *arguments]


def desktop_argv(argv: Sequence[str]) -> list[str]:
    args = list(argv)
    if is_frozen() and not args:
        return ["app"]
    return args


def prepare_frozen_runtime() -> None:
    if not is_frozen():
        return
    os.chdir(frozen_home())
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> None:
    prepare_frozen_runtime()
    from babanongchang.cli import main as cli_main

    cli_main(desktop_argv(sys.argv[1:]))