package com.babanongchang.android

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class CliRunControlTest {
    @Test fun pausedTimeDoesNotConsumeDeadlineAndOldEvidenceIsRejected() {
        var now = 1000L
        val control = CliRunControl { now }
        val revision = control.revision
        control.pause()
        now += 10000
        control.resume()
        assertEquals(1000L, control.activeMillis())
        try {
            control.requireFresh(revision)
            fail("旧页面坐标不能继续操作")
        } catch (_: IllegalStateException) { }
        control.requireFresh(control.revision)
    }

    @Test fun pauseBlocksWorkerAndStopWakesItWithoutRunningAction() {
        val control = CliRunControl(System::currentTimeMillis)
        control.pause()
        val started = CountDownLatch(1)
        val finished = CountDownLatch(1)
        val result = AtomicReference<String>()
        val worker = Thread {
            started.countDown()
            try {
                control.checkpoint()
                result.set("action")
            } catch (_: IllegalStateException) {
                result.set("stopped")
            } finally { finished.countDown() }
        }
        worker.start()
        assertTrue(started.await(1, TimeUnit.SECONDS))
        assertFalse(finished.await(50, TimeUnit.MILLISECONDS))
        control.stop()
        assertTrue(finished.await(1, TimeUnit.SECONDS))
        worker.join(1000)
        assertEquals("stopped", result.get())
    }

    @Test fun stopInterruptsLongWait() {
        val control = CliRunControl(System::currentTimeMillis)
        val finished = CountDownLatch(1)
        val result = AtomicReference<String>()
        val worker = Thread {
            try { control.sleepMillis(300000); result.set("finished") }
            catch (_: IllegalStateException) { result.set("stopped") }
            finally { finished.countDown() }
        }
        worker.start()
        control.stop()
        assertTrue(finished.await(1, TimeUnit.SECONDS))
        worker.join(1000)
        assertEquals("stopped", result.get())
    }
}
