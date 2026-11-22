from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


LOG_FILE_NAME = "babanongchang.log"
_debug = False


def silent_log(_text: str) -> None:
    return


def configure_library_logging(debug: bool) -> None:
    global _debug
    _debug = debug
    apply_library_logging()


def apply_library_logging() -> None:
    logging.getLogger("RapidOCR").setLevel(logging.WARNING if _debug else logging.CRITICAL)


class DebugLog:
    """Print each line and append it to the run log. Only constructed for --debug."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8")
        self(f"--- {datetime.now().isoformat(timespec='seconds')} ---")

    def __call__(self, text: str) -> None:
        print(text, flush=True)
        self._file.write(text if text.endswith("\n") else f"{text}\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
