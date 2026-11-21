from typing import Protocol

from babanongchang.automation.browsing import SwipeDevice
from babanongchang.automation.handle import TextDevice


class FarmDevice(TextDevice, SwipeDevice, Protocol):
    def back(self) -> None: ...

    def installed_packages(self) -> set[str]: ...

    def start_activity(self, component: str) -> None: ...
