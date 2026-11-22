package com.babanongchang.android.engine

class TextHandle(
    val device: FarmDevice,
    private val ocr: OcrEngine,
    val minScore: Double = 0.75,
    val config: ProjectConfig = ProjectConfig(),
    val clock: Clock,
) {
    init {
        require(minScore in 0.0..1.0) { "OCR 最低置信度必须在 0 到 1 之间" }
    }

    fun scan(): ScreenSnapshot {
        clock.checkpoint()
        val image = device.screenshot()
        clock.checkpoint()
        val result = ocr.recognize(image)
        clock.checkpoint()
        if (result.texts == null || result.boxes == null || result.scores == null) {
            return ScreenSnapshot(image.width, image.height, emptyList())
        }
        val items = result.texts.zip(result.scores).zip(result.boxes).mapNotNull { (pair, box) ->
            val (text, score) = pair
            if (score < minScore) null else OcrText(text, score, box)
        }
        return ScreenSnapshot(image.width, image.height, items)
    }

    fun <T> waitForScreen(
        matcher: (ScreenSnapshot) -> T?,
        timeout: Int? = null,
        interval: Int? = null,
        error: String = "等待目标页面超时",
    ): T {
        val limit = timeout ?: config.recognitionTimeoutMs
        val intervalSeconds = validateWait(limit, interval)
        val deadline = clock.monotonic() + limit / 1000.0
        while (clock.monotonic() < deadline) {
            val found = matcher(scan())
            if (found != null) return found
            clock.sleep(intervalSeconds)
        }
        throw WaitTimeoutError(error)
    }

    fun waitForStableScreen(
        predicate: (ScreenSnapshot) -> Boolean,
        stableScans: Int = 2,
        signature: ((ScreenSnapshot) -> Any?)? = null,
        timeout: Int? = null,
        interval: Int? = null,
        error: String = "等待页面稳定超时",
    ): ScreenSnapshot {
        require(stableScans >= 1) { "稳定扫描次数必须大于 0" }
        var stableCount = 0
        var previous: Any? = null
        var seen = false
        return waitForScreen({ snapshot ->
            if (!predicate(snapshot)) {
                previous = null
                seen = false
                stableCount = 0
                return@waitForScreen null
            }
            val current = signature?.invoke(snapshot)
            stableCount = if (signature == null || (seen && current == previous)) stableCount + 1 else 1
            previous = current
            seen = true
            if (stableCount >= stableScans) snapshot else null
        }, timeout, interval, error)
    }

    fun waitForStableText(
        text: String,
        stableScans: Int = 2,
        positionTolerance: Int = 8,
        screenPredicate: ((ScreenSnapshot) -> Boolean)? = null,
        timeout: Int? = null,
        interval: Int? = null,
        exact: Boolean = false,
        error: String? = null,
    ): OcrText {
        require(stableScans >= 1) { "稳定扫描次数必须大于 0" }
        require(positionTolerance >= 0) { "位置容差不能小于 0" }
        var previous: Pair<Int, Int>? = null
        var stableCount = 0
        return waitForScreen({ snapshot ->
            val found = findText(snapshot.items, text, exact)
            if (found == null || (screenPredicate != null && !screenPredicate(snapshot))) {
                previous = null
                stableCount = 0
                return@waitForScreen null
            }
            val center = found.center
            val prior = previous
            stableCount = if (prior != null &&
                kotlin.math.abs(center.first - prior.first) <= positionTolerance &&
                kotlin.math.abs(center.second - prior.second) <= positionTolerance
            ) stableCount + 1 else 1
            previous = center
            if (stableCount >= stableScans) found else null
        }, timeout, interval, error ?: "等待“$text”稳定出现超时")
    }

    fun waitForText(
        text: String,
        timeout: Int? = null,
        exact: Boolean = false,
        region: RelativeRegion? = null,
    ): Pair<Int, Int> = waitForAllText(listOf(text), timeout, exact, region).single()

    fun waitForAllText(
        texts: List<String>,
        timeout: Int? = null,
        exact: Boolean = false,
        region: RelativeRegion? = null,
    ): List<Pair<Int, Int>> {
        if (texts.isEmpty() || texts.any { normalizeText(it).isEmpty() }) throw IllegalArgumentException("等待文案不能为空")
        val description = texts.joinToString("、") { "“$it”" }
        return waitForScreen({ snapshot ->
            val used = mutableSetOf<OcrText>()
            val selected = mutableListOf<OcrText>()
            for (value in texts) {
                val found = findTexts(snapshot.items, value, exact, region, snapshot.shape)
                    .firstOrNull { it !in used } ?: return@waitForScreen null
                selected += found
                used += found
            }
            selected.map { it.center }
        }, timeout, error = "等待${description}超时，已停止以避免误点")
    }

    fun waitForAnyText(
        texts: List<String>,
        timeout: Int? = null,
        exact: Boolean = false,
        region: RelativeRegion? = null,
    ): Pair<String, Pair<Int, Int>> {
        if (texts.isEmpty() || texts.any { normalizeText(it).isEmpty() }) throw IllegalArgumentException("等待文案不能为空")
        val description = texts.joinToString("、") { "“$it”" }
        return waitForScreen({ snapshot ->
            texts.firstNotNullOfOrNull { value ->
                findText(snapshot.items, value, exact, region, snapshot.shape)?.let { value to it.center }
            }
        }, timeout, error = "等待任一文案 $description 超时")
    }

    fun waitForTextGone(
        text: String,
        timeout: Int? = null,
        exact: Boolean = false,
        stableScans: Int = 1,
    ): ScreenSnapshot = waitForStableScreen(
        { !hasText(it.items, text, exact) },
        stableScans,
        timeout = timeout,
        error = "等待“$text”消失超时",
    )

    fun clickText(
        text: String,
        wait: Boolean = true,
        timeout: Int? = null,
        exact: Boolean = false,
        region: RelativeRegion? = null,
    ): Pair<Int, Int> {
        val point = if (wait) {
            waitForText(text, timeout, exact, region)
        } else {
            if (normalizeText(text).isEmpty()) throw IllegalArgumentException("点击文案不能为空")
            val snapshot = scan()
            findText(snapshot.items, text, exact, region, snapshot.shape)?.center
                ?: throw AutomationError("当前屏幕未找到“$text”，已停止以避免误点")
        }
        device.tap(point)
        return point
    }

    fun <T> tapAndWait(
        point: Pair<Int, Int>,
        matcher: (ScreenSnapshot) -> T?,
        timeout: Int? = null,
        interval: Int? = null,
        error: String = "点击后未进入目标页面",
    ): T {
        device.tap(point)
        return waitForScreen(matcher, timeout, interval, error)
    }

    private fun validateWait(timeout: Int, interval: Int?): Double {
        require(timeout > 0) { "timeout 必须大于 0" }
        val resolved = interval ?: config.screenshotIntervalMs
        require(resolved > 0) { "interval 必须大于 0" }
        return resolved / 1000.0
    }

    companion object {
        fun findTexts(
            items: List<OcrText>,
            target: String,
            exact: Boolean = false,
            region: RelativeRegion? = null,
            imageShape: Pair<Int, Int>? = null,
            order: String = "confidence",
        ): List<OcrText> {
            val normalizedTarget = normalizeText(target)
            require(normalizedTarget.isNotEmpty()) { "查找文案不能为空" }
            if (region != null && imageShape == null) throw IllegalArgumentException("使用区域过滤时必须提供 image_shape")
            val matches = items.filter { item ->
                val matched = if (exact) item.normalizedText == normalizedTarget else normalizedTarget in item.normalizedText
                matched && (region == null || region.contains(item.center, imageShape!!))
            }
            return when (order) {
                "confidence" -> matches.sortedByDescending { it.score }
                "reading" -> matches.sortedWith(compareBy({ it.center.second }, { it.center.first }))
                else -> throw IllegalArgumentException("不支持的文字排序方式：$order")
            }
        }

        fun findText(
            items: List<OcrText>,
            target: String,
            exact: Boolean = false,
            region: RelativeRegion? = null,
            imageShape: Pair<Int, Int>? = null,
        ): OcrText? = findTexts(items, target, exact, region, imageShape).firstOrNull()

        fun hasText(items: List<OcrText>, target: String, exact: Boolean = false) =
            findText(items, target, exact) != null

        fun findSameRowText(
            items: List<OcrText>,
            imageShape: Pair<Int, Int>,
            anchorMatcher: (OcrText) -> Boolean,
            targetTexts: List<String>,
            targetRegion: RelativeRegion? = null,
            targetOnRight: Boolean = true,
            maxVerticalRatio: Double = 0.06,
        ): OcrText? {
            require(maxVerticalRatio > 0) { "同行文字纵向容差必须大于 0" }
            if (targetTexts.isEmpty() || targetTexts.any { normalizeText(it).isEmpty() }) {
                throw IllegalArgumentException("目标文案不能为空")
            }
            val height = imageShape.first
            val anchors = items.filter(anchorMatcher)
            val candidates = items.filter { item ->
                targetTexts.any { normalizeText(it) in item.normalizedText } &&
                    (targetRegion == null || targetRegion.contains(item.center, imageShape))
            }
            val pairs = anchors.flatMap { anchor ->
                candidates.mapNotNull { candidate ->
                    val aligned = (!targetOnRight || candidate.center.first > anchor.center.first) &&
                        kotlin.math.abs(candidate.center.second - anchor.center.second) < maxVerticalRatio * height
                    if (aligned) anchor to candidate else null
                }
            }
            return pairs.maxByOrNull { it.first.score + it.second.score }?.second
        }

        fun screenSignature(items: List<OcrText>, include: ((OcrText) -> Boolean)? = null): List<String> =
            items.mapNotNull { item ->
                item.normalizedText.takeIf { it.isNotEmpty() && (include == null || include(item)) }
            }.sorted()
    }
}

