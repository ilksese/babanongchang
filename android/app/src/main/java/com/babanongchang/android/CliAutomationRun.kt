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
    var message = "选择功能后，进入目标页面，点击小白球手动开始。"
        private set
    @Volatile var activeRecordId: String? = null
        private set
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
        service.hideControls()
        Thread({
            var result = "运行完成；详细结果见日志"
            val history = RunHistory(File(outputDirectory, "runs"))
            var record: RunRecord? = null
            try {
                outputDirectory.mkdirs()
                val index = when (module) {
                    "games" -> 5
                    else -> FarmFeatures.titles.indices.firstOrNull { FarmFeatures.module(it) == module } ?: 0
                }
                record = history.create(FarmFeatures.titles[index], module, options)
                activeRecordId = record.id
                File(outputDirectory, "cli.log").writeText("")
                gate.checkpoint()
                val bridge = CliAccessibilityBridge(service, gate) { text ->
                    history.append(checkNotNull(record).id, text)
                    File(outputDirectory, "cli.log").appendText(text)
                }
                CliPython.get(service).getModule("babanongchang.android")
                    .callAttr("run", bridge, module, options, outputDirectory.absolutePath, taobaoConfidence)
            } catch (error: Exception) {
                result = "已停止：${error.message ?: error.javaClass.simpleName}"
            } finally {
                gate.stop()
                runCatching { File(outputDirectory, "cli.log").appendText("\n$result\n") }
                val saved = runCatching { record?.let { history.finish(it.id, result) } }
                saved.exceptionOrNull()?.let { result += "；运行记录保存失败：${it.message}" }
                main.post {
                    activeRecordId = null
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
