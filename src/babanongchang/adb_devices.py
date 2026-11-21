"""Side-effect-free ADB device discovery shared by CLI and desktop UI."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Callable, Sequence

from babanongchang.winproc import hidden_subprocess_kwargs


@dataclass(frozen=True)
class AdbDevice:
    serial: str
    state: str
    details: tuple[tuple[str, str], ...] = ()

    @property
    def model(self) -> str | None:
        return dict(self.details).get("model")


def parse_adb_devices(output: str) -> tuple[AdbDevice, ...]:
    devices: list[AdbDevice] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] == "List":
            continue
        details = tuple(
            token.split(":", 1) for token in parts[2:] if ":" in token
        )
        devices.append(AdbDevice(parts[0], parts[1], details))
    return tuple(devices)


def list_adb_devices(
    adb: str = "adb",
    *,
    runner: Callable[[Sequence[str]], str] | None = None,
) -> tuple[AdbDevice, ...]:
    if runner is None:
        def runner(command: Sequence[str]) -> str:
            return subprocess.check_output(command, text=True, timeout=15, **hidden_subprocess_kwargs())
    return parse_adb_devices(runner([adb, "devices", "-l"]))
