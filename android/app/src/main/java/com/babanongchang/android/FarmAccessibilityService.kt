package com.babanongchang.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.KeyguardManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.view.Display
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
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
    }

    private val handler = Handler(Looper.getMainLooper())
    private val run = ReadOnlyRun(this)
    private val recognizer by lazy {
        TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
    }
    private var overlay: View? = null
    private var alive = false
    private var recognizing = false

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
            text = "开始只读识别"
            setOnClickListener { run.start() }
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
        getSystemService(WindowManager::class.java).addView(layout, params)
        overlay = layout
    }

    private fun removeOverlay() {
        overlay?.let { getSystemService(WindowManager::class.java).removeView(it) }
        overlay = null
    }

    override fun captureAndRecognize(callback: (Result<OcrFrame>) -> Unit) {
        if (recognizing) {
            callback(Result.failure(IllegalStateException("OCR busy")))
            return
        }
        recognizing = true
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
                    callback(Result.failure(PlatformFailure("$reason（错误码$errorCode）")))
                }

                override fun onSuccess(screenshot: ScreenshotResult) {
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
                    if (!alive || !run.view.running) {
                        bitmap.recycle()
                        recognizing = false
                        return
                    }
                    try {
                        recognizer.process(InputImage.fromBitmap(bitmap, 0))
                            .addOnCompleteListener(mainExecutor) { task ->
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

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (run.view.running) unavailableReason()?.let { run.stop(it) }
    }

    override fun onInterrupt() {
        run.stop("无障碍服务中断")
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
