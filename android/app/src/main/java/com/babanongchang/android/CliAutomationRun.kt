package com.babanongchang.android

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
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
        val taobaoConfidence = service.getSharedPreferences("cli", android.content.Context.MODE_PRIVATE)
            .getInt("taobao_confidence", 75).coerceIn(0, 100) / 100.0
        try {
            service.keepTaskScreenOn(true)
        } catch (error: RuntimeException) {
            message = "无法保持亮屏：${error.message ?: error.javaClass.simpleName}"
            service.showCliControls()
            return
        }
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
            try {
                outputDirectory.mkdirs()
                File(outputDirectory, "cli.log").writeText("")
                gate.checkpoint()
                val bridge = CliAccessibilityBridge(service, gate) { text ->
                    synchronized(logBuffer) {
                        logBuffer.append(text)
                        if (logBuffer.length > 20000) logBuffer.delete(0, logBuffer.length - 20000)
                        File(outputDirectory, "cli.log").appendText(text)
                    }
                }
                CliPython.get(service).getModule("babanongchang.android")
                    .callAttr("run", bridge, module, options, outputDirectory.absolutePath, taobaoConfidence)
            } catch (error: Exception) {
                result = "已停止：${error.message ?: error.javaClass.simpleName}"
                synchronized(logBuffer) { logBuffer.append("\n$result\n") }
            } finally {
                gate.stop()
                runCatching { File(outputDirectory, "cli.log").appendText("\n$result\n") }
                main.post {
                    busy = false
                    service.keepTaskScreenOn(false)
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
        service.keepTaskScreenOn(false)
        message = "已暂停；继续时旧页面坐标失效会安全停止。已发出的手势无法撤销。"
        service.showCliControls()
    }

    fun resume() {
        if (!busy || !paused || ending) return
        service.keepTaskScreenOn(true)
        paused = false
        service.hideControls()
        control?.resume()
    }

    fun end() {
        if (!busy || ending) return
        ending = true
        service.keepTaskScreenOn(false)
        control?.stop()
        paused = false
        message = "正在结束并等待已发出操作返回；结果未确认时请查看目标应用"
        service.showCliControls()
    }
}
