package com.babanongchang.android

import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import java.io.File

class CliAutomationRun(private val service: FarmAccessibilityService) {
    private val main = Handler(Looper.getMainLooper())
    private var control: CliRunControl? = null
    var busy = false
        private set
    var paused = false
        private set
    private var ending = false
    var message = "选择功能、填写参数后，手动进入目标页面，再从浮层开始"
        private set
    private val logBuffer = StringBuilder()
    val logs: String get() = synchronized(logBuffer) { logBuffer.toString() }
    val outputDirectory: File get() = File(service.filesDir, "cli-output")

    fun start(module: String, options: String) {
        if (busy) return
        service.cliUnavailableReason()?.let { message = it; service.showCliControls(); return }
        val gate = CliRunControl(SystemClock::elapsedRealtime)
        control = gate
        busy = true
        paused = false
        ending = false
        message = "正在运行：$module $options"
        synchronized(logBuffer) { logBuffer.clear() }
        service.hideControls()
        Thread({
            var result = "运行完成；详细结果见日志"
            var recognizer: com.google.mlkit.vision.text.TextRecognizer? = null
            var wake: PowerManager.WakeLock? = null
            try {
                val localRecognizer = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
                recognizer = localRecognizer
                val localWake = service.getSystemService(PowerManager::class.java).newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK, "babanongchang:cli",
                )
                wake = localWake
                outputDirectory.mkdirs()
                File(outputDirectory, "cli.log").writeText("")
                localWake.acquire()
                gate.checkpoint()
                val bridge = CliAccessibilityBridge(service, gate, localRecognizer) { text ->
                    synchronized(logBuffer) {
                        logBuffer.append(text)
                        if (logBuffer.length > 20000) logBuffer.delete(0, logBuffer.length - 20000)
                        File(outputDirectory, "cli.log").appendText(text)
                    }
                }
                CliPython.get(service).getModule("babanongchang.android")
                    .callAttr("run", bridge, module, options, outputDirectory.absolutePath)
            } catch (error: Exception) {
                result = "已停止：${error.message ?: error.javaClass.simpleName}"
                synchronized(logBuffer) { logBuffer.append("\n$result\n") }
            } finally {
                gate.stop()
                wake?.let { if (it.isHeld) it.release() }
                recognizer?.close()
                runCatching { File(outputDirectory, "cli.log").appendText("\n$result\n") }
                main.post {
                    busy = false
                    paused = false
                    control = null
                    message = result
                    service.showCliControls()
                }
            }
        }, "cli-automation").start()
    }

    fun pause() {
        if (!busy || paused || ending) return
        control?.pause()
        paused = true
        message = "已暂停；继续时旧页面坐标失效会安全停止。已发出的手势无法撤销。"
        service.showCliControls()
    }

    fun resume() {
        if (!busy || !paused || ending) return
        paused = false
        service.hideControls()
        control?.resume()
    }

    fun end() {
        if (!busy || ending) return
        ending = true
        control?.stop()
        paused = false
        message = "正在结束并等待已发出操作返回；结果未确认时请查看目标应用"
        service.showCliControls()
    }
}
