package com.babanongchang.android

import org.junit.Assert.*
import org.junit.Test

class SingleFertilizationRunTest {
    @Test fun oneManualRunAttemptsOnceAndOnlyReducedBalanceConfirmsSuccess() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)

        run.start()
        assertFalse(platform.state.overlayVisible)
        platform.advance(200)
        platform.reply(farm(601))
        assertEquals(listOf(Bounds(300, 900, 420, 960)), platform.taps)
        assertTrue(platform.state.running)
        platform.advance(500)
        platform.reply(farm(501))

        assertTrue(platform.state.overlayVisible)
        assertFalse(platform.state.running)
        assertEquals("施肥成功：肥料余额 601 → 501", platform.state.message)
        platform.advance(20_000)
        assertEquals(1, platform.taps.size)
    }

    @Test fun protectionThresholdNeverDispatchesAt600Or599() {
        for (balance in listOf(600L, 599L)) {
            val platform = FakePlatform()
            SingleFertilizationRun(platform).start()
            platform.advance(200)
            platform.reply(farm(balance))
            assertTrue(platform.taps.isEmpty())
            assertEquals("未执行：肥料余额 $balance 不大于保护阈值 600；未发起施肥尝试", platform.state.message)
            assertTrue(platform.state.overlayVisible)
        }
    }

    @Test fun gestureCompletionDoesNotConfirmAndUnchangedBalanceTimesOutWithoutRetry() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.reply(farm(601))
        platform.gestureReplies.single()(true)
        assertTrue(platform.state.running)
        assertFalse(platform.state.message.contains("施肥成功"))
        platform.advance(500)
        platform.reply(farm(601))
        val captures = platform.screenshots
        platform.advance(499)
        assertEquals(captures, platform.screenshots)
        platform.advance(1)
        platform.reply(farm(700))
        platform.advance(8_999)
        assertTrue(platform.state.running)
        platform.advance(1)
        assertEquals("结果未确认：确认肥料余额减少超时（10秒）；不自动补点", platform.state.message)
        assertTrue(platform.state.overlayVisible)
        platform.reply(farm(501))
        assertFalse(platform.state.message.contains("施肥成功"))
        assertEquals(1, platform.taps.size)
    }

    @Test fun postAttemptPauseFreezesConfirmationBudgetAndResumeOnlyChecksOriginalBalance() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.reply(farm(1200))
        platform.advance(4_000)
        val oldReply = platform.requests.removeAt(0)
        assertTrue(run.onVolumeKey(VolumeKey.UP, true))
        assertTrue(platform.state.message.contains("施肥结果未确认"))
        val captures = platform.screenshots
        platform.advance(30_000)
        oldReply(Result.success(farm(1000)))
        platform.gestureReplies.single()(true)
        assertTrue(platform.state.paused)
        assertEquals(captures, platform.screenshots)
        run.onVolumeKey(VolumeKey.UP, false)
        run.resume()
        oldReply(Result.success(farm(1000)))
        platform.advance(500)
        platform.reply(farm(1200))
        assertTrue(platform.state.running)
        assertEquals(1, platform.taps.size)
        platform.advance(5_499)
        assertTrue(platform.state.running)
        platform.advance(1)
        assertEquals("结果未确认：确认肥料余额减少超时（10秒）；不自动补点", platform.state.message)
        assertEquals(1, platform.taps.size)
    }

    @Test fun endingAfterAttemptCannotBeResumedAndLateCallbacksCannotPolluteNextManualRun() {
        for (paused in listOf(false, true)) {
            val platform = FakePlatform()
            val run = SingleFertilizationRun(platform)
            run.start()
            platform.advance(200)
            platform.reply(farm(1200))
            platform.advance(500)
            val oldReply = platform.requests.removeAt(0)
            val oldGesture = platform.gestureReplies.single()
            if (paused) run.onVolumeKey(VolumeKey.UP, true)
            run.end()
            val ended = platform.state
            assertEquals("已结束，施肥结果未确认", ended.message)
            run.resume()
            oldReply(Result.success(farm(1100)))
            oldGesture(false)
            platform.advance(20_000)
            assertEquals(ended, platform.state)
            assertEquals(1, platform.taps.size)
            run.start()
            oldReply(Result.success(farm(1100)))
            oldGesture(true)
            platform.advance(200)
            platform.reply(farm(601))
            assertTrue(platform.state.running)
            assertEquals(2, platform.taps.size)
            oldGesture(false)
            platform.advance(500)
            platform.reply(farm(501))
            assertEquals("施肥成功：肥料余额 601 → 501", platform.state.message)
            oldGesture(false)
            oldReply(Result.success(farm(1100)))
            assertEquals("施肥成功：肥料余额 601 → 501", platform.state.message)
        }
    }

    @Test fun rejectedDispatchReportsNoAttemptAndLateCallbacksCannotChangeIt() {
        val platform = FakePlatform().apply { acceptsGesture = false }
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.reply(farm())
        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：施肥手势未派发；未发起施肥尝试", platform.state.message)
        val stopped = platform.state
        platform.gestureReplies.single()(false)
        platform.gestureReplies.single()(true)
        run.resume()
        platform.advance(20_000)
        assertEquals(stopped, platform.state)
        assertTrue(platform.taps.isEmpty())
    }

    @Test fun cancelledOrThrowingGestureStopsUnconfirmedWithoutRetry() {
        for (failure in listOf("cancelled", "exception")) {
            val platform = FakePlatform().apply {
                if (failure == "exception") gestureError = IllegalStateException("private platform data")
            }
            val run = SingleFertilizationRun(platform)
            run.start()
            platform.advance(200)
            platform.reply(farm())
            if (failure == "cancelled") platform.gestureReplies.single()(false)
            assertTrue(platform.state.overlayVisible)
            assertEquals("结果未确认：施肥手势未能完成；不自动补点", platform.state.message)
            platform.gestureReplies.single()(true)
            run.resume()
            platform.advance(20_000)
            assertEquals(1, platform.taps.size)
            assertFalse(platform.state.running)
        }
    }

    @Test fun interferenceOverridesReducedBalanceAndPostAttemptFailuresRemainUnconfirmed() {
        for (failure in listOf("popup", "page", "permission", "ocr", "stop")) {
            val platform = FakePlatform()
            val run = SingleFertilizationRun(platform)
            run.start()
            platform.advance(200)
            platform.reply(farm())
            platform.advance(500)
            when (failure) {
                "popup" -> platform.reply(farm(1100).copy(lines = farm(1100).lines + OcrLine("奖励", Bounds(0, 0, 10, 10))))
                "page" -> platform.reply(farm(1100).copy(lines = farm(1100).lines.drop(1)))
                "permission" -> { platform.problem = "屏幕已关闭或锁定"; platform.reply(farm(1100)) }
                "ocr" -> platform.requests.removeAt(0)(Result.failure(IllegalStateException("private OCR")))
                "stop" -> run.stop("无障碍服务中断")
            }
            assertFalse(platform.state.running)
            assertTrue(platform.state.overlayVisible)
            assertTrue(platform.state.message.contains("结果未确认"))
            assertFalse(platform.state.message.contains("未发起施肥尝试"))
            assertFalse(platform.state.message.contains("施肥成功"))
            platform.advance(20_000)
            assertEquals(1, platform.taps.size)
        }
    }

    @Test fun confirmationOnlyNeedsValidFarmAndUniqueReducedBalanceNotAnotherButton() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.reply(farm())
        platform.advance(500)
        platform.reply(farm(1100).copy(lines = farm(1100).lines.dropLast(1)))
        assertEquals("施肥成功：肥料余额 1200 → 1100", platform.state.message)
        assertEquals(1, platform.taps.size)
    }

    @Test fun noOverlappingCaptureAndOldDuplicateReplyCannotConfirmOrScheduleExtraWork() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.reply(farm())
        platform.advance(499)
        assertEquals(1, platform.screenshots)
        platform.advance(1)
        val reply = platform.requests.removeAt(0)
        reply(Result.success(farm()))
        reply(Result.success(farm(1100)))
        assertTrue(platform.state.running)
        platform.advance(500)
        assertEquals(3, platform.screenshots)
        platform.reply(farm(1100))
        assertEquals("施肥成功：肥料余额 1200 → 1100", platform.state.message)
        run.stop("奖励弹窗")
        assertEquals("施肥成功：肥料余额 1200 → 1100", platform.state.message)
        assertEquals(1, platform.taps.size)
    }

    @Test fun permissionLossAfterValidRecognitionBeforeDispatchStillReportsNoAttempt() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        platform.onShow = { view ->
            if (view.running && platform.screenshots == 1) {
                platform.problem = "无障碍手势能力不可用"
            }
        }

        run.start()
        platform.advance(200)
        platform.reply(farm(1200))

        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：无障碍手势能力不可用；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
    }

    @Test fun postAttemptResumePreservesOriginalBaselineAndIgnoresOldGestureFailure() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.reply(farm(1200))
        run.onVolumeKey(VolumeKey.UP, true)
        platform.advance(30_000)
        run.resume()
        platform.gestureReplies.single()(false)
        platform.advance(500)
        platform.reply(farm(1100))
        assertEquals("施肥成功：肥料余额 1200 → 1100", platform.state.message)
        assertEquals(1, platform.taps.size)
    }

    @Test fun missingPermissionStopsWithoutTakingScreenshot() {
        val platform = FakePlatform().apply { problem = "无障碍截图能力不可用" }
        SingleFertilizationRun(platform).start()
        platform.advance(10_000)
        assertEquals(0, platform.screenshots)
        assertTrue(platform.state.overlayVisible)
        assertEquals("已停止：无障碍截图能力不可用；未发起施肥尝试", platform.state.message)
    }

    @Test fun stalledCaptureStopsAtTenSecondsAndIgnoresLateOcr() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(9_999)
        assertTrue(platform.state.running)
        platform.advance(1)
        assertFalse(platform.state.running)
        assertTrue(platform.state.overlayVisible)
        assertEquals("已停止：点击前识别超时（10秒）；未发起施肥尝试", platform.state.message)
        platform.reply(farm())
        assertNull(platform.state.recognition)
    }

    @Test fun environmentLossAtPhaseDeadlineStopsWithSpecificReasonBeforeTimeout() {
        val beforeAttempt = FakePlatform()
        SingleFertilizationRun(beforeAttempt).start()
        beforeAttempt.advance(9_999)
        beforeAttempt.problem = "屏幕已关闭或锁定"
        beforeAttempt.advance(1)
        assertEquals("已停止：屏幕已关闭或锁定；未发起施肥尝试", beforeAttempt.state.message)
        assertTrue(beforeAttempt.taps.isEmpty())

        val afterAttempt = FakePlatform()
        val run = SingleFertilizationRun(afterAttempt)
        run.start()
        afterAttempt.advance(200)
        afterAttempt.reply(farm(1200))
        afterAttempt.advance(9_499)
        afterAttempt.problem = "当前不是支付宝前台页面"
        afterAttempt.advance(501)
        assertEquals("已停止：当前不是支付宝前台页面；施肥结果未确认", afterAttempt.state.message)
        assertEquals(1, afterAttempt.taps.size)
    }

    @Test fun wrongPageStopsWithoutClaimingRecognition() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines.drop(1)))
        assertNull(platform.state.recognition)
        assertEquals("已停止：无法确认芭芭农场页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun ocrFailureStopsWithSafeReasonInsteadOfLeakingRawText() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
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
            farm().copy(lines = farm().lines + farm().lines.last()),
            farm().copy(lines = farm().lines.map { if (it.text.startsWith("肥料")) it.copy(text = "肥料：无法解析") else it }),
            farm().copy(lines = farm().lines.map { if (it.text == "施肥") it.copy(bounds = Bounds(-1, 0, 30, 20)) else it }),
        )
        for (frame in frames) {
            val platform = FakePlatform()
            SingleFertilizationRun(platform).start()
            platform.advance(200)
            platform.reply(frame)
            assertNull(platform.state.recognition)
            assertTrue(platform.state.overlayVisible)
            assertEquals("已停止：肥料余额或施肥按钮无法唯一确认；未发起施肥尝试", platform.state.message)
        }
    }

    @Test fun permissionLossDuringOcrOverridesSuccessfulEvidence() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.problem = "当前不是支付宝前台页面"
        platform.reply(farm())
        assertNull(platform.state.recognition)
        assertEquals("已停止：当前不是支付宝前台页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun interruptionStopsAndOldOcrCannotAffectNewRun() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
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
        assertEquals(1, platform.taps.size)
    }

    @Test fun contentEventAtDispatchBoundaryStopsEvenWhenAccessibleSnapshotIsUnchanged() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.onShow = { view -> if (view.running) run.onPageChanged(1) }
        platform.reply(farm())
        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：识别期间页面发生变化；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
    }

    @Test fun pageChangeAfterRecognitionBeforeDispatchNeverUsesRecognizedCoordinates() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        platform.onShow = { view ->
            if (view.running) platform.page = platform.page!!.copy(windowId = 2)
        }
        platform.reply(farm())
        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：识别期间页面发生变化；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
    }

    @Test fun overlayEventsAndPreCaptureChangesDoNotInvalidateFreshFarmRecognition() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        run.onPageChanged(1)
        platform.advance(200)
        run.onVolumeKey(VolumeKey.UP, true)
        run.resume()
        run.onPageChanged(1)
        assertTrue(platform.state.running)
        platform.advance(200)
        run.onPageChanged(99)
        assertTrue(platform.state.running)
        val oldReply = platform.requests.removeAt(0)
        oldReply(Result.success(farm()))
        platform.reply(farm())
        assertEquals(1, platform.taps.size)
        // The expected post-tap change occurs before the fresh confirmation capture.
        run.onPageChanged(1)
        platform.advance(500)
        run.onPageChanged(99)
        platform.reply(farm(1100))
        assertEquals("施肥成功：肥料余额 1200 → 1100", platform.state.message)
        assertEquals(1, platform.taps.size)
    }

    @Test fun contentEventInvalidatesInFlightOcrEvenWhenNodesAndAppWindowStayTheSame() {
        for (afterAttempt in listOf(false, true)) {
            val platform = FakePlatform()
            val run = SingleFertilizationRun(platform)
            run.start()
            platform.advance(200)
            if (afterAttempt) {
                platform.reply(farm())
                platform.advance(500)
            }
            val oldReply = platform.requests.removeAt(0)
            run.onPageChanged(1)
            val stopped = platform.state
            assertFalse(stopped.running)
            assertTrue(stopped.overlayVisible)
            assertEquals(if (afterAttempt) "已停止：识别期间页面发生变化；施肥结果未确认"
                else "已停止：识别期间页面发生变化；未发起施肥尝试", stopped.message)
            assertFalse(platform.captureGuards.last()())
            oldReply(Result.success(farm(1100)))
            platform.advance(20_000)
            assertEquals(stopped, platform.state)
            assertEquals(if (afterAttempt) 1 else 0, platform.taps.size)
        }
    }

    @Test fun sameWindowContentChangeDuringOcrStopsBeforeOldCoordinatesCanDispatch() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        platform.advance(200)
        val oldReply = platform.requests.removeAt(0)
        platform.page = platform.page!!.copy(nodes = platform.page!!.nodes +
            PageNode("温馨提示", Bounds(100, 400, 400, 450)))
        oldReply(Result.success(farm()))
        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：识别期间页面发生变化；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
        run.resume()
        platform.advance(20_000)
        oldReply(Result.success(farm()))
        assertTrue(platform.taps.isEmpty())
    }

    @Test fun inaccessibleOrDialogSemanticsNeverPermitOcrOnlyFarmTap() {
        val normal = FakePlatform().page!!
        for (page in listOf(null, normal.copy(nodes = emptyList()),
            normal.copy(nodes = normal.nodes + PageNode("", Bounds(0, 0, 720, 1280), className = "android.app.Dialog")),
            normal.copy(nodes = normal.nodes + PageNode("", Bounds(0, 0, 720, 1280), paneTitle = "提示")),
            normal.copy(nodes = normal.nodes + PageNode("继续", Bounds(100, 400, 200, 450), clickable = true)),
            normal.copy(nodes = normal.nodes + PageNode("温馨提示", Bounds(100, 400, 200, 450))))) {
            val platform = FakePlatform().apply { this.page = page }
            SingleFertilizationRun(platform).start()
            platform.advance(200)
            platform.reply(farm())
            assertTrue(platform.taps.isEmpty())
            assertEquals("已停止：无法确认可访问农场页面，或存在弹窗；未发起施肥尝试", platform.state.message)
            assertTrue(platform.state.overlayVisible)
        }
    }

    @Test fun unknownSameWindowPromptOverridesValidFarmWithoutClosingIt() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines + listOf(
            OcrLine("温馨提示", Bounds(100, 400, 400, 450)),
            OcrLine("取消", Bounds(100, 500, 200, 550)),
            OcrLine("确定", Bounds(300, 500, 400, 550)),
        )))
        assertTrue(platform.taps.isEmpty())
        assertEquals("已停止：页面存在未确认内容或弹窗；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
        platform.advance(20_000)
        assertTrue(platform.taps.isEmpty())
    }

    @Test fun rewardPopupOverridesOtherwiseValidFarmEvidence() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines + OcrLine("恭喜获得", Bounds(10, 400, 300, 450))))
        assertNull(platform.state.recognition)
        assertEquals("已停止：发现弹窗或任务页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun unsupportedScreenshotCapabilityReportsSpecificBlocker() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.requests.removeAt(0)(Result.failure(PlatformFailure("当前显示器不支持无障碍截图（错误码4）")))
        assertEquals("已停止：当前显示器不支持无障碍截图（错误码4）；未发起施肥尝试", platform.state.message)
    }

    @Test fun secondManualRunReplacesPreviousNecessaryResult() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        run.start()
        platform.advance(200)
        assertEquals(1, platform.screenshots)
        platform.reply(farm())
        platform.advance(500)
        platform.reply(farm(1100))
        assertTrue(platform.state.message.contains("施肥成功"))
        run.start()
        assertNull(platform.state.recognition)
        platform.advance(200)
        platform.reply(farm().copy(lines = emptyList()))
        assertNull(platform.state.recognition)
        assertFalse(platform.state.message.contains("1200"))
    }

    @Test fun duplicateFarmTitlesDoNotConfirmThePage() {
        val platform = FakePlatform()
        SingleFertilizationRun(platform).start()
        platform.advance(200)
        platform.reply(farm().copy(lines = farm().lines + farm().lines.first()))
        assertNull(platform.state.recognition)
        assertEquals("已停止：无法确认芭芭农场页面；未发起施肥尝试", platform.state.message)
    }

    @Test fun volumeUpPausesUntilOverlayContinueAndReconfirmsWithRemainingTime() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
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
        assertEquals(listOf(Bounds(40, 500, 100, 560)), platform.taps)
        assertTrue(platform.state.running)
    }

    @Test fun interruptionWhilePausedDiscardsRunAndCannotResume() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
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
        val run = SingleFertilizationRun(platform)
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
        val run = SingleFertilizationRun(platform)
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
        assertEquals("已停止：点击前识别超时（10秒）；未发起施肥尝试", platform.state.message)
        assertTrue(platform.state.overlayVisible)
        assertFalse(platform.state.paused)
    }

    @Test fun endFromVolumeDownRestoresControlsAndRequiresExplicitNewStart() {
        for (paused in listOf(false, true)) {
            val platform = FakePlatform()
            val run = SingleFertilizationRun(platform)
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
            assertEquals(1, platform.taps.size)
        }
    }

    @Test fun overlayEndWhilePausedInvalidatesPendingCapture() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
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
        val run = SingleFertilizationRun(platform)
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
        platform.advance(500)
        platform.reply(farm(1100))
        assertFalse(run.onVolumeKey(VolumeKey.UP, true))
        assertFalse(run.onVolumeKey(VolumeKey.UP, false))
        assertFalse(run.onVolumeKey(VolumeKey.DOWN, true))
        assertFalse(run.onVolumeKey(VolumeKey.DOWN, false))
        assertEquals(1, platform.taps.size)
    }

    @Test fun resumeRechecksPlatformBeforeTakingAnotherScreenshot() {
        val platform = FakePlatform()
        val run = SingleFertilizationRun(platform)
        run.start()
        run.onVolumeKey(VolumeKey.UP, true)
        platform.problem = "当前不是支付宝前台页面"
        run.resume()
        platform.advance(30_000)
        assertEquals(0, platform.screenshots)
        assertEquals("已停止：当前不是支付宝前台页面；未发起施肥尝试", platform.state.message)
        assertFalse(platform.state.paused)
    }

    private fun farm(balance: Long = 1200) = OcrFrame(720, 1280, listOf(
        OcrLine("芭芭农场", Bounds(20, 100, 220, 150)),
        OcrLine("肥料：$balance", Bounds(250, 820, 450, 860)),
        OcrLine("施肥", Bounds(300, 900, 420, 960)),
    ))
}

