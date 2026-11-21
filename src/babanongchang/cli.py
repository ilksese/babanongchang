from __future__ import annotations

import subprocess
import sys
from typing import Sequence

from babanongchang.adapters.adb import Adb
from babanongchang.adapters.ocr import DesktopOcr
from babanongchang.arguments import build_parser, farm_options, game_options, parse_arguments
from babanongchang.config import load_project_config
from babanongchang.desktop_runtime import clock_from_environment
from babanongchang.automation.handle import AutomationError
from babanongchang.workflow import run_farm


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parse_arguments(parser, sys.argv[1:] if argv is None else argv)
    if args.module == "app":
        from babanongchang.app import run_app

        run_app()
        return
    clock = clock_from_environment()
    try:
        options = farm_options(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.nlgj:
        from babanongchang.adapters.adb_game import AdbGameDevice
        from babanongchang.nlgj.ocr import ScreenReader
        from babanongchang.nlgj.runner import play

        game = game_options(parser, args)
        try:
            device = AdbGameDevice(args.serial, args.adb, clock=clock)
            play(game, device=device, reader=ScreenReader(), clock=clock,
                 log=lambda text: print(text, flush=True))
        except KeyboardInterrupt:
            print("Stopped by user. No further taps.")
        except (RuntimeError, subprocess.SubprocessError) as exc:
            parser.exit(1, f"Stopped safely: {exc}\n")
        return

    adb: Adb | None = None
    try:
        config = load_project_config()
        adb = Adb(args.serial, clock=clock)
        run_farm(args.module, options, device=adb, ocr=DesktopOcr(), config=config, clock=clock)
    except KeyboardInterrupt:
        print("\n已由用户停止")
    except AutomationError as exc:
        raise SystemExit(f"自动化已安全停止：{exc}") from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        if adb is not None:
            adb.allow_screen_sleep()


if __name__ == "__main__":
    main()
