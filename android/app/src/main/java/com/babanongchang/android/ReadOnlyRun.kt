package com.babanongchang.android

class PlatformFailure(val userReason: String) : Exception(userReason)

data class Bounds(val left: Int, val top: Int, val right: Int, val bottom: Int)
data class OcrLine(val text: String, val bounds: Bounds)
data class OcrFrame(val width: Int, val height: Int, val lines: List<OcrLine>)
data class FarmRecognition(val fertilizerBalance: Long, val button: Bounds)
enum class VolumeKey { UP, DOWN }

data class RunView(
    val running: Boolean = false,
    val paused: Boolean = false,
    val overlayVisible: Boolean = true,
    val message: String = "只读验证：请手动进入支付宝芭芭农场",
    val recognition: FarmRecognition? = null,
)

/** Platform boundary: callbacks, timers and user events are serialized on the main thread. */
interface ReadOnlyPlatform {
    fun nowMillis(): Long
    fun unavailableReason(): String?
    fun show(view: RunView)
    fun schedule(delayMillis: Long, action: () -> Unit)
    /** Check isCurrent before every async continuation, especially before starting OCR. */
    fun captureAndRecognize(isCurrent: () -> Boolean, callback: (Result<OcrFrame>) -> Unit)
}

class ReadOnlyRun(private val platform: ReadOnlyPlatform) {
    var view = RunView()
        private set

    private var generation = 0L
    private var deadline = 0L
    private var remainingMillis = 10_000L
    private val heldKeys = mutableMapOf<VolumeKey, Boolean>()

    fun onVolumeKey(key: VolumeKey, down: Boolean, repeatCount: Int = 0): Boolean {
        if (!down) return heldKeys.remove(key) ?: false
        heldKeys[key]?.let { return it }
        val consume = view.running || view.paused
        heldKeys[key] = consume
        if (consume && repeatCount == 0) {
            if (key == VolumeKey.UP) pause() else end()
        }
        return consume
    }

    fun start() {
        if (view.running || view.paused) return
        remainingMillis = 10_000
        beginRecognition()
    }

    fun resume() {
        if (view.paused) beginRecognition()
    }

    fun end() {
        if (view.running || view.paused) finish("已结束；未发起施肥尝试")
    }

    private fun pause() {
        if (!view.running) return
        remainingMillis = (deadline - platform.nowMillis()).coerceAtLeast(0)
        generation++
        view = RunView(paused = true, message = "已暂停：请通过浮层继续或结束；未发起施肥尝试")
        platform.show(view)
    }

    private fun beginRecognition() {
        val token = ++generation
        val problem = platform.unavailableReason()
        if (problem != null) {
            view = RunView(message = "已停止：$problem；未发起施肥尝试")
            platform.show(view)
            return
        }
        view = RunView(running = true, overlayVisible = false, message = "正在只读识别")
        platform.show(view)
        deadline = platform.nowMillis() + remainingMillis
        platform.schedule(remainingMillis) {
            if (active(token)) finish("已停止：只读识别超时（10秒）；未发起施肥尝试")
        }
        // Allow the accessibility overlay removal to reach the display before capturing.
        platform.schedule(200) {
            if (!active(token)) return@schedule
            val problem = platform.unavailableReason()
            if (problem != null) {
                finish("已停止：$problem；未发起施肥尝试")
                return@schedule
            }
            platform.captureAndRecognize({ active(token) && platform.nowMillis() < deadline }) { result ->
                if (!active(token)) return@captureAndRecognize
                val problem = platform.unavailableReason()
                if (problem != null) {
                    finish("已停止：$problem；未发起施肥尝试")
                    return@captureAndRecognize
                }
                if (platform.nowMillis() >= deadline) {
                    finish("已停止：只读识别超时（10秒）；未发起施肥尝试")
                    return@captureAndRecognize
                }
                val frame = result.getOrNull()
                if (frame == null) {
                    val reason = (result.exceptionOrNull() as? PlatformFailure)?.userReason
                        ?: "截图或中文识别失败"
                    finish("已停止：$reason；未发起施肥尝试")
                    return@captureAndRecognize
                }
                if (frame.lines.any { line ->
                        listOf("恭喜", "奖励", "立即领取", "开心收下", "做任务集肥料", "做任务领肥料")
                            .any { it in line.text }
                    }) {
                    finish("已停止：发现弹窗或任务页面；未发起施肥尝试")
                    return@captureAndRecognize
                }
                if (frame.lines.count { it.text.replace(Regex("\\s+"), "") == "芭芭农场" } != 1) {
                    finish("已停止：无法确认芭芭农场页面；未发起施肥尝试")
                    return@captureAndRecognize
                }
                val lines = frame.lines.map { it.copy(text = it.text.replace(Regex("\\s+"), "")) }
                val balanceLabels = lines.filter { it.text.startsWith("肥料") }
                val balance = balanceLabels.singleOrNull()?.text
                    ?.let { Regex("肥料[：:]?([0-9]+)").matchEntire(it)?.groupValues?.get(1)?.toLongOrNull() }
                val button = lines.filter { it.text == "施肥" }.singleOrNull()?.bounds
                if (balance == null || button == null ||
                    button.left < 0 || button.top < 0 || button.right > frame.width ||
                    button.bottom > frame.height || button.left >= button.right || button.top >= button.bottom
                ) {
                    finish("已停止：肥料余额或施肥按钮无法唯一确认；未发起施肥尝试")
                    return@captureAndRecognize
                }
                view = RunView(
                    message = "只读识别完成：农场已确认，肥料余额 $balance，施肥按钮已定位；未发起施肥尝试",
                    recognition = FarmRecognition(balance, button),
                )
                platform.show(view)
            }
        }
    }

    fun stop(reason: String) {
        if (view.running || view.paused) finish("已停止：$reason；未发起施肥尝试")
    }

    private fun active(token: Long) = view.running && token == generation

    private fun finish(message: String) {
        generation++
        view = RunView(message = message)
        platform.show(view)
    }
}
