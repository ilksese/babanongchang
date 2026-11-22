package com.babanongchang.android.vision

import com.babanongchang.android.engine.Clock
import com.babanongchang.android.engine.GameOptions
import org.json.JSONObject
import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.Rect
import org.opencv.core.Scalar
import org.opencv.imgcodecs.Imgcodecs
import org.opencv.imgproc.Imgproc
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.max
import kotlin.math.min

interface ArrowDevice {
    val packageName: String
    fun screenshot(): Mat
    fun tap(x: Int, y: Int)
    fun swipeAd(upwards: Boolean)
}

data class GameLine(val text: String, val score: Double, val x: Int, val y: Int)

class NativeGameReader(private val ocr: RapidOcr) {
    fun read(image: Mat): List<GameLine> = ocr.read(image).map { item ->
        GameLine(
            item.text.replace(" ", ""),
            item.score,
            pyRound(item.box.map { it.first }.average()),
            pyRound(item.box.map { it.second }.average()),
        )
    }
}

private const val AD_SCROLL_SECONDS = 33.0

private class AdWait(val started: Double, var enteredAt: Double? = null, var scrollStartedAt: Double? = null, var returnRequestedAt: Double? = null) {
    fun confirmEntry(lines: List<GameLine>, height: Int, now: Double): Boolean {
        if (enteredAt != null) return true
        if (lines.any { it.score >= 0.85 && (it.y < 0.22 * height || it.y > 0.80 * height) && Regex("浏览30秒得奖励").containsMatchIn(it.text) }) {
            enteredAt = now
            return true
        }
        return false
    }

    fun startScrolling(now: Double) {
        check(enteredAt != null) { "Cannot scroll before the rewarded-ad page is confirmed" }
        if (scrollStartedAt == null) scrollStartedAt = now
    }

    fun remaining(now: Double): Double? = scrollStartedAt?.let { max(0.0, it + AD_SCROLL_SECONDS - now) }

    fun rewardIssued(lines: List<GameLine>, height: Int) = lines.any {
        it.score >= 0.85 && (it.y < 0.22 * height || it.y > 0.80 * height) && Regex("奖励了?已发放").containsMatchIn(it.text)
    }

    fun closeAction(image: Mat, lines: List<GameLine>, now: Double): Triple<Int, Int, String>? {
        val left = remaining(now)
        if (left == null || left > 0 || !rewardIssued(lines, image.rows())) return null
        lines.firstOrNull { it.score >= 0.90 && it.text in setOf("关闭", "关闭广告", "返回游戏", "跳过广告", "跳过") }
            ?.let { return Triple(it.x, it.y, "close-finished-ad") }
        return crossCandidates(image, adCorners = true).firstOrNull()?.let { Triple(it.second, it.third, "close-finished-ad-X") }
    }
}

private class AdScroller(private val device: ArrowDevice, private val clock: Clock) {
    @Volatile var stopped = false
    var error: Throwable? = null
    var swipes = 0
    private var thread: Thread? = null

    fun start() {
        thread = Thread({
            var upwards = true
            try {
                while (!stopped) {
                    clock.checkpoint()
                    device.swipeAd(upwards)
                    swipes += 1
                    upwards = !upwards
                }
            } catch (error: Throwable) {
                this.error = error
                stopped = true
            }
        }, "ad-scroll")
        thread!!.start()
    }

    fun stop() {
        stopped = true
        thread?.join(25_000)
    }
}

private data class Action(val x: Int, val y: Int, val reason: String, val balance: Int? = null, val price: Int? = null)

