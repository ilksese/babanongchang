package com.babanongchang.android.engine

import java.io.File
import java.math.BigDecimal

open class AutomationError(message: String) : Exception(message)
class WaitTimeoutError(message: String) : AutomationError(message)

interface Clock {
    fun monotonic(): Double
    fun sleep(seconds: Double)
    fun checkpoint()
}

interface ScreenImage {
    val width: Int
    val height: Int
}

interface FarmDevice {
    fun screenshot(): ScreenImage
    fun tap(point: Pair<Int, Int>)
    fun swipe(start: Pair<Int, Int>, end: Pair<Int, Int>, durationMs: Int)
    fun back()
    fun installedPackages(): Set<String>
    fun startActivity(component: String)
}

data class OcrRaw(
    val texts: List<String>?,
    val scores: List<Double>?,
    val boxes: List<List<Pair<Double, Double>>>?,
)

interface OcrEngine {
    fun recognize(image: ScreenImage): OcrRaw
    fun close() {}
}

data class OcrText(
    val text: String,
    val score: Double,
    val box: List<Pair<Double, Double>>,
) {
    val center: Pair<Int, Int>
        get() = box.map { it.first }.average().toInt() to box.map { it.second }.average().toInt()
    val normalizedText: String get() = normalizeText(text)
    val top: Double get() = box.minOf { it.second }
}

data class ScreenSnapshot(
    val width: Int,
    val height: Int,
    val items: List<OcrText>,
) {
    val shape: Pair<Int, Int> get() = height to width
    val texts: List<String> get() = items.map { it.text }
}

data class RelativeRegion(
    val left: Double = 0.0,
    val top: Double = 0.0,
    val right: Double = 1.0,
    val bottom: Double = 1.0,
) {
    init {
        require(0 <= left && left < right && right <= 1 && 0 <= top && top < bottom && bottom <= 1) {
            "相对区域坐标必须满足 0 <= left < right <= 1 且 0 <= top < bottom <= 1"
        }
    }

    fun contains(point: Pair<Int, Int>, imageShape: Pair<Int, Int>): Boolean {
        val (height, width) = imageShape
        val (x, y) = point
        return left * width < x && x < right * width && top * height < y && y < bottom * height
    }
}

data class ProjectConfig(
    val screenshotIntervalMs: Int = 200,
    val recognitionTimeoutMs: Int = 10_000,
)

fun loadProjectConfig(path: File): ProjectConfig {
    if (!path.isFile) return ProjectConfig()
    val values = mutableMapOf<String, String>()
    var section = ""
    path.readText().lineSequence().forEach { raw ->
        val line = raw.substringBefore("#").trim()
        if (line.isEmpty()) return@forEach
        if (line.startsWith("[") && line.endsWith("]")) {
            section = line.substring(1, line.length - 1).trim()
            return@forEach
        }
        if (section != "ocr" || !line.contains("=")) return@forEach
        val key = line.substringBefore("=").trim()
        val value = line.substringAfter("=").trim().trim('"')
        if (key == "ocr") throw IllegalArgumentException("配置项 ocr 必须是 TOML 表")
        values[key] = value
    }
    if (path.readText().lineSequence().any { it.trim().startsWith("ocr") && it.contains("=") && !it.trim().startsWith("[") }) {
        throw IllegalArgumentException("配置项 ocr 必须是 TOML 表")
    }
    return ProjectConfig(
        positiveInteger(values["screenshot_interval_ms"], "ocr.screenshot_interval_ms", 200),
        positiveInteger(values["recognition_timeout_ms"], "ocr.recognition_timeout_ms", 10_000),
    )
}

private fun positiveInteger(value: String?, key: String, default: Int): Int {
    if (value == null) return default
    val parsed = value.toIntOrNull()
    if (parsed == null || parsed <= 0) throw IllegalArgumentException("配置项 $key 必须是大于 0 的整数")
    return parsed
}

fun normalizeText(text: String) = text.replace(Regex("\\s+"), "")

fun formatG(value: Double): String = BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()

const val MIN_BROWSE_SECONDS = 15.0
val FARM_MODULES = setOf("all", "fertilize", "goods", "tasks", "taobao")

data class FarmOptions(
    val threshold: Int = 600,
    val browseSeconds: Double = 18.0,
    val maxClicks: Int? = null,
    val taobaoMinScore: Double = 0.75,
) {
    init {
        if (threshold < 0 || browseSeconds < MIN_BROWSE_SECONDS) {
            throw IllegalArgumentException("threshold 不能为负数，browse-seconds 不能少于 15 秒")
        }
        if (maxClicks != null && maxClicks < 1) throw IllegalArgumentException("max-clicks 必须大于 0")
        if (taobaoMinScore !in 0.0..1.0) throw IllegalArgumentException("淘宝 OCR 置信度阈值必须在 0 到 1 之间")
    }
}

data class GameOptions(
    val levels: Int = 3,
    val target: Int? = null,
    val maxMinutes: Double = 15.0,
    val mode: String = "safe",
    val delay: Double = 0.65,
    val idleTimeout: Double = 35.0,
    val maxRestarts: Int = 0,
    val streakPolicy: String = "coins-or-abandon",
    val reviveAds: Boolean = true,
    val adTimeout: Double = 180.0,
    val boardTop: Double = 0.146,
    val boardBottom: Double = 0.824,
    val output: File = File("artifacts/nlgj"),
    val dryRun: Boolean = false,
) {
    init {
        if (!(0 <= boardTop && boardTop < boardBottom && boardBottom <= 1)) {
            throw IllegalArgumentException("Require 0 <= --board-top < --board-bottom <= 1")
        }
        if (target != null && target < 1) throw IllegalArgumentException("Require --target >= 1")
        if (minOf(levels, maxRestarts) < 0 || minOf(maxMinutes, delay, idleTimeout, adTimeout) <= 0) {
            throw IllegalArgumentException("Require nonnegative --levels and positive timing values")
        }
    }

    companion object {
        val defaultOutput: File = File("artifacts/nlgj")
    }
}

