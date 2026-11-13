package com.babanongchang.android

import android.app.UiAutomation
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.After
import org.junit.Before
import org.junit.Test

class ScreenWakeLockTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var service: FarmAccessibilityService
    private var originalServices: String? = null
    private var originalEnabled = 0

    @Before fun connect() {
        val automation = instrumentation.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
        val resolver = instrumentation.targetContext.contentResolver
        originalServices = android.provider.Settings.Secure.getString(resolver, "enabled_accessibility_services")
        originalEnabled = android.provider.Settings.Secure.getInt(resolver, "accessibility_enabled", 0)
        automation.adoptShellPermissionIdentity("android.permission.WRITE_SECURE_SETTINGS")
        val component = "com.babanongchang.android/.FarmAccessibilityService"
        val others = originalServices.orEmpty().split(':').filter { it.isNotBlank() && it != component }
        android.provider.Settings.Secure.putString(resolver, "enabled_accessibility_services", others.joinToString(":"))
        val disconnectDeadline = android.os.SystemClock.elapsedRealtime() + 3000
        var disconnected = false
        while (!disconnected && android.os.SystemClock.elapsedRealtime() < disconnectDeadline) {
            instrumentation.runOnMainSync { disconnected = FarmAccessibilityService.connected == null }
            if (!disconnected) Thread.sleep(50)
        }
        check(disconnected) { "Previous accessibility service did not disconnect" }
        android.provider.Settings.Secure.putString(resolver, "enabled_accessibility_services", (others + component).joinToString(":"))
        android.provider.Settings.Secure.putInt(resolver, "accessibility_enabled", 1)
        val deadline = android.os.SystemClock.elapsedRealtime() + 3000
        while (FarmAccessibilityService.connected == null && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(50)
        service = checkNotNull(FarmAccessibilityService.connected) { "Enable the service on the test emulator first" }
    }

    @After fun restoreServiceSettings() {
        if (::service.isInitialized) instrumentation.runOnMainSync {
            service.keepTaskScreenOn(false)
            service.hideControls()
        }
        val resolver = instrumentation.targetContext.contentResolver
        android.provider.Settings.Secure.putString(resolver, "enabled_accessibility_services", originalServices)
        android.provider.Settings.Secure.putInt(resolver, "accessibility_enabled", originalEnabled)
        instrumentation.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).dropShellPermissionIdentity()
    }

    private fun wake() = FarmAccessibilityService::class.java.getDeclaredField("screenWakeLock").apply {
        isAccessible = true
    }.get(service) as? android.os.PowerManager.WakeLock

    @Test fun singleTaskReleasesScreenOnPauseAndFinish() {
        instrumentation.runOnMainSync {
            assertFalse(wake()?.isHeld == true)
            service.show(RunView(running = true, overlayVisible = false))
            assertTrue(checkNotNull(wake()).isHeld)
            service.hideControls()
            assertTrue("Hiding controls must not release the task's screen lock", checkNotNull(wake()).isHeld)
            service.show(RunView(paused = true))
            assertFalse(checkNotNull(wake()).isHeld)
            service.show(RunView(running = true, overlayVisible = false))
            assertTrue(checkNotNull(wake()).isHeld)
            service.show(RunView())
            assertFalse(checkNotNull(wake()).isHeld)
            service.keepTaskScreenOn(false)
            assertFalse("Repeated cleanup must be safe", checkNotNull(wake()).isHeld)
        }
    }

    @Test fun cliPauseAndEndReleaseScreenBeforeWorkerExits() {
        instrumentation.runOnMainSync {
            val busy = CliAutomationRun::class.java.getDeclaredField("busy").apply { isAccessible = true }
            try {
                busy.setBoolean(service.cliRun, true)
                service.keepTaskScreenOn(true)
                service.cliRun.pause()
                assertFalse(checkNotNull(wake()).isHeld)
                service.cliRun.resume()
                assertTrue(checkNotNull(wake()).isHeld)
                service.cliRun.end()
                assertTrue("Worker cleanup may still be pending", service.cliRun.busy)
                assertFalse(checkNotNull(wake()).isHeld)
            } finally {
                busy.setBoolean(service.cliRun, false)
            }
        }
    }

    @Test fun finishingHomeReleasesScreen() = checkHomeExit(removeTask = false)

    @Test fun removingAppTaskReleasesScreen() = checkHomeExit(removeTask = true)

    private fun checkHomeExit(removeTask: Boolean) {
        val context = instrumentation.targetContext
        val home = instrumentation.startActivitySync(android.content.Intent(context, MainActivity::class.java)
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        try {
            instrumentation.runOnMainSync {
                service.keepTaskScreenOn(true)
                assertTrue(checkNotNull(wake()).isHeld)
                if (removeTask) home.finishAndRemoveTask() else home.finish()
            }
            val deadline = android.os.SystemClock.elapsedRealtime() + 3000
            var destroyed = false
            while (!destroyed && android.os.SystemClock.elapsedRealtime() < deadline) {
                instrumentation.runOnMainSync { destroyed = home.isDestroyed }
                if (!destroyed) Thread.sleep(50)
            }
            assertTrue("Wait for the actual Activity exit, including its transition", destroyed)
            instrumentation.runOnMainSync { assertFalse(checkNotNull(wake()).isHeld) }
        } finally {
            instrumentation.runOnMainSync { home.finish() }
        }
    }

}