private fun streakAction(image: Mat, lines: List<GameLine>, policy: String): Action? {
    if (policy != "coins-or-abandon") return null
    val text = lines.joinToString(" ") { it.text }
    if ("恢复您的连胜" !in text || "获得福利" in text) return null
    val abandon = lines.filter { it.text == "残忍放弃" && it.score >= 0.95 && it.x > 0.15 * image.cols() && it.x < 0.5 * image.cols() && it.y > 0.4 * image.rows() && it.y < 0.8 * image.rows() }
    val balances = lines.mapNotNull { line ->
        if (line.score >= 0.95 && Regex("\\d+\\+?").matches(line.text) && line.x > 0.12 * image.cols() && line.x < 0.4 * image.cols() && line.y > 0 && line.y < 0.13 * image.rows())
            line.text.trimEnd('+').toInt() else null
    }
    if (abandon.size != 1 || balances.size != 1) return null
    val prices = lines.mapNotNull { line ->
        if (line.score >= 0.95 && Regex("\\d+").matches(line.text) && line.x > 0.5 * image.cols() && line.x < 0.85 * image.cols() && kotlin.math.abs(line.y - abandon[0].y) < 30)
            Triple(line.text.toInt(), line.x, line.y) else null
    }
    if (prices.size != 1 || prices[0].first <= 0) return null
    val (price, x, y) = prices[0]
    val balance = balances[0]
    return if (balance >= price) Action(x, y, "restore-streak-coins", balance, price)
    else Action(abandon[0].x, abandon[0].y, "abandon-streak-insufficient-coins", balance, price)
}

private fun reviveAction(image: Mat, lines: List<GameLine>): Action? {
    val text = lines.joinToString(" ") { it.text }
    if ("获得福利" in text || "恢复您的连胜" in text) return null
    val restartConfirmation = "重新开始" in text && "体力" in text
    val offer = "继续游戏" in text && listOf("恢复", "就差", "复活").any { it in text }
    if (!restartConfirmation && !offer) return null
    val button = lines.firstOrNull {
        it.score >= 0.85 && Regex("[D0O口回▶▷]*继续").matches(it.text) &&
            it.x > 0.3 * image.cols() && it.x < 0.7 * image.cols() && it.y > 0.45 * image.rows() && it.y < 0.8 * image.rows()
    } ?: return null
    return Action(button.x, button.y, if (restartConfirmation) "cancel-restart-for-revive" else "revive-watch-ad")
}

private fun popupAction(image: Mat, lines: List<GameLine>, allowNext: Boolean = true, allowRestart: Boolean = false): Action? {
    val height = image.rows()
    val width = image.cols()
    val modal = lines.filter { it.y > 0.18 * height && it.y < 0.84 * height }
    val text = modal.joinToString(" ") { it.text }
    if (listOf("支付", "购买", "授权", "登录", "安装").any { it in text }) return null
    val dismiss = setOf("关闭", "暂不", "不用了", "以后再说", "放弃奖励", "不领取", "继续游戏", "返回游戏")
    val advance = setOf("下一关", "下一关卡", "继续挑战")
    if ("获得福利" in text || "助力礼包" in text) {
        val candidate = crossCandidates(image).firstOrNull() ?: return null
        val roi = image.submat(Rect(max(0, candidate.second - 28), max(0, candidate.third - 28), min(57, image.cols() - max(0, candidate.second - 28)), min(57, image.rows() - max(0, candidate.third - 28))))
        val red = Mat()
        Core.inRange(roi, Scalar(20.0, 20.0, 160.0), Scalar(140.0, 140.0, 255.0), red)
        val redCount = countNonZero(red)
        roi.release(); red.release()
        if ("获得福利" in text && redCount < 80) return null
        return Action(candidate.second, candidate.third, if ("获得福利" in text) "close-welfare" else "close-gift")
    }
    for (line in lines) {
        if (line.score < 0.85 || line.y <= 0.18 * height || line.y >= 0.90 * height) continue
        val lowerRight = line.x > 0.55 * width && line.y > 0.70 * height
        if (line.text in dismiss || (allowNext && line.text in advance && lowerRight)) return Action(line.x, line.y, line.text)
        if (allowRestart && line.text == "重来" && "重新开始" in text) return Action(line.x, line.y, "restart")
        if (line.text == "免费" && "恢复您的连胜" in text) return Action(line.x, line.y, "restore-free-streak")
        if (line.text.startsWith("跳过") && !Regex("\\d").containsMatchIn(line.text)) return Action(line.x, line.y, line.text)
    }
    if (listOf("福利", "奖励", "领取", "广告", "暂停", "提示", "恭喜", "继续游戏").any { it in text }) {
        return crossCandidates(image).firstOrNull()?.let { Action(it.second, it.third, "close-X") }
    }
    return null
}

private fun fastSequence(board: Board): List<Triple<Int, Int, Int>> {
    val removed = mutableSetOf<Int>()
    val sequence = mutableListOf<Triple<Int, Int, Int>>()
    for (label in board.order) {
        if (!board.blockers.getValue(label).all { it in removed }) continue
        val point = tapPoint(board, label) ?: continue
        sequence += Triple(label, point.first, point.second)
        removed += label
    }
    return sequence
}

