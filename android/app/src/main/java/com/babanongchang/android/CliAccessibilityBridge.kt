package com.babanongchang.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ComponentName
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Handler
import android.os.Looper
import android.view.Display
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognizer
import org.json.JSONArray
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** All entry points are called on Python workers; Android operations run on the main thread. */
class CliAccessibilityBridge(
    private val service: FarmAccessibilityService,
    private val control: CliRunControl,
    private val recognizer: TextRecognizer,
    private val writeLog: (String) -> Unit,
) {
    private val main = Handler(Looper.getMainLooper())
    private val ioLock = Any()
    private var observedRevision = -1
    private var width = 0
    private var height = 0
    private var lastCapture = -500L

    fun activeMillis() = control.activeMillis()
    fun sleepMillis(duration: Long) = control.sleepMillis(duration)
    fun log(text: String) = writeLog(text)

    private fun <T> onMain(action: ((Result<T>) -> Unit) -> Unit): T {
        control.checkpoint()
        val revision = control.revision
        val latch = CountDownLatch(1)
        var result: Result<T>? = null
        main.post {
            try {
                control.requireFresh(revision)
                check(service.cliUnavailableReason() == null) { service.cliUnavailableReason().orEmpty() }
                action { result = it; latch.countDown() }
            } catch (error: Exception) {
                result = Result.failure(error)
                latch.countDown()
            }
        }
        check(latch.await(30, TimeUnit.SECONDS)) { "Android 操作等待超时，本轮停止" }
        control.checkpoint()
        control.requireFresh(revision)
        return checkNotNull(result).getOrThrow()
    }

    fun foreground(): String = onMain { done ->
        done(runCatching {
            val root = service.rootInActiveWindow ?: error("无法识别前台应用")
            try { root.packageName?.toString() ?: error("无法识别前台应用") }
            finally { root.recycle() }
        })
    }

    fun capture(): ByteArray = synchronized(ioLock) {
        val wait = 500 - (activeMillis() - lastCapture)
        if (wait > 0) sleepMillis(wait)
        val revision = control.revision
        val bytes = onMain<ByteArray> { done ->
            service.takeScreenshot(Display.DEFAULT_DISPLAY, service.mainExecutor,
                object : AccessibilityService.TakeScreenshotCallback {
                    override fun onFailure(errorCode: Int) {
                        done(Result.failure(IllegalStateException("无障碍截图失败：$errorCode")))
                    }
                    override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                        done(runCatching {
                            result.hardwareBuffer.use { buffer ->
                                val hardware = Bitmap.wrapHardwareBuffer(buffer, result.colorSpace)
                                    ?: error("截图为空")
                                try {
                                    val bitmap = hardware.copy(Bitmap.Config.ARGB_8888, false)
                                        ?: error("无法复制截图")
                                    try {
                                        width = bitmap.width
                                        height = bitmap.height
                                        ByteArrayOutputStream().use { output ->
                                            check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output))
                                            output.toByteArray()
                                        }
                                    } finally { bitmap.recycle() }
                                } finally { hardware.recycle() }
                            }
                        })
                    }
                })
        }
        lastCapture = activeMillis()
        observedRevision = revision
        bytes
    }

    fun recognize(png: ByteArray): String = synchronized(ioLock) {
        control.checkpoint()
        val bitmap = android.graphics.BitmapFactory.decodeByteArray(png, 0, png.size)
            ?: error("OCR 图片无效")
        val task = try {
            recognizer.process(InputImage.fromBitmap(bitmap, 0)).addOnCompleteListener { bitmap.recycle() }
        } catch (error: Exception) {
            bitmap.recycle()
            throw error
        }
        run {
            val text = Tasks.await(task, 30, TimeUnit.SECONDS)
            control.checkpoint()
            val lines = JSONArray()
            for (block in text.textBlocks) for (line in block.lines) {
                val box = line.cornerPoints ?: continue
                lines.put(JSONArray().put(line.text).put(JSONArray().apply {
                    box.forEach { put(JSONArray().put(it.x).put(it.y)) }
                }).put(line.confidence.toDouble()))
            }
            lines.toString()
        }
    }

    fun tap(x: Int, y: Int) = gesture(x, y, x, y, 50)
    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, duration: Int) =
        gesture(x1, y1, x2, y2, duration)

    private fun gesture(x1: Int, y1: Int, x2: Int, y2: Int, duration: Int) = synchronized(ioLock) {
        control.checkpoint()
        control.requireFresh(observedRevision)
        require(duration in 1..10000 && x1 in 0 until width && x2 in 0 until width &&
            y1 in 0 until height && y2 in 0 until height) { "手势坐标或时长无效" }
        onMain<Unit> { done ->
            control.requireFresh(observedRevision)
            val path = Path().apply {
                moveTo(x1.toFloat(), y1.toFloat())
                if (x1 != x2 || y1 != y2) lineTo(x2.toFloat(), y2.toFloat())
            }
            val gesture = GestureDescription.Builder().addStroke(
                GestureDescription.StrokeDescription(path, 0, duration.toLong()),
            ).build()
            val accepted = service.dispatchGesture(gesture,
                object : AccessibilityService.GestureResultCallback() {
                    override fun onCompleted(description: GestureDescription) { done(Result.success(Unit)) }
                    override fun onCancelled(description: GestureDescription) {
                        done(Result.failure(IllegalStateException("手势被取消；不自动重试")))
                    }
                }, main)
            if (!accepted) done(Result.failure(IllegalStateException("系统拒绝手势；不自动重试")))
        }
    }

    fun back() = onMain<Unit> { done ->
        control.requireFresh(observedRevision)
        done(runCatching { check(service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)) })
    }

    fun installedPackages(): String = onMain { done ->
        done(Result.success(JSONArray(listOf("com.eg.android.AlipayGphone", "com.taobao.taobao")
            .filter { service.packageManager.getLaunchIntentForPackage(it) != null }).toString()))
    }

    fun launch(packageName: String, activity: String) = onMain<Unit> { done ->
        done(runCatching {
            require(packageName in setOf("com.eg.android.AlipayGphone", "com.taobao.taobao"))
            val intent = if (activity.isEmpty()) {
                service.packageManager.getLaunchIntentForPackage(packageName) ?: error("应用未安装")
            } else Intent(Intent.ACTION_MAIN).apply {
                component = ComponentName(packageName, activity)
                addCategory(Intent.CATEGORY_LAUNCHER)
            }
            service.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
        })
    }
}