private class FakePlatform : SingleFertilizationPlatform {
    var time = 0L
    var problem: String? = null
    var page: PageEvidence? = PageEvidence(1, listOf(
        PageNode("芭芭农场", Bounds(20, 100, 220, 150)),
        PageNode("肥料", Bounds(250, 820, 450, 860)),
        PageNode("施肥", Bounds(0, 0, 720, 1280), clickable = true),
    ))
    override fun pageEvidence() = page
    var state = RunView()
    var screenshots = 0
    val taps = mutableListOf<Bounds>()
    val gestureReplies = mutableListOf<(Boolean) -> Unit>()
    var acceptsGesture = true
    var gestureError: Exception? = null
    val requests = mutableListOf<(Result<OcrFrame>) -> Unit>()
    val captureGuards = mutableListOf<() -> Boolean>()
    private val jobs = mutableListOf<Pair<Long, () -> Unit>>()
    override fun nowMillis() = time
    override fun unavailableReason() = problem
    var onShow: (RunView) -> Unit = { }
    override fun show(view: RunView) { state = view; onShow(view) }
    override fun schedule(delayMillis: Long, action: () -> Unit) { jobs += time + delayMillis to action }
    override fun captureAndRecognize(isCurrent: () -> Boolean, callback: (Result<OcrFrame>) -> Unit) {
        captureGuards += isCurrent
        screenshots++
        requests += callback
    }
    override fun tap(button: Bounds, callback: (Boolean) -> Unit): Boolean {
        if (acceptsGesture) taps += button
        gestureReplies += callback
        gestureError?.let { throw it }
        return acceptsGesture
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
