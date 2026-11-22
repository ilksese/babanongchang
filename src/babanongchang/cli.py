from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import Sequence

from babanongchang.adapters.adb import Adb
from babanongchang.adapters.ocr import DesktopOcr
from babanongchang.arguments import build_parser, farm_options, game_options, parse_arguments
from babanongchang.config import load_project_config
from babanongchang.desktop_runtime import clock_from_environment
from babanongchang.automation.handle import AutomationError
from babanongchang.logs import LOG_FILE_NAME, DebugLog, configure_library_logging, silent_log
from babanongchang.workflow import run_farm


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parse_arguments(parser, sys.argv[1:] if argv is None else argv)
    if args.module == "app":
        from babanongchang.app import run_app

        run_app()
        return
    configure_library_logging(args.debug)
    logger = silent_log
    clock = clock_from_environment()
    adb: Adb | None = None
    try:
        if args.debug:
            logger = DebugLog(Path.cwd() / LOG_FILE_NAME)
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
                play(
                    game, device=device, reader=ScreenReader(), clock=clock,
                    log=logger, record_events=args.debug,
                )
            except KeyboardInterrupt:
                _notify(args.debug, logger, "Stopped by user. No further taps.")
            except (RuntimeError, subprocess.SubprocessError) as exc:
                message = f"Stopped safely: {exc}"
                if args.debug:
                    logger(message)
                parser.exit(1, f"{message}\n")
            return

        try:
            config = load_project_config()
            adb = Adb(args.serial, clock=clock)
            run_farm(
                args.module, options, device=adb, ocr=DesktopOcr(), config=config,
                clock=clock, log=logger,
            )
        except KeyboardInterrupt:
            _notify(args.debug, logger, "已由用户停止")
        except AutomationError as exc:
            message = f"自动化已安全停止：{exc}"
            if args.debug:
                logger(message)
            raise SystemExit(message) from exc
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    finally:
        if isinstance(logger, DebugLog):
            logger.close()
        if adb is not None:
            adb.allow_screen_sleep()


def _notify(debug: bool, logger, message: str) -> None:
    if debug:
        logger(message)
    else:
        print(message)


if __name__ == "__main__":
    main()