sealed class RunRequest {
    data class Farm(val module: String, val options: FarmOptions) : RunRequest()
    data class Game(val options: GameOptions) : RunRequest()
}

fun parseRun(module: String, options: String, taobaoMinScore: Double = FarmOptions().taobaoMinScore): RunRequest {
    if (module == "app") throw IllegalArgumentException("APK 不支持桌面界面")
    val argv = splitArgs(options)
    if ("--serial" in argv || argv.any { it == "--adb" || it.startsWith("--adb=") }) {
        throw IllegalArgumentException("APK 操作本机，不支持 --serial 或 --adb")
    }
    val flags = linkedMapOf<String, MutableList<String>>()
    val bare = mutableListOf<String>()
    var index = 0
    while (index < argv.size) {
        val token = argv[index]
        if (token.startsWith("--")) {
            val body = token.removePrefix("--")
            if (body.contains("=")) {
                val key = body.substringBefore("=")
                flags.getOrPut(key) { mutableListOf() }.add(body.substringAfter("="))
            } else if (index + 1 < argv.size && !argv[index + 1].startsWith("--")) {
                flags.getOrPut(body) { mutableListOf() }.add(argv[index + 1])
                index += 1
            } else {
                flags.getOrPut(body) { mutableListOf() }
            }
        } else {
            bare += token
        }
        index += 1
    }
    if (bare.isNotEmpty()) throw IllegalArgumentException("无法识别的参数：${bare.joinToString(" ")}")
    val nlgj = flags.containsKey("nlgj")
    flags.remove("nlgj")
    if ((module == "games") != nlgj) throw IllegalArgumentException("游戏请使用 games --nlgj")
    val known = setOf(
        "threshold", "browse-seconds", "max-clicks", "levels", "target", "max-minutes", "mode",
        "delay", "idle-timeout", "max-restarts", "streak-policy", "no-revive-ads", "ad-timeout",
        "board-top", "board-bottom", "output", "dry-run",
    )
    val unknown = flags.keys - known
    if (unknown.isNotEmpty()) throw IllegalArgumentException("无法识别的参数：${unknown.joinToString(" ")}")
    fun value(name: String) = flags[name]?.singleOrNull()
    fun integer(name: String): Int? = value(name)?.let { text ->
        text.toIntOrNull() ?: throw IllegalArgumentException("--$name 必须是整数")
    }
    fun number(name: String): Double? = value(name)?.let { text ->
        text.toDoubleOrNull() ?: throw IllegalArgumentException("--$name 必须是数字")
    }
    val defaults = FarmOptions()
    val gameDefaults = GameOptions()
    if (module == "games") {
        val mode = value("mode") ?: gameDefaults.mode
        if (mode !in setOf("safe", "fast")) throw IllegalArgumentException("--mode 只能是 safe 或 fast")
        val streak = value("streak-policy") ?: gameDefaults.streakPolicy
        if (streak !in setOf("coins-or-abandon", "stop")) {
            throw IllegalArgumentException("--streak-policy 无效")
        }
        return RunRequest.Game(GameOptions(
            levels = integer("levels") ?: gameDefaults.levels,
            target = integer("target"),
            maxMinutes = number("max-minutes") ?: gameDefaults.maxMinutes,
            mode = mode,
            delay = number("delay") ?: gameDefaults.delay,
            idleTimeout = number("idle-timeout") ?: gameDefaults.idleTimeout,
            maxRestarts = integer("max-restarts") ?: gameDefaults.maxRestarts,
            streakPolicy = streak,
            reviveAds = !flags.containsKey("no-revive-ads"),
            adTimeout = number("ad-timeout") ?: gameDefaults.adTimeout,
            boardTop = number("board-top") ?: gameDefaults.boardTop,
            boardBottom = number("board-bottom") ?: gameDefaults.boardBottom,
            output = value("output")?.let { File(it) } ?: gameDefaults.output,
            dryRun = flags.containsKey("dry-run"),
        ))
    }
    if (module !in FARM_MODULES) throw IllegalArgumentException("未知农场功能：$module")
    return RunRequest.Farm(module, FarmOptions(
        threshold = integer("threshold") ?: defaults.threshold,
        browseSeconds = number("browse-seconds") ?: defaults.browseSeconds,
        maxClicks = integer("max-clicks"),
        taobaoMinScore = taobaoMinScore,
    ))
}

fun splitArgs(options: String): List<String> {
    val args = mutableListOf<String>()
    val current = StringBuilder()
    var quote: Char? = null
    var escaped = false
    fun flush() {
        if (current.isNotEmpty()) {
            args += current.toString()
            current.clear()
        }
    }
    for (char in options) {
        when {
            escaped -> { current.append(char); escaped = false }
            char == '\\' && quote != '\'' -> escaped = true
            quote != null -> if (char == quote) quote = null else current.append(char)
            char == '"' || char == '\'' -> quote = char
            char.isWhitespace() -> flush()
            else -> current.append(char)
        }
    }
    if (quote != null || escaped) throw IllegalArgumentException("参数引号未闭合")
    flush()
    return args
}
