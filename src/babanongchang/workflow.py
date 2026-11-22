from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from babanongchang.config import ProjectConfig
from babanongchang.farm.alipay.flow import (
    ALIPAY_PACKAGE, AlipayAutomation, FarmAutomation, GoodsAutomation, TaskAutomation,
)
from babanongchang.farm.device import FarmDevice
from babanongchang.farm.taobao.flow import TaobaoAutomation
from babanongchang.automation.handle import OcrEngine, TextHandle
from babanongchang.logs import silent_log
from babanongchang.runtime import Clock, SYSTEM_CLOCK


FARM_MODULES = ("all", "fertilize", "goods", "tasks", "taobao")
MIN_BROWSE_SECONDS = 15


@dataclass(frozen=True)
class FarmOptions:
    threshold: int = 600
    browse_seconds: float = 18
    max_clicks: int | None = None
    taobao_min_score: float = 0.75

    def __post_init__(self) -> None:
        if self.threshold < 0 or self.browse_seconds < MIN_BROWSE_SECONDS:
            raise ValueError("threshold 不能为负数，browse-seconds 不能少于 15 秒")
        if self.max_clicks is not None and self.max_clicks < 1:
            raise ValueError("max-clicks 必须大于 0")
        if not 0 <= self.taobao_min_score <= 1:
            raise ValueError("淘宝 OCR 置信度阈值必须在 0 到 1 之间")


def run_farm(
    module: str, options: FarmOptions, *, device: FarmDevice, ocr: OcrEngine,
    config: ProjectConfig, clock: Clock = SYSTEM_CLOCK, log: Callable[[str], None] = silent_log,
) -> None:
    """运行指定农场功能；调用方管理设备、OCR 和取消时钟的生命周期。"""
    if module not in FARM_MODULES:
        raise ValueError(f"未知农场功能：{module}")

    def screen(min_score: float = 0.75) -> TextHandle:
        return TextHandle(device, ocr=ocr, config=config, clock=clock, min_score=min_score)

    def run_taobao() -> None:
        TaobaoAutomation(device, screen(options.taobao_min_score), log=log).run()

    if module == "taobao":
        run_taobao()
        return
    if module == "fertilize":
        FarmAutomation(device, screen(), options.threshold, options.browse_seconds, log=log).run(
            max_clicks=options.max_clicks,
        )
        return
    if module == "goods":
        GoodsAutomation(device, screen(), options.browse_seconds, log=log).run()
        return
    if module == "tasks":
        TaskAutomation(device, screen(), options.browse_seconds, log=log).run()
        return

    completed: set[str] = set()
    while True:
        installed = device.installed_packages()
        if ALIPAY_PACKAGE in installed and ALIPAY_PACKAGE not in completed:
            AlipayAutomation(
                device, screen(), options.threshold, options.browse_seconds, log=log,
            ).run(max_clicks=options.max_clicks)
            completed.add(ALIPAY_PACKAGE)
        elif TaobaoAutomation.PACKAGE in installed and TaobaoAutomation.PACKAGE not in completed:
            run_taobao()
            completed.add(TaobaoAutomation.PACKAGE)
        else:
            if not completed:
                log("未安装支付宝或淘宝，流程结束")
            else:
                log("所有已安装应用的芭芭农场流程已完成")
            return
