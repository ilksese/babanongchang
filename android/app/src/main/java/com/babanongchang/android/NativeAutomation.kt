package com.babanongchang.android

import android.content.Context
import com.babanongchang.android.engine.AutomationError
import com.babanongchang.android.engine.Clock
import com.babanongchang.android.engine.FarmDevice
import com.babanongchang.android.engine.FarmOptions
import com.babanongchang.android.engine.GameOptions
import com.babanongchang.android.engine.RunRequest
import com.babanongchang.android.engine.ScreenImage
import com.babanongchang.android.engine.loadProjectConfig
import com.babanongchang.android.engine.parseRun
import com.babanongchang.android.engine.runFarm
import com.babanongchang.android.vision.ArrowDevice
import com.babanongchang.android.vision.NativeGameReader
import com.babanongchang.android.vision.OpenCvKit
import com.babanongchang.android.vision.RapidOcr
import com.babanongchang.android.vision.normalizeWidth
import com.babanongchang.android.vision.playGame
import com.babanongchang.android.vision.pyRound
import org.json.JSONArray
import org.opencv.core.Mat
import java.io.File
import kotlin.math.roundToLong

object NativeRuntime {
    private var engine: RapidOcr? = null

    fun ocr(context: Context): RapidOcr = synchronized(this) {
        engine ?: RapidOcr(
            OnnxSession(model(context, "Det.onnx").path),
            OnnxSession(model(context, "Cls.onnx").path),
            OnnxSession(model(context, "Rec.onnx").path),
        ).also { engine = it }
    }

    fun recognizeJson(context: Context, png: ByteArray): String = ocr(context).recognizeJson(png)

    private fun model(context: Context, name: String): File {
        val file = File(context.filesDir, "ocr-models/$name")
        if (!file.isFile || file.length() == 0L) {
            file.parentFile?.mkdirs()
            context.assets.open("ocr/$name").use { input -> file.outputStream().use { input.copyTo(it) } }
        }
        return file
    }
}

fun runNative(
    context: Context,
    bridge: CliAccessibilityBridge,
    module: String,
    options: String,
    outputDir: File,
    taobaoMinScore: Double = FarmOptions().taobaoMinScore,
) {
    val request = parseRun(module, options, taobaoMinScore)
    val clock = BridgeClock(bridge)
    val log = { text: String -> bridge.log(text + "\n") }
    try {
        when (request) {
            is RunRequest.Game -> {
                val output = if (request.options.output.path == GameOptions.defaultOutput.path) outputDir
                else if (request.options.output.isAbsolute) request.options.output
                else File(outputDir, request.options.output.path)
                playGame(request.options.copy(output = output), BridgeGameDevice(bridge),
                    NativeGameReader(NativeRuntime.ocr(context)), clock, log)
            }
            is RunRequest.Farm -> {
                outputDir.mkdirs()
                runFarm(request.module, request.options, BridgeFarmDevice(bridge), NativeRuntime.ocr(context),
                    loadProjectConfig(File(outputDir, "babanongchang.toml")), clock, log)
            }
        }
    } catch (error: AutomationError) {
        throw RuntimeException("自动化已安全停止：${error.message}", error)
    }
}

private class BridgeClock(private val bridge: CliAccessibilityBridge) : Clock {
    override fun monotonic() = bridge.activeMillis() / 1000.0
    override fun sleep(seconds: Double) = bridge.sleepMillis((seconds * 1000).roundToLong())
    override fun checkpoint() = bridge.checkpoint()
}

private class BridgeFarmDevice(private val bridge: CliAccessibilityBridge) : FarmDevice {
    override fun screenshot(): ScreenImage {
        val png = bridge.capture()
        val decoded = OpenCvKit.decodePng(png)
        val image = CapturedScreen(decoded.cols(), decoded.rows(), png)
        decoded.release()
        return image
    }

    override fun tap(point: Pair<Int, Int>) = bridge.tap(point.first, point.second)
    override fun swipe(start: Pair<Int, Int>, end: Pair<Int, Int>, durationMs: Int) =
        bridge.swipe(start.first, start.second, end.first, end.second, durationMs)
    override fun back() = bridge.back()
    override fun installedPackages(): Set<String> {
        val array = JSONArray(bridge.installedPackages())
        return (0 until array.length()).map { array.getString(it) }.toSet()
    }
    override fun startActivity(component: String) {
        bridge.launch(component.substringBefore("/"), component.substringAfter("/", ""))
    }
}

private class BridgeGameDevice(private val bridge: CliAccessibilityBridge) : ArrowDevice {
    override val packageName = bridge.foreground()
    private var sourceWidth = 720
    private var normalizedHeight = 1600

    override fun screenshot(): Mat {
        if (bridge.foreground() != packageName) throw RuntimeException("前台应用已切换，停止游戏")
        val decoded = OpenCvKit.decodePng(bridge.capture())
        sourceWidth = decoded.cols()
        val normalized = normalizeWidth(decoded)
        normalizedHeight = normalized.rows()
        decoded.release()
        return normalized
    }

    override fun tap(x: Int, y: Int) {
        if (bridge.foreground() != packageName) throw RuntimeException("前台应用已切换，停止游戏点击")
        val ratio = sourceWidth / 720.0
        bridge.tap(pyRound(x * ratio), pyRound(y * ratio))
    }

    override fun swipeAd(upwards: Boolean) {
        if (bridge.foreground() != packageName) throw RuntimeException("前台应用已切换，停止广告浏览")
        val ratio = sourceWidth / 720.0
        val bottom = pyRound(normalizedHeight * 0.78 * ratio)
        val top = pyRound(normalizedHeight * 0.30 * ratio)
        val (start, end) = if (upwards) bottom to top else top to bottom
        val x = pyRound(360 * ratio)
        bridge.swipe(x, start, x, end, 650)
    }
}
