package com.babanongchang.android.engine

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.io.File

class FarmEngineTest {
    @Test fun parsesFarmOptionsWithoutCallingPython() {
        val request = parseRun("fertilize", "--threshold 700 --max-clicks 2", 0.5)
        val farm = request as RunRequest.Farm
        assertEquals("fertilize", farm.module)
        assertEquals(700, farm.options.threshold)
        assertEquals(2, farm.options.maxClicks)
        assertEquals(0.5, farm.options.taobaoMinScore, 0.0)
    }

    @Test fun rejectsDesktopRelayFlags() {
        assertEquals("APK 操作本机，不支持 --serial 或 --adb",
            runCatching { parseRun("all", "--serial emulator") }.exceptionOrNull()?.message)
    }

    @Test fun stopsFertilizingAtThreshold() {
        val device = ScriptDevice(listOf(
            script(text("肥料800", 0.9, 360, 1100), text("施肥", 0.99, 360, 1200)),
            script(text("肥料500", 0.9, 360, 1100), text("施肥", 0.99, 360, 1200)),
        ))
        val clock = ManualClock()
        val logs = mutableListOf<String>()
        FarmAutomation(device, TextHandle(device, ScriptOcr, clock = clock), threshold = 600, log = { logs += it }).run()
        assertEquals(listOf(360 to 1200), device.taps)
        assertEquals("肥料余额不大于 600，施肥结束", logs.last())
    }

    @Test fun findsTaobaoTaskAlreadyOpen() {
        val items = listOf(text("做任务赚肥料", 0.9, 200, 100), text("肥料明细", 0.9, 500, 100))
        assertEquals(true, isTaobaoFertilizerTasksPage(items))
        assertNull(findAvailableTaobaoTask(items, 1600 to 720))
    }

    private fun text(value: String, score: Double, x: Int, y: Int) =
        OcrText(value, score, listOf(x - 10.0 to y - 10.0, x + 10.0 to y - 10.0, x + 10.0 to y + 10.0, x - 10.0 to y + 10.0))

    private fun script(vararg items: OcrText) = ScriptImage(720, 1600, items.toList())
}

private class ScriptImage(override val width: Int, override val height: Int, val items: List<OcrText>) : ScreenImage

private object ScriptOcr : OcrEngine {
    override fun recognize(image: ScreenImage): OcrRaw {
        val script = image as ScriptImage
        return OcrRaw(script.items.map { it.text }, script.items.map { it.score }, script.items.map { it.box })
    }
}

private class ScriptDevice(frames: List<ScriptImage>) : FarmDevice {
    private val pending = ArrayDeque(frames)
    val taps = mutableListOf<Pair<Int, Int>>()
    private var last = frames.last()
    override fun screenshot(): ScreenImage = pending.removeFirstOrNull()?.also { last = it } ?: last
    override fun tap(point: Pair<Int, Int>) { taps += point }
    override fun swipe(start: Pair<Int, Int>, end: Pair<Int, Int>, durationMs: Int) = Unit
    override fun back() = Unit
    override fun installedPackages() = emptySet<String>()
    override fun startActivity(component: String) = Unit
}

private class ManualClock : Clock {
    private var now = 0.0
    override fun monotonic() = now
    override fun sleep(seconds: Double) { now += seconds }
    override fun checkpoint() = Unit
}
