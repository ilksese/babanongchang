"""Hide console windows created by tools launched from the desktop app."""

from __future__ import annotations

import os
import subprocess


def hidden_subprocess_kwargs(*extra: int) -> dict[str, int]:
    if os.name != "nt":
        return {}
    flags = subprocess.CREATE_NO_WINDOW
    for item in extra:
        flags |= item
    return {"creationflags": flags}
