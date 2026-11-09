package com.babanongchang.android

import org.junit.Assert.*
import org.junit.Test

class ReadOnlyRunTest {
    @Test fun recognizesFarmThroughCompleteReadOnlyRun() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)

        run.start()
        assertFalse(platform.state.overlayVisible)
        platform.advance(200)
        platform.reply(farm())

        assertTrue(platform.state.overlayVisible)
        assertFalse(platform.state.running)
        assertEquals("只读识别完成：农场已确认，肥料余额 1200，施肥按钮已定位；未发起施肥尝试", platform.state.message)
        assertEquals(FarmRecognition(1200, Bounds(300, 900, 420, 960)), platform.state.recognition)
    }

    @Test fun missingPermissionStopsWithoutTakingScreenshot() {
        val platform = FakePlatform().apply { problem = "无障碍截图能力不可用" }
        ReadOnlyRun(platform).start()
        platform.advance(10_000)
        assertEquals(0, platform.screenshots)
        assertTrue(platform.state.overlayVisible)
        assertEquals("已停止：无障碍截图能力不可用；未发起施肥尝试", platform.state.message)
    }

    @Test fun stalledCaptureStopsAtTenSecondsAndIgnoresLateOcr() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(9_999)
        assertTrue(platform.state.running)
        platform.advance(1)
        assertFalse(platform.state.running)
        assertTrue(platform.state.overlayVisible)
        assertEquals("已停止：只读识别超时（10秒）；未发起施肥尝试", platform.state.message)
        platform.reply(farm())
        assertNull(platform.state.recognition)
    }

    @Test fun wrongPageStopsWithoutClaimingRecognition() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines.drop(1)))
        assertNull(platform.state.recognition)
        assertEquals("已停止：无法确认芭芭农场页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun ocrFailureStopsWithSafeReasonInsteadOfLeakingRawText() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.requests.removeAt(0)(Result.failure(IllegalStateException("private OCR content")))
        assertTrue(platform.state.overlayVisible)
        assertEquals("已停止：截图或中文识别失败；未发起施肥尝试", platform.state.message)
    }

    @Test fun incompleteOrAmbiguousFarmEvidenceStopsWithoutCoordinates() {
        val frames = listOf(
            farm().copy(lines = farm().lines.dropLast(1)),
            farm().copy(lines = farm().lines.filterNot { it.text.startsWith("肥料") }),
            farm().copy(lines = farm().lines + OcrLine("肥料：999", Bounds(10, 500, 200, 560))),
            farm().copy(lines = farm().lines.map { if (it.text == "施肥") it.copy(bounds = Bounds(-1, 0, 30, 20)) else it }),
        )
        for (frame in frames) {
            val platform = FakePlatform()
            ReadOnlyRun(platform).start()
            platform.advance(200)
            platform.reply(frame)
            assertNull(platform.state.recognition)
            assertTrue(platform.state.overlayVisible)
            assertEquals("已停止：肥料余额或施肥按钮无法唯一确认；未发起施肥尝试", platform.state.message)
        }
    }

    @Test fun permissionLossDuringOcrOverridesSuccessfulEvidence() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.problem = "当前不是支付宝前台页面"
        platform.reply(farm())
        assertNull(platform.state.recognition)
        assertEquals("已停止：当前不是支付宝前台页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun interruptionStopsAndOldOcrCannotAffectNewRun() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        platform.advance(200)
        val oldReply = platform.requests.removeAt(0)
        run.stop("无障碍服务中断")
        assertEquals("已停止：无障碍服务中断；未发起施肥尝试", platform.state.message)
        run.start()
        oldReply(Result.success(farm()))
        assertTrue(platform.state.running)
        assertNull(platform.state.recognition)
        platform.advance(200)
        platform.reply(farm())
        assertNotNull(platform.state.recognition)
    }

    @Test fun rewardPopupOverridesOtherwiseValidFarmEvidence() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines + OcrLine("恭喜获得", Bounds(10, 400, 300, 450))))
        assertNull(platform.state.recognition)
        assertEquals("已停止：发现弹窗或任务页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun unsupportedScreenshotCapabilityReportsSpecificBlocker() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.requests.removeAt(0)(Result.failure(PlatformFailure("当前显示器不支持无障碍截图（错误码4）")))
        assertEquals("已停止：当前显示器不支持无障碍截图（错误码4）；未发起施肥尝试", platform.state.message)
    }

    @Test fun secondReadOnlyRunReplacesPreviousNecessaryResult() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        run.start()
        platform.advance(200)
        assertEquals(1, platform.screenshots)
        platform.reply(farm())
        assertNotNull(platform.state.recognition)
        run.start()
        assertNull(platform.state.recognition)
        platform.advance(200)
        platform.reply(farm().copy(lines = emptyList()))
        assertNull(platform.state.recognition)
        assertFalse(platform.state.message.contains("1200"))
    }

    @Test fun duplicateFarmTitlesDoNotConfirmThePage() {
        val platform = FakePlatform()
        ReadOnlyRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines + farm().lines.first()))
        assertNull(platform.state.recognition)
        assertEquals("已停止：无法确认芭芭农场页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun volumeUpPausesUntilOverlayContinueAndReconfirmsWithRemainingTime() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        platform.advance(4_000)
        val oldReply = platform.requests.removeAt(0)

        assertTrue(run.onVolumeKey(VolumeKey.UP, true))
        assertTrue(platform.state.paused)
        assertTrue(platform.state.overlayVisible)
        assertFalse(platform.state.running)
        platform.advance(30_000)
        oldReply(Result.success(farm()))
        assertNull(platform.state.recognition)
        assertEquals(1, platform.screenshots)
        run.start()
        assertTrue(platform.state.paused)
        assertTrue(run.onVolumeKey(VolumeKey.UP, true, repeatCount = 5))
        assertTrue(run.onVolumeKey(VolumeKey.UP, false))
        assertTrue(run.onVolumeKey(VolumeKey.UP, true))
        assertTrue(run.onVolumeKey(VolumeKey.UP, false))
        assertTrue(platform.state.paused)

        run.resume()
        oldReply(Result.success(farm()))
        assertTrue(platform.state.running)
        assertNull(platform.state.recognition)
        assertFalse(platform.state.overlayVisible)
        platform.advance(200)
        assertEquals(2, platform.screenshots)
        platform.reply(farm().copy(lines = farm().lines.map {
            if (it.text == "施肥") it.copy(bounds = Bounds(40, 500, 100, 560)) else it
        }))
        assertEquals(FarmRecognition(1200, Bounds(40, 500, 100, 560)), platform.state.recognition)
    }

    @Test fun interruptionWhilePausedDiscardsRunAndCannotResume() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        run.onVolumeKey(VolumeKey.UP, true)
        run.stop("无障碍服务中断")
        run.resume()
        platform.advance(30_000)
        assertFalse(platform.state.paused)
        assertFalse(platform.state.running)
        assertTrue(platform.state.overlayVisible)
        assertEquals(0, platform.screenshots)
        assertEquals("已停止：无障碍服务中断；未发起施肥尝试", platform.state.message)
    }

    @Test fun lateScreenshotCannotStartOcrAfterPauseResumeOrNewRun() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        platform.advance(200)
        val oldCaptureIsCurrent = platform.captureGuards.single()
        assertTrue(oldCaptureIsCurrent())
        run.onVolumeKey(VolumeKey.UP, true)
        assertFalse(oldCaptureIsCurrent())
        run.resume()
        assertFalse(oldCaptureIsCurrent())
        platform.advance(200)
        val resumedCaptureIsCurrent = platform.captureGuards.last()
        assertTrue(resumedCaptureIsCurrent())
        run.end()
        run.start()
        assertFalse(resumedCaptureIsCurrent())
        assertFalse(oldCaptureIsCurrent())
    }

    @Test fun pauseFreezesOnlyPausedTimeAndRepeatedPausesKeepRemainingBudget() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        platform.advance(4_000)
        run.onVolumeKey(VolumeKey.UP, true)
        run.onVolumeKey(VolumeKey.UP, false)
        platform.advance(30_000)
        run.resume()
        platform.advance(3_000)
        run.onVolumeKey(VolumeKey.UP, true)
        run.onVolumeKey(VolumeKey.UP, false)
        platform.advance(30_000)
        run.resume()
        platform.advance(2_999)
        assertTrue(platform.state.running)
        platform.advance(1)
        assertEquals("已停止：只读识别超时（10秒）；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
        assertFalse(platform.state.paused)
    }

    @Test fun endFromVolumeDownRestoresControlsAndRequiresExplicitNewStart() {
        for (paused in listOf(false, true)) {
            val platform = FakePlatform()
            val run = ReadOnlyRun(platform)
            assertFalse(run.onVolumeKey(VolumeKey.DOWN, true))
            assertFalse(run.onVolumeKey(VolumeKey.DOWN, false))
            run.start()
            platform.advance(200)
            val oldReply = platform.requests.removeAt(0)
            if (paused) run.onVolumeKey(VolumeKey.UP, true)
            assertTrue(run.onVolumeKey(VolumeKey.DOWN, true))
            val ended = platform.state
            assertEquals("已结束；未发起施肥尝试", ended.message)
            assertTrue(ended.overlayVisible)
            assertFalse(ended.running)
            assertFalse(ended.paused)
            assertTrue(run.onVolumeKey(VolumeKey.DOWN, true, repeatCount = 8))
            assertTrue(run.onVolumeKey(VolumeKey.DOWN, false))
            assertFalse(run.onVolumeKey(VolumeKey.DOWN, true))
            assertFalse(run.onVolumeKey(VolumeKey.DOWN, false))
            run.resume()
            platform.advance(30_000)
            oldReply(Result.success(farm()))
            assertEquals(ended, platform.state)
            assertEquals(1, platform.screenshots)
            run.start()
            oldReply(Result.success(farm()))
            assertTrue(platform.state.running)
            assertNull(platform.state.recognition)
            platform.advance(200)
            platform.reply(farm())
            assertNotNull(platform.state.recognition)
        }
    }

    @Test fun overlayEndWhilePausedInvalidatesPendingCapture() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        run.onVolumeKey(VolumeKey.UP, true)
        run.end()
        run.resume()
        platform.advance(30_000)
        assertEquals(0, platform.screenshots)
        assertEquals("已结束；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
    }

    @Test fun heldKeysDoNotStartResumeOrStopAnotherRunAndKeepEventStreamsPaired() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        assertFalse(run.onVolumeKey(VolumeKey.UP, true))
        run.start()
        assertFalse(run.onVolumeKey(VolumeKey.UP, true, repeatCount = 4))
        assertFalse(run.onVolumeKey(VolumeKey.UP, false))
        assertTrue(platform.state.running)
        assertTrue(run.onVolumeKey(VolumeKey.DOWN, true))
        run.start()
        assertTrue(run.onVolumeKey(VolumeKey.DOWN, true, repeatCount = 3))
        assertTrue(run.onVolumeKey(VolumeKey.DOWN, false))
        assertTrue(platform.state.running)
        platform.advance(200)
        platform.reply(farm())
        assertFalse(run.onVolumeKey(VolumeKey.UP, true))
        assertFalse(run.onVolumeKey(VolumeKey.UP, false))
        assertFalse(run.onVolumeKey(VolumeKey.DOWN, true))
        assertFalse(run.onVolumeKey(VolumeKey.DOWN, false))
        assertNotNull(platform.state.recognition)
    }

    @Test fun resumeRechecksPlatformBeforeTakingAnotherScreenshot() {
        val platform = FakePlatform()
        val run = ReadOnlyRun(platform)
        run.start()
        run.onVolumeKey(VolumeKey.UP, true)
        platform.problem = "当前不是支付宝前台页面"
        run.resume()
        platform.advance(30_000)
        assertEquals(0, platform.screenshots)
        assertEquals("已停止：当前不是支付宝前台页面；未发起施肥尝试", platform.state.message)
        assertFalse(platform.state.paused)
    }

    private fun farm() = OcrFrame(720, 1280, listOf(
        OcrLine("芭芭农场", Bounds(20, 100, 220, 150)),
        OcrLine("肥料：1200", Bounds(250, 820, 450, 860)),
        OcrLine("施肥", Bounds(300, 900, 420, 960)),
    ))
}

private class FakePlatform : ReadOnlyPlatform {
    var time = 0L
    var problem: String? = null
    var state = RunView()
    var screenshots = 0
    val requests = mutableListOf<(Result<OcrFrame>) -> Unit>()
    val captureGuards = mutableListOf<() -> Boolean>()
    private val jobs = mutableListOf<Pair<Long, () -> Unit>>()
    override fun nowMillis() = time
    override fun unavailableReason() = problem
    override fun show(view: RunView) { state = view }
    override fun schedule(delayMillis: Long, action: () -> Unit) { jobs += time + delayMillis to action }
    override fun captureAndRecognize(isCurrent: () -> Boolean, callback: (Result<OcrFrame>) -> Unit) {
        captureGuards += isCurrent
        screenshots++
        requests += callback
    }
    fun reply(frame: OcrFrame) { requests.removeAt(0)(Result.success(frame)) }
    fun advance(millis: Long) {
        val target = time + millis
        while (true) {
            val next = jobs.minByOrNull { it.first } ?: break
            if (next.first > target) break
            jobs.remove(next)
            time = next.first
            next.second()
        }
        time = target
    }
}
