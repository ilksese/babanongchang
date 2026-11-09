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
    val message: String = "单次施肥验证（非正式可用版）：请手动进入支付宝芭芭农场",
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
    /** One dispatch only; completion is not evidence that fertilizer was consumed. */
    fun tap(button: Bounds, callback: (Boolean) -> Unit): Boolean
}

class ReadOnlyRun(private val platform: ReadOnlyPlatform) {
    var view = RunView()
        private set

    private var generation = 0L
    private var deadline = 0L
    private var remainingMillis = 10_000L
    private var baseline: Long? = null
    private var attemptDispatched = false
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
        baseline = null
        attemptDispatched = false
        remainingMillis = 10_000
        beginRecognition()
    }

    fun resume() {
        if (view.paused) beginRecognition()
    }

    fun end() {
        if (view.running || view.paused) finish(if (baseline == null) "已结束；未发起施肥尝试" else "已结束，施肥结果未确认")
    }

    private fun pause() {
        if (!view.running) return
        remainingMillis = (deadline - platform.nowMillis()).coerceAtLeast(0)
        generation++
        view = RunView(paused = true, message = "已暂停：请通过浮层继续或结束；${attemptStatus()}")
        platform.show(view)
    }

    private fun beginRecognition() {
        val token = ++generation
        val problem = platform.unavailableReason()
        if (problem != null) {
            finish("已停止：$problem；${attemptStatus()}")
            return
        }
        view = RunView(running = true, overlayVisible = false,
            message = if (baseline == null) "正在确认施肥条件" else "正在确认原施肥尝试的结果")
        platform.show(view)
        deadline = platform.nowMillis() + remainingMillis
        platform.schedule(remainingMillis) {
            if (active(token)) {
                platform.unavailableReason()?.let { stop(it) } ?: timeout()
            }
        }
        // Allow the accessibility overlay removal to reach the display before capturing.
        platform.schedule(if (baseline == null) 200 else 500) { if (active(token)) capture(token) }
    }

    private fun capture(token: Long) {
        if (!active(token)) return
        val problem = platform.unavailableReason()
        if (problem != null) {
            stop(problem)
            return
        }
        var delivered = false
        platform.captureAndRecognize({ active(token) && !delivered && platform.nowMillis() < deadline }) { result ->
            if (!active(token) || delivered) return@captureAndRecognize
            delivered = true
            val problem = platform.unavailableReason()
            if (problem != null) {
                stop(problem)
                return@captureAndRecognize
            }
            if (platform.nowMillis() >= deadline) {
                timeout()
                return@captureAndRecognize
            }
            val frame = result.getOrNull()
            if (frame == null) {
                val reason = (result.exceptionOrNull() as? PlatformFailure)?.userReason
                    ?: "截图或中文识别失败"
                stop(reason)
                return@captureAndRecognize
            }
            if (frame.lines.any { line ->
                    listOf("恭喜", "奖励", "立即领取", "开心收下", "做任务集肥料", "做任务领肥料")
                        .any { it in line.text }
                }) {
                stop("发现弹窗或任务页面")
                return@captureAndRecognize
            }
            if (frame.lines.count { it.text.replace(Regex("\\s+"), "") == "芭芭农场" } != 1) {
                stop("无法确认芭芭农场页面")
                return@captureAndRecognize
            }
            val lines = frame.lines.map { it.copy(text = it.text.replace(Regex("\\s+"), "")) }
            val balanceLabels = lines.filter { it.text.startsWith("肥料") }
            val balance = balanceLabels.singleOrNull()?.text
                ?.let { Regex("肥料[：:]?([0-9]+)").matchEntire(it)?.groupValues?.get(1)?.toLongOrNull() }
            val button = lines.filter { it.text == "施肥" }.singleOrNull()?.bounds
            if (balance == null || (baseline == null && (button == null ||
                button.left < 0 || button.top < 0 || button.right > frame.width ||
                button.bottom > frame.height || button.left >= button.right || button.top >= button.bottom))
            ) {
                stop("肥料余额或施肥按钮无法唯一确认")
                return@captureAndRecognize
            }
            val before = baseline
            if (before == null) {
                if (balance <= 600) {
                    finish("未执行：肥料余额 $balance 不大于保护阈值 600；未发起施肥尝试")
                    return@captureAndRecognize
                }
                baseline = balance
                remainingMillis = 10_000
                beginRecognition()
                val gestureToken = generation
                if (!active(gestureToken)) return@captureAndRecognize
                val dispatchProblem = platform.unavailableReason()
                if (dispatchProblem != null) {
                    baseline = null
                    stop(dispatchProblem)
                    return@captureAndRecognize
                }
                val accepted = try {
                    platform.tap(requireNotNull(button)) { completed ->
                        if (active(gestureToken) && !completed) gestureFailed()
                    }
                } catch (_: Exception) { false }
                if (active(gestureToken) && accepted) attemptDispatched = true
                if (active(gestureToken) && !accepted) gestureFailed()
            } else if (balance < before) {
                finish("施肥成功：肥料余额 $before → $balance")
            } else {
                platform.schedule(500) { if (active(token)) capture(token) }
            }
        }
    }

    fun stop(reason: String) {
        if (view.running || view.paused) finish("已停止：$reason；${attemptStatus()}")
    }

    private fun gestureFailed() = finish("结果未确认：施肥手势未能完成；不自动补点")

    private fun attemptStatus() = if (attemptDispatched) "施肥结果未确认" else "未发起施肥尝试"

    private fun timeout() {
        finish(if (baseline == null) "已停止：点击前识别超时（10秒）；未发起施肥尝试"
            else "结果未确认：确认肥料余额减少超时（10秒）；不自动补点")
    }

    private fun active(token: Long) = view.running && token == generation

    private fun finish(message: String) {
        generation++
        view = RunView(message = message)
        platform.show(view)
    }
}
