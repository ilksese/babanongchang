package com.babanongchang.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.view.Display
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import android.view.accessibility.AccessibilityWindowInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions

class FarmAccessibilityService : AccessibilityService(), ReadOnlyPlatform {
    companion object {
        const val ALIPAY_PACKAGE = "com.eg.android.AlipayGphone"
        var connected: FarmAccessibilityService? = null
            private set
        var lastMessage: String? = null
            private set
        var overlayFailure: String? = null
            private set
    }

    private val handler = Handler(Looper.getMainLooper())
    private val run = ReadOnlyRun(this)
    private val recognizer by lazy {
        TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
    }
    private var overlay: View? = null
    private var alive = false
    private var recognizing = false
    private var lastScreenshotMillis = -500L

    override fun onServiceConnected() {
        alive = true
        connected = this
        showControls()
    }

    fun showControls() {
        if (!run.view.running) show(run.view)
    }

    override fun nowMillis() = SystemClock.elapsedRealtime()

    override fun unavailableReason(): String? {
        if (!alive) return "无障碍服务未连接"
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_TAKE_SCREENSHOT == 0) {
            return "系统未提供无障碍截图能力（需要 Android 11+）"
        }
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_PERFORM_GESTURES == 0) {
            return "系统未提供无障碍手势能力"
        }
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_REQUEST_FILTER_KEY_EVENTS == 0 ||
            serviceInfo.flags and AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS == 0
        ) return "系统未提供辅助按键拦截能力，无法安全控制运行"
        val otherKeyFilter = getSystemService(AccessibilityManager::class.java)
            .getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            .any { it.id != serviceInfo.id &&
                it.flags and AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS != 0 }
        if (otherKeyFilter) return "其他无障碍服务正在请求按键拦截，无法保证音量键控制"
        if (!getSystemService(PowerManager::class.java).isInteractive ||
            getSystemService(KeyguardManager::class.java).isKeyguardLocked
        ) return "屏幕已关闭或锁定"
        if (rootInActiveWindow?.packageName?.toString() != ALIPAY_PACKAGE) {
            return "当前不是支付宝前台页面"
        }
        val appWindows = windows.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
        if (appWindows.size != 1) return "存在多个应用窗口或弹窗，无法确认页面"
        return null
    }

    override fun schedule(delayMillis: Long, action: () -> Unit) {
        handler.postDelayed(action, delayMillis)
    }

    override fun show(view: RunView) {
        lastMessage = view.message
        removeOverlay()
        if (!alive || !view.overlayVisible) return
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(12, 8, 12, 8)
            setBackgroundColor(Color.rgb(245, 245, 245))
        }
        layout.addView(TextView(this).apply {
            text = view.message
            setTextColor(Color.BLACK)
            textSize = 13f
            maxLines = 5
        })
        layout.addView(Button(this).apply {
            text = if (view.paused) "继续" else "开始单次施肥验证"
            setOnClickListener { if (view.paused) run.resume() else run.start() }
        })
        if (view.paused) layout.addView(Button(this).apply {
            text = "结束"
            setOnClickListener { run.end() }
        })
        val params = WindowManager.LayoutParams(
            (260 * resources.displayMetrics.density).toInt(),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            y = (48 * resources.displayMetrics.density).toInt()
        }
        try {
            getSystemService(WindowManager::class.java).addView(layout, params)
            overlay = layout
            overlayFailure = null
        } catch (error: RuntimeException) {
            overlay = null
            overlayFailure = "控制浮层不可用：${error.javaClass.simpleName}"
            lastMessage = "${view.message}；$overlayFailure"
        }
    }

    private fun removeOverlay() {
        overlay?.let {
            try {
                getSystemService(WindowManager::class.java).removeView(it)
            } catch (error: RuntimeException) {
                overlayFailure = "控制浮层不可用：${error.javaClass.simpleName}"
            }
        }
        overlay = null
    }

    override fun captureAndRecognize(isCurrent: () -> Boolean, callback: (Result<OcrFrame>) -> Unit) {
        if (!alive || !isCurrent()) return
        if (recognizing) {
            // Drain an old in-flight request without failing or overlapping the resumed run.
            schedule(200) { captureAndRecognize(isCurrent, callback) }
            return
        }
        val waitMillis = 500 - (nowMillis() - lastScreenshotMillis)
        if (waitMillis > 0) {
            schedule(waitMillis) { captureAndRecognize(isCurrent, callback) }
            return
        }
        recognizing = true
        lastScreenshotMillis = nowMillis()
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onFailure(errorCode: Int) {
                    recognizing = false
                    val reason = when (errorCode) {
                        ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS -> "无障碍截图授权不可用"
                        ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> "系统限制截图频率，本轮已停止"
                        ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY -> "当前显示器不支持无障碍截图"
                        ERROR_TAKE_SCREENSHOT_SECURE_WINDOW -> "当前窗口禁止截图"
                        else -> "无障碍截图失败"
                    }
                    if (!alive || !isCurrent()) return
                    callback(Result.failure(PlatformFailure("$reason（错误码$errorCode）")))
                }

                override fun onSuccess(screenshot: ScreenshotResult) {
                    if (!alive || !isCurrent()) {
                        screenshot.hardwareBuffer.close()
                        recognizing = false
                        return
                    }
                    val bitmap = try {
                        screenshot.hardwareBuffer.use { buffer ->
                            val hardware = Bitmap.wrapHardwareBuffer(buffer, screenshot.colorSpace)
                                ?: error("No screenshot bitmap")
                            try {
                                hardware.copy(Bitmap.Config.ARGB_8888, false) ?: error("Empty screenshot")
                            } finally {
                                hardware.recycle()
                            }
                        }
                    } catch (error: Exception) {
                        recognizing = false
                        callback(Result.failure(error))
                        return
                    }
                    if (!alive || !isCurrent()) {
                        bitmap.recycle()
                        recognizing = false
                        return
                    }
                    try {
                        recognizer.process(InputImage.fromBitmap(bitmap, 0))
                            .addOnCompleteListener(mainExecutor) { task ->
                                if (!alive || !isCurrent()) {
                                    bitmap.recycle()
                                    recognizing = false
                                    return@addOnCompleteListener
                                }
                                val result = if (task.isSuccessful) runCatching {
                                    OcrFrame(bitmap.width, bitmap.height,
                                        task.result.textBlocks.flatMap { it.lines }.mapNotNull { line ->
                                            line.boundingBox?.let {
                                                OcrLine(line.text, Bounds(it.left, it.top, it.right, it.bottom))
                                            }
                                        })
                                } else Result.failure(task.exception ?: IllegalStateException("OCR failed"))
                                bitmap.recycle()
                                recognizing = false
                                callback(result)
                            }
                    } catch (error: Exception) {
                        bitmap.recycle()
                        recognizing = false
                        callback(Result.failure(error))
                    }
                }
            })
        } catch (error: Exception) {
            recognizing = false
            callback(Result.failure(error))
        }
    }

    override fun tap(button: Bounds, callback: (Boolean) -> Unit): Boolean {
        if (unavailableReason() != null) return false
        val path = Path().apply {
            moveTo((button.left + button.right) / 2f, (button.top + button.bottom) / 2f)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        return dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription) { callback(true) }
            override fun onCancelled(gestureDescription: GestureDescription) { callback(false) }
        }, handler)
    }

    override fun onKeyEvent(event: KeyEvent): Boolean {
        val key = when (event.keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> VolumeKey.UP
            KeyEvent.KEYCODE_VOLUME_DOWN -> VolumeKey.DOWN
            else -> return false
        }
        if (event.action != KeyEvent.ACTION_DOWN && event.action != KeyEvent.ACTION_UP) return false
        return run.onVolumeKey(key, event.action == KeyEvent.ACTION_DOWN, event.repeatCount)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (run.view.running || run.view.paused) unavailableReason()?.let { run.stop(it) }
    }

    override fun onInterrupt() {
        run.stop("无障碍服务中断")
    }

    override fun onUnbind(intent: Intent?): Boolean {
        alive = false
        connected = null
        run.stop("无障碍服务断开")
        handler.removeCallbacksAndMessages(null)
        removeOverlay()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        alive = false
        connected = null
        run.stop("无障碍服务断开")
        handler.removeCallbacksAndMessages(null)
        removeOverlay()
        recognizer.close()
        super.onDestroy()
    }
}