fun findBrowseIteration(texts: Iterable<String>): Int? {
    val iterations = texts.flatMap { Regex("第\\s*(\\d+)\\s*次").findAll(it).map { match -> match.groupValues[1].toInt() } }
    return iterations.filter { it > 0 }.maxOrNull()
}

fun swipeBrowse(
    device: FarmDevice,
    durationSeconds: Double = 18.0,
    clock: Clock,
    log: (String) -> Unit = {},
) {
    require(durationSeconds > 0) { "浏览时长必须大于 0" }
    val image = device.screenshot()
    val upper = image.width / 2 to (image.height * 0.36).toInt()
    val lower = image.width / 2 to (image.height * 0.74).toInt()
    val deadline = clock.monotonic() + durationSeconds
    var downward = true
    log("开始上下往复滑动 ${formatG(durationSeconds)} 秒")
    while (clock.monotonic() < deadline) {
        val (start, end) = if (downward) upper to lower else lower to upper
        device.swipe(start, end, 650)
        downward = !downward
        clock.sleep(0.2)
    }
    log("浏览时间已满足，准备返回")
}

data class BackResult(val snapshot: ScreenSnapshot, val backCount: Int)

fun backUntil(
    device: FarmDevice,
    handle: TextHandle,
    predicate: (ScreenSnapshot) -> Boolean,
    timeout: Int = ProjectConfig().recognitionTimeoutMs,
    interval: Int = 1000,
    maxBacks: Int? = null,
    error: String = "多次返回后仍未进入目标页面",
    clock: Clock,
): BackResult {
    require(timeout > 0 && interval > 0) { "timeout 和 interval 必须大于 0" }
    if (maxBacks != null) require(maxBacks >= 1) { "max_backs 必须大于 0" }
    val deadline = clock.monotonic() + timeout / 1000.0
    var backCount = 0
    while (clock.monotonic() < deadline) {
        val snapshot = handle.scan()
        if (predicate(snapshot)) return BackResult(snapshot, backCount)
        if (maxBacks != null && backCount >= maxBacks) break
        device.back()
        backCount += 1
        clock.sleep(interval / 1000.0)
    }
    throw WaitTimeoutError(error)
}