fun playGame(
    options: GameOptions,
    device: ArrowDevice,
    reader: NativeGameReader,
    clock: Clock,
    log: (String) -> Unit,
    recordEvents: Boolean = false,
) {
    options.output.mkdirs()
    val events = if (recordEvents) File(options.output, "events.jsonl").bufferedWriter() else null
    fun event(kind: String, fields: Map<String, Any?> = emptyMap()) {
        val entry = JSONObject()
        entry.put("time", LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss")))
        entry.put("event", kind)
        fields.forEach { (key, value) -> if (value != null) entry.put(key, value) }
        val line = entry.toString()
        log(line)
        events?.apply { write(line); newLine(); flush() }
    }
    event("start", mapOf("package" to device.packageName))
    val deadline = clock.monotonic() + options.maxMinutes * 60
    var completed = 0
    var lastAction = clock.monotonic()
    var lastCount: Int? = null
    var lastHearts: Int? = null
    var pending: Pair<Int, Int>? = null
    var pendingMask: Mat? = null
    var pendingAfter: Mat? = null
    var previousMask: Mat? = null
    var pendingSince = 0.0
    var lastLevel: Int? = null
    var levelActive = false
    var won = false
    var restarts = 0
    var adWait: AdWait? = null
    var coinAttempted = false
    var coinAttemptedAt = 0.0
    var predicted: Board? = null
    var adScroller: AdScroller? = null
    var nextLevelReadyAt: Double? = null
    var fastRoundCount: Int? = null
    var fastNoProgress = 0
    var stoppedByTime = true
    var previousShot: Mat? = null
    try {
        while (options.target != null || clock.monotonic() < deadline || adWait != null) {
            val image = device.screenshot()
            if (previousShot != null && previousShot !== predicted?.image && previousShot !== image) previousShot!!.release()
            previousShot = image
            Imgcodecs.imwrite(File(options.output, "latest.png").path, image)
            val mask = darkBoard(image, options.boardTop, options.boardBottom)
            val stable = previousMask?.let { differenceCount(mask, it) <= 2 } == true
            previousMask?.release()
            previousMask = mask.clone()
            val backgroundReady = whiteBoardBackground(image, options.boardTop, options.boardBottom)
            val reusePrediction = adWait == null && predicted != null && pendingAfter != null &&
                differenceCount(mask, pendingAfter!!) == 0 && backgroundReady
            if (!reusePrediction && adWait == null && pending != null && backgroundReady && clock.monotonic() - pendingSince < 5) {
                val hearts = heartCount(image)
                if (heartLost(lastHearts, hearts, finalTap = lastCount == 1)) {
                    event("stop", mapOf("reason" to "Lost a heart; saving screen for diagnosis"))
                    stoppedByTime = false
                    mask.release(); break
                }
                mask.release(); clock.sleep(0.15); continue
            }
            val board = if (reusePrediction) {
                predicted!!.also { reused ->
                    if (reused.image !== image) reused.image.release()
                    reused.image = image
                }
            } else if (adWait != null && !(backgroundReady && heartCount(image) > 0)) {
                Board(image, Mat.zeros(mask.size(), CvType.CV_32S), reason = "Ad")
            } else {
                recognizeBoard(image, options.boardTop, options.boardBottom)
            }
            if (adWait != null) {
                val needsOcr = adWait!!.enteredAt == null || adWait!!.returnRequestedAt != null
                val lines = if (needsOcr) reader.read(image) else emptyList()
                val levels = lines.mapNotNull { line ->
                    if (line.y < 0.14 * image.rows() && line.score >= 0.90) Regex("关卡[:：]?(\\d+)").find(line.text)?.groupValues?.get(1)?.toInt() else null
                }
                val headerLevel = levels.isNotEmpty() && (lastLevel == null || lastLevel in levels)
                if (headerLevel && heartCount(image) > 0 && (board.valid || board.reason == "No arrows")) {
                    adScroller?.stop(); adScroller = null
                    if (lastLevel == null) { lastLevel = levels[0]; levelActive = true }
                    event("revived", mapOf("level" to lastLevel))
                    adWait = null
                    lastCount = null; lastHearts = null; pending = null
                    pendingMask?.release(); pendingMask = null
                    pendingAfter?.release(); pendingAfter = null
                    fastRoundCount = null; fastNoProgress = 0; predicted = null
                    previousMask?.release(); previousMask = null
                    lastAction = clock.monotonic()
                    mask.release(); continue
                }
                val now = clock.monotonic()
                if (now - adWait!!.started > options.adTimeout) {
                    event("stop", mapOf("reason" to "Rewarded-ad entry/return not confirmed before timeout", "visible_text" to lines.joinToString(" ") { it.text }))
                    stoppedByTime = false; mask.release(); break
                }
                if (adWait!!.returnRequestedAt != null) {
                    event("ad-return-wait", mapOf("seconds" to kotlin.math.round((now - adWait!!.returnRequestedAt!!) * 10) / 10.0))
                    mask.release(); clock.sleep(1.0); continue
                }
                if (!adWait!!.confirmEntry(lines, image.rows(), now)) {
                    event("ad-wait-entry", mapOf("visible_text" to lines.joinToString(" ") { it.text }))
                    mask.release(); clock.sleep(0.5); continue
                }
                adScroller = AdScroller(device, clock).also { it.start() }
                adWait!!.startScrolling(clock.monotonic())
                event("ad-scroll-start", mapOf("mode" to "continuous-up-down", "seconds" to AD_SCROLL_SECONDS))
                clock.sleep(adWait!!.remaining(clock.monotonic()) ?: 0.0)
                adScroller!!.stop()
                adScroller!!.error?.let { throw RuntimeException("Ad scrolling failed: ${it.message}", it) }
                event("ad-scroll-stop", mapOf("swipes" to adScroller!!.swipes, "reason" to "fixed-33-seconds-finished"))
                adScroller = null
                val reward = device.screenshot()
                Imgcodecs.imwrite(File(options.output, "latest.png").path, reward)
                val rewardLines = reader.read(reward)
                val rewardNow = clock.monotonic()
                if (!adWait!!.rewardIssued(rewardLines, reward.rows())) {
                    event("stop", mapOf("reason" to "Reward not confirmed after fixed 33-second ad browse", "visible_text" to rewardLines.joinToString(" ") { it.text }))
                    reward.release(); mask.release(); stoppedByTime = false; break
                }
                val close = adWait!!.closeAction(reward, rewardLines, rewardNow)
                if (close == null) {
                    event("stop", mapOf("reason" to "Reward confirmed but no safe return control found", "visible_text" to rewardLines.joinToString(" ") { it.text }))
                    reward.release(); mask.release(); stoppedByTime = false; break
                }
                event("ad-close", mapOf("action" to close.third, "x" to close.first, "y" to close.second))
                device.tap(close.first, close.second)
                adWait!!.returnRequestedAt = clock.monotonic()
                reward.release(); mask.release(); clock.sleep(1.0); continue
            }
            if (board.valid) {
                coinAttempted = false
                if (!stable && pending == null) { mask.release(); clock.sleep(0.25); continue }
                val hearts = heartCount(image)
                if (lastHearts != null && hearts > 0 && hearts < lastHearts!!) {
                    event("stop", mapOf("reason" to "Lost a heart; saving screen for diagnosis"))
                    stoppedByTime = false; mask.release(); break
                }
                if (hearts > 0) lastHearts = hearts
                val count = board.arrows.size
                if (!levelActive) {
                    val headerHeight = pyRound(image.rows() * 0.14).coerceIn(1, image.rows())
                    val header = image.rowRange(0, headerHeight).clone()
                    reader.read(header).forEach { line ->
                        Regex("关卡[:：]?(\\d+)").find(line.text)?.let { lastLevel = it.groupValues[1].toInt() }
                    }
                    header.release()
                    levelActive = true
                    event("level", mapOf("level" to lastLevel, "arrows" to count))
                    Imgcodecs.imwrite(File(options.output, "level-$lastLevel-start.png").path, image)
                }
                if (lastCount != null && count > lastCount!!) {
                    event("stop", mapOf("reason" to "Unexpected board growth/change; refusing stale actions"))
                    stoppedByTime = false; mask.release(); break
                }
                if (pending != null) {
                    if (!arrowHasLeft(mask, pendingMask!!, count, lastCount!!, pendingAfter)) {
                        if (clock.monotonic() - pendingSince >= 10) {
                            event("stop", mapOf("reason" to "Arrow did not leave after tap; no repeated guessing"))
                            stoppedByTime = false; mask.release(); break
                        }
                        mask.release(); clock.sleep(0.4); continue
                    }
                    event("verified", mapOf("remaining" to count))
                    pending = null
                    pendingMask?.release(); pendingMask = null
                    pendingAfter?.release(); pendingAfter = null
                }
                val annotated = annotateBoard(board)
                Imgcodecs.imwrite(File(options.output, "annotated.png").path, annotated)
                annotated.release()
                if (options.dryRun) {
                    File(options.output, "report.json").writeText(reportJson(board))
                    event("dry-run", mapOf("arrows" to count, "order" to org.json.JSONArray(board.order)))
                    stoppedByTime = false; mask.release(); break
                }
                if (options.mode == "fast") {
                    if (fastRoundCount != null) {
                        fastNoProgress = if (count >= fastRoundCount!!) fastNoProgress + 1 else 0
                        if (fastNoProgress >= 2) {
                            event("stop", mapOf("reason" to "Fast mode removed no arrows in two rounds; refusing to guess"))
                            stoppedByTime = false; mask.release(); break
                        }
                    }
                    val sequence = fastSequence(board)
                    if (sequence.isEmpty()) {
                        event("stop", mapOf("reason" to "Only arrows covered by an app overlay are free; tap manually"))
                        stoppedByTime = false; mask.release(); break
                    }
                    event("fast-round", mapOf("remaining" to count, "taps" to sequence.size))
                    var nextAt = clock.monotonic()
                    sequence.forEachIndexed { index, (label, x, y) ->
                        val delay = nextAt - clock.monotonic()
                        if (delay > 0) clock.sleep(delay)
                        nextAt = clock.monotonic() + 0.3
                        val arrow = board.arrows.getValue(label)
                        val fields = mutableMapOf<String, Any?>("mode" to "fast", "index" to index, "x" to x, "y" to y,
                            "direction" to org.json.JSONArray(listOf(arrow.dx, arrow.dy)), "confidence" to kotlin.math.round(arrow.confidence * 1000) / 1000.0)
                        if (x != arrow.x || y != arrow.y) fields["head"] = org.json.JSONArray(listOf(arrow.x, arrow.y))
                        event("tap-arrow", fields)
                        device.tap(x, y)
                    }
                    lastCount = count
                    fastRoundCount = count
                    previousMask?.release(); previousMask = null
                    lastAction = clock.monotonic()
                    mask.release(); continue
                }
                val ready = board.blockers.filterValues { it.isEmpty() }.keys.mapNotNull { label -> tapPoint(board, label)?.let { label to it } }
                if (ready.isEmpty()) {
                    event("stop", mapOf("reason" to "Only arrows covered by an app overlay are free; tap manually"))
                    stoppedByTime = false; mask.release(); break
                }
                val label = ready.minBy { (id, _) -> labelCount(board.labels, id) }.first
                val arrow = board.arrows.getValue(label)
                val (x, y) = ready.first { it.first == label }.second
                val fields = mutableMapOf<String, Any?>("remaining" to count, "x" to x, "y" to y,
                    "direction" to org.json.JSONArray(listOf(arrow.dx, arrow.dy)), "confidence" to kotlin.math.round(arrow.confidence * 1000) / 1000.0)
                if (x != arrow.x || y != arrow.y) fields["head"] = org.json.JSONArray(listOf(arrow.x, arrow.y))
                event("tap-arrow", fields)
                device.tap(x, y)
                lastCount = count
                pending = x to y
                pendingMask?.release()
                pendingMask = labelMask(board.labels, label)
                pendingAfter?.release()
                pendingAfter = mask.clone().also { clearLabel(it, board.labels, label) }
                predicted?.labels?.release()
                predicted = predictRemoval(board, label)
                pendingSince = clock.monotonic()
                lastAction = clock.monotonic()
                mask.release()
                clock.sleep(options.delay)
                continue
            }
            if (options.dryRun) {
                event("dry-run", mapOf("reason" to board.reason))
                stoppedByTime = false; mask.release(); break
            }
            val moving = "Unrecognized strokes/animation" in board.reason || "touches the board crop" in board.reason
            if (moving && (pending != null || fastRoundCount != null) && clock.monotonic() - lastAction < 5) {
                mask.release(); clock.sleep(0.2); continue
            }
            val lines = reader.read(image)
            val text = lines.joinToString(" ") { it.text }
            if (options.reviveAds) {
                val resumed = AdWait(clock.monotonic())
                if (resumed.confirmEntry(lines, image.rows(), clock.monotonic())) {
                    adWait = resumed
                    event("ad-entered", mapOf("resumed" to true))
                    mask.release(); continue
                }
                reviveAction(image, lines)?.let { action ->
                    if (lastLevel == null) lines.forEach { line ->
                        if (line.y < 0.14 * image.rows()) Regex("关卡[:：]?(\\d+)").find(line.text)?.let { lastLevel = it.groupValues[1].toInt(); levelActive = true }
                    }
                    event("revive", mapOf("action" to action.reason, "x" to action.x, "y" to action.y))
                    device.tap(action.x, action.y)
                    if (action.reason == "revive-watch-ad") adWait = AdWait(clock.monotonic())
                    lastAction = clock.monotonic()
                    mask.release(); clock.sleep(1.0); continue
                }
            }
            val decision = streakAction(image, lines, options.streakPolicy)
            if (decision != null) {
                if (coinAttempted) {
                    if (clock.monotonic() - coinAttemptedAt >= 10) {
                        event("stop", mapOf("reason" to "Streak transaction did not leave dialog; no duplicate spending"))
                        stoppedByTime = false; mask.release(); break
                    }
                    mask.release(); clock.sleep(0.5); continue
                }
                val confirmation = device.screenshot()
                val confirmed = streakAction(confirmation, reader.read(confirmation), options.streakPolicy)
                confirmation.release()
                if (confirmed != decision) {
                    event("wait", mapOf("reason" to "Streak price/balance/dialog changed during confirmation"))
                    mask.release(); clock.sleep(0.5); continue
                }
                event("streak", mapOf("action" to decision.reason, "balance" to decision.balance, "cost" to decision.price, "x" to decision.x, "y" to decision.y))
                device.tap(decision.x, decision.y)
                coinAttempted = true
                coinAttemptedAt = clock.monotonic()
                lastAction = coinAttemptedAt
                mask.release(); clock.sleep(1.0); continue
            }
            if ("恢复您的连胜" in text && "残忍放弃" in text && "免费" !in text && "获得福利" !in text) {
                event("stop", mapOf("reason" to "Streak policy disabled or balance/price not confidently recognized", "visible_text" to text))
                stoppedByTime = false; mask.release(); break
            }
            val victoryWords = listOf("下一关", "恭喜通关", "通关成功", "挑战成功", "闯关成功")
            if (levelActive && !won && victoryWords.any { it in text }) {
                completed += 1
                won = true
                event("completed", mapOf("level" to lastLevel, "completed" to completed))
                Imgcodecs.imwrite(File(options.output, "level-$lastLevel-win.png").path, image)
                if (options.target != null && lastLevel != null && lastLevel!! >= options.target!!) {
                    event("stop", mapOf("reason" to "Target reached (completed level $lastLevel >= ${options.target})"))
                    stoppedByTime = false; mask.release(); break
                }
                if (options.target == null && options.levels > 0 && completed >= options.levels) {
                    event("stop", mapOf("reason" to "Requested number of wins reached"))
                    stoppedByTime = false; mask.release(); break
                }
            }
            val failureOffer = options.reviveAds && "继续游戏" in text && "恢复" in text
            var action = if (failureOffer) null else popupAction(image, lines, allowRestart = restarts < options.maxRestarts)
            val advance = setOf("下一关", "下一关卡", "继续挑战")
            if ("获得福利" in text) {
                nextLevelReadyAt = null
                if (action != null && action.reason in advance) action = null
            } else if (action != null && action.reason in advance) {
                val now = clock.monotonic()
                if (nextLevelReadyAt == null || now < nextLevelReadyAt!!) {
                    if (nextLevelReadyAt == null) {
                        nextLevelReadyAt = now + 1.5
                        event("wait-next", mapOf("seconds" to 1.5))
                    }
                    val wait = max(0.0, nextLevelReadyAt!! - clock.monotonic())
                    mask.release(); clock.sleep(wait); continue
                }
            }
            if (action != null) {
                event("popup", mapOf("action" to action.reason, "x" to action.x, "y" to action.y))
                device.tap(action.x, action.y)
                if (action.reason == "restart") {
                    restarts += 1
                    event("restart", mapOf("used" to restarts, "limit" to options.maxRestarts))
                    levelActive = false; won = false; lastCount = null; fastRoundCount = null; fastNoProgress = 0
                    lastHearts = null; pending = null; predicted = null
                }
                if (won && action.reason in advance) {
                    levelActive = false; won = false; lastCount = null; fastRoundCount = null; fastNoProgress = 0
                    lastHearts = null; pending = null; predicted = null; nextLevelReadyAt = null
                }
                lastAction = clock.monotonic()
                mask.release(); clock.sleep(1.0); continue
            }
            val idle = clock.monotonic() - lastAction
            if (idle >= options.idleTimeout) {
                val reason = "Idle timeout: no safe action for ${"%.1f".format(idle)}s; ${board.reason}"
                event("stop", mapOf("reason" to reason, "recognition_reason" to board.reason, "idle_seconds" to kotlin.math.round(idle * 10) / 10.0,
                    "timeout_seconds" to options.idleTimeout, "visible_text" to text))
                mask.release()
                throw RuntimeException(reason)
            }
            event("wait", mapOf("reason" to board.reason, "visible_text" to text))
            mask.release()
            clock.sleep(1.0)
        }
        if (stoppedByTime) event("stop", mapOf("reason" to "Time limit reached"))
    } finally {
        adScroller?.stop()
        pendingMask?.release(); pendingAfter?.release(); previousMask?.release()
        if (previousShot != null && previousShot !== predicted?.image) previousShot!!.release()
        events?.close()
    }
}

private fun annotateBoard(board: Board): Mat {
    val image = board.image.clone()
    board.arrows.forEach { (label, arrow) ->
        val color = if (board.blockers[label].isNullOrEmpty()) Scalar(0.0, 150.0, 0.0) else Scalar(0.0, 80.0, 240.0)
        Imgproc.arrowedLine(image, org.opencv.core.Point(arrow.x.toDouble(), arrow.y.toDouble()),
            org.opencv.core.Point((arrow.x + arrow.dx * 25).toDouble(), (arrow.y + arrow.dy * 25).toDouble()), color, 2)
        Imgproc.putText(image, label.toString(), org.opencv.core.Point((arrow.x + 6).toDouble(), (arrow.y - 6).toDouble()),
            Imgproc.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)
    }
    return image
}

private fun reportJson(board: Board): String {
    val heads = JSONObject()
    board.arrows.forEach { (label, arrow) ->
        heads.put(label.toString(), JSONObject().put("label", arrow.label).put("x", arrow.x).put("y", arrow.y)
            .put("dx", arrow.dx).put("dy", arrow.dy).put("confidence", arrow.confidence).put("scale", arrow.scale))
    }
    return JSONObject().put("valid", board.valid).put("reason", board.reason).put("arrows", board.arrows.size)
        .put("order", org.json.JSONArray(board.order)).put("ready", org.json.JSONArray(board.blockers.filterValues { it.isEmpty() }.keys.toList()))
        .put("heads", heads).toString(2)
}

private fun differenceCount(left: Mat, right: Mat): Int {
    var count = 0
    val rows = min(left.rows(), right.rows())
    val cols = min(left.cols(), right.cols())
    if (left.rows() != right.rows() || left.cols() != right.cols()) return Int.MAX_VALUE
    for (row in 0 until rows) for (col in 0 until cols) if (left.u8(row, col) != right.u8(row, col)) count += 1
    return count
}

private fun labelMask(labels: Mat, label: Int): Mat {
    val mask = Mat.zeros(labels.size(), CvType.CV_8U)
    for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) if (labels.get(row, col)[0].toInt() == label) mask.put(row, col, 255.0)
    return mask
}

private fun clearLabel(mask: Mat, labels: Mat, label: Int) {
    for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) if (labels.get(row, col)[0].toInt() == label) mask.put(row, col, 0.0)
}

private fun labelCount(labels: Mat, label: Int): Int {
    var count = 0
    for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) if (labels.get(row, col)[0].toInt() == label) count += 1
    return count
}
