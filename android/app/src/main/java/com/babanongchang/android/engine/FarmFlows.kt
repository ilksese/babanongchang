package com.babanongchang.android.engine

const val ALIPAY_PACKAGE = "com.eg.android.AlipayGphone"
const val ALIPAY_HOME_ACTIVITY = "$ALIPAY_PACKAGE/com.alipay.mobile.quinox.LauncherActivity"
val TASK_DIALOG_TITLES = listOf("做任务集肥料", "做任务领肥料")

enum class TaskOperation(val value: String) { SWIPE_BROWSE("swipe_browse"), CLICK_AND_RETURN("click_and_return") }

data class TaskMatcher(val fixedText: String? = null, val pattern: String? = null) {
    private val regex = pattern?.let { Regex(it) }
    init {
        require((fixedText == null) != (pattern == null)) { "任务匹配器必须且只能配置 fixed_text 或 pattern" }
    }
    fun matches(text: String): Boolean {
        val normalized = normalizeText(text)
        return if (fixedText != null) normalizeText(fixedText) in normalized else regex!!.containsMatchIn(normalized)
    }
}

data class TaskDefinition(
    val key: String,
    val name: String,
    val operation: TaskOperation,
    val matchers: List<TaskMatcher>,
    val actionLabels: List<String> = listOf("去完成"),
    val durationSeconds: Double = 18.0,
    val staySeconds: Double = 0.0,
    val enabled: Boolean = true,
) {
    init {
        require(matchers.isNotEmpty()) { "任务必须至少配置一个匹配器" }
        require(durationSeconds > 0) { "任务时长必须大于 0" }
        require(staySeconds >= 0) { "任务停留时间不能小于 0" }
    }
    fun matches(text: String) = matchers.any { it.matches(text) }
}

val TASK_POOL = listOf(
    TaskDefinition("browse-goods", "逛好物浏览任务", TaskOperation.SWIPE_BROWSE,
        listOf(TaskMatcher(pattern = "逛(?:好物|一逛)(?:最高得|立得)\\d+肥料?")),
        listOf("去完成", "去逛逛")),
    TaskDefinition("browse-selected-goods", "看精选商品得肥料", TaskOperation.SWIPE_BROWSE,
        listOf(TaskMatcher(fixedText = "看精选商品得肥料")), listOf("去完成", "去逛逛")),
    TaskDefinition("browse-local-flavors", "逛乡土寻味专场得肥料", TaskOperation.SWIPE_BROWSE,
        listOf(TaskMatcher(fixedText = "逛乡土寻味专场得肥料")), listOf("去完成", "去逛逛")),
    TaskDefinition("visit-alipay-for-beans", "逛支付宝得金豆", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛支付宝得金豆"))),
    TaskDefinition("visit-alipay-beans-for-treasure", "逛支付宝金豆得宝", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛支付宝金豆得宝"))),
    TaskDefinition("visit-ant-manor", "逛一逛蚂蚁庄园", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛一逛蚂蚁庄园"))),
    TaskDefinition("visit-forest-team-planting", "逛一逛森林组队种", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛一逛森林组队种"))),
    TaskDefinition("visit-alipay-member", "逛一逛支付宝会员", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛一逛支付宝会员")), listOf("去完成", "去逛逛")),
    TaskDefinition("visit-bean-park", "逛一逛金豆乐园", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(fixedText = "逛一逛金豆乐园"))),
    TaskDefinition("play-my-game", "玩一玩…", TaskOperation.CLICK_AND_RETURN,
        listOf(TaskMatcher(pattern = "^玩一玩.*")), staySeconds = 600.0),
).filter { it.enabled }

fun parseFertilizer(items: List<OcrText>, imageShape: Pair<Int, Int>): Int? {
    val (height, width) = imageShape
    val candidates = items.mapNotNull { item ->
        val (x, y) = item.center
        if (x <= 0.2 * width || x >= 0.8 * width || y <= 0.55 * height || y >= 0.85 * height) return@mapNotNull null
        Regex("肥料[：:]?(\\d+)$").find(item.normalizedText)?.let { item.score to it.groupValues[1].toInt() }
    }
    if (candidates.isNotEmpty()) return candidates.maxBy { it.first }.second
    val labels = items.filter { "肥料" in it.text }
    val numbers = items.filter { Regex("\\d+").matches(it.text.trim()) }
    for (label in labels) {
        val (labelX, labelY) = label.center
        if (labelX <= 0.2 * width || labelX >= 0.8 * width || labelY <= 0.55 * height || labelY >= 0.85 * height) continue
        val nearby = numbers.filter {
            val dx = it.center.first - labelX
            dx > 0 && dx < 0.3 * width && kotlin.math.abs(it.center.second - labelY) < 0.035 * height
        }
        if (nearby.isNotEmpty()) return nearby.minBy { it.center.first - labelX }.text.trim().toInt()
    }
    return null
}

fun findGoodsEntry(items: List<OcrText>, imageShape: Pair<Int, Int>): OcrText? {
    val region = RelativeRegion(left = 0.0, top = 0.12, right = 0.22, bottom = 0.35)
    return listOf("逛农货", "百县百品").flatMap { TextHandle.findTexts(items, it, region = region, imageShape = imageShape) }
        .maxByOrNull { it.score }
}

fun hasTaskDialog(items: List<OcrText>) = items.any { item ->
    TASK_DIALOG_TITLES.any { normalizeText(it) in item.normalizedText }
}

fun findFertilizerEntry(items: List<OcrText>, imageShape: Pair<Int, Int>) = TextHandle.findText(
    items, "领肥料", region = RelativeRegion(left = 0.55, top = 0.55), imageShape = imageShape,
)

fun findTaskAction(
    items: List<OcrText>,
    imageShape: Pair<Int, Int>,
    task: TaskDefinition,
    actions: List<String>? = null,
): OcrText? = TextHandle.findSameRowText(
    items, imageShape, { task.matches(it.text) }, actions ?: task.actionLabels, RelativeRegion(left = 0.55),
)

fun describeRecognizedTasks(items: List<OcrText>, imageShape: Pair<Int, Int>): List<String> = TASK_POOL.mapNotNull { task ->
    val title = items.filter { task.matches(it.text) }.maxByOrNull { it.score } ?: return@mapNotNull null
    val button = findTaskAction(items, imageShape, task, task.actionLabels + "领取")
    val buttonText = button?.text?.trim() ?: "无可执行按钮"
    "${title.text.trim()} -> ${task.operation.value} [$buttonText]"
}

open class AlipayFlow(
    val device: FarmDevice,
    val screen: TextHandle,
    val browseSeconds: Double = 18.0,
    val log: (String) -> Unit = {},
) {
    fun browseForReward(durationSeconds: Double? = null) {
        swipeBrowse(device, durationSeconds ?: browseSeconds, screen.clock, log)
    }
}

class FarmAutomation(
    device: FarmDevice,
    screen: TextHandle,
    val threshold: Int = 600,
    browseSeconds: Double = 18.0,
    log: (String) -> Unit = {},
) : AlipayFlow(device, screen, browseSeconds, log) {
    fun waitForFarm(timeout: Double = 15.0): Pair<Int, OcrText> = screen.waitForScreen({ snapshot ->
        val balance = parseFertilizer(snapshot.items, snapshot.shape)
        val fertilize = TextHandle.findText(snapshot.items, "施肥", exact = true)
        if (balance != null && fertilize != null) balance to fertilize else null
    }, timeout = (timeout * 1000).toInt(), interval = 600, error = "未识别到施肥页面的“施肥”和肥料余额，已停止以避免误点")

    fun maybeClaimReward(): Boolean {
        val claim = try {
            screen.waitForText("立即领肥", timeout = 5000)
        } catch (_: WaitTimeoutError) {
            return false
        }
        log("发现“立即领肥”，开始领取浏览奖励")
        device.tap(claim)
        screen.clickText("立即领取")
        val browse = waitForBrowseOrFarm()
        if (browse == null) {
            log("本轮未出现“逛一逛”，已回到施肥页，继续施肥")
            return true
        }
        device.tap(browse.center)
        screen.waitForText("浏览或查看商品领肥料", timeout = 20_000)
        browseForReward()
        device.back()
        waitForFarm(20.0)
        log("已返回施肥页面")
        return true
    }

    fun waitForBrowseOrFarm(timeout: Double = 12.0): OcrText? {
        val found = screen.waitForScreen({ snapshot ->
            val browse = TextHandle.findText(snapshot.items, "逛一逛")
            if (browse != null) true to browse else {
                val balance = parseFertilizer(snapshot.items, snapshot.shape)
                val fertilize = TextHandle.findText(snapshot.items, "施肥", exact = true)
                if (balance != null && fertilize != null) true to null else null
            }
        }, timeout = (timeout * 1000).toInt(), interval = 600, error = "领取后既未出现“逛一逛”，也未返回施肥页")
        return found.second
    }

    fun run(maxClicks: Int? = null) {
        var clicks = 0
        while (maxClicks == null || clicks < maxClicks) {
            val (balance, fertilize) = waitForFarm()
            log("识别到肥料余额：$balance")
            if (balance <= threshold) {
                log("肥料余额不大于 $threshold，施肥结束")
                return
            }
            device.tap(fertilize.center)
            clicks += 1
            log("已点击施肥（第 $clicks 次）")
            screen.clock.sleep(1.2)
            maybeClaimReward()
        }
        log("已达到本次限制的 $maxClicks 次点击，停止运行")
    }
}

class GoodsAutomation(
    device: FarmDevice,
    screen: TextHandle,
    browseSeconds: Double = 18.0,
    log: (String) -> Unit = {},
) : AlipayFlow(device, screen, browseSeconds, log) {
    fun waitForHomeEntry(timeout: Double = 15.0) = screen.waitForScreen(
        { findGoodsEntry(it.items, it.shape) },
        timeout = (timeout * 1000).toInt(), interval = 600, error = "未识别到首页的“逛农货/百县百品”入口",
    )

    fun waitForGoodsPage(timeout: Double = 15.0) {
        screen.waitForStableScreen({ snapshot ->
            findGoodsEntry(snapshot.items, snapshot.shape) == null &&
                TextHandle.findText(snapshot.items, "施肥", exact = true) == null &&
                snapshot.items.size >= 3
        }, stableScans = 2, timeout = (timeout * 1000).toInt(), interval = 500,
            error = "点击入口后未确认进入“逛农货/百县百品”二级页面")
    }

    fun run() {
        val entry = waitForHomeEntry()
        log("识别到首页入口：${entry.text}")
        device.tap(entry.center)
        waitForGoodsPage()
        log("已进入逛农货/百县百品二级页面")
        browseForReward()
        device.back()
        waitForHomeEntry(20.0)
        log("已返回芭芭农场首页，本日任务完成")
    }
}

class TaskAutomation(
    device: FarmDevice,
    screen: TextHandle,
    browseSeconds: Double = 18.0,
    log: (String) -> Unit = {},
) : AlipayFlow(device, screen, browseSeconds, log) {
    fun waitForTaskDialog(timeout: Double = 15.0) {
        screen.waitForStableScreen({ hasTaskDialog(it.items) }, stableScans = 2,
            timeout = (timeout * 1000).toInt(), interval = 500, error = "等待“做任务领肥料”弹窗超时")
    }

    fun waitForTaskListStable(timeout: Double = 20.0) {
        screen.waitForStableScreen({ hasTaskDialog(it.items) }, stableScans = 2,
            signature = { taskListSignature(it.items) }, timeout = (timeout * 1000).toInt(), interval = 600,
            error = "任务列表刷新后未能稳定，已停止以避免误点")
    }

    fun openTaskDialog() {
        val deadline = screen.clock.monotonic() + 15
        while (screen.clock.monotonic() < deadline) {
            val snapshot = screen.scan()
            if (hasTaskDialog(snapshot.items)) {
                waitForTaskListStable()
                log("检测到已在“做任务集肥料”任务列表")
                return
            }
            val entry = findFertilizerEntry(snapshot.items, snapshot.shape)
            if (entry != null) {
                device.tap(entry.center)
                waitForTaskDialog()
                waitForTaskListStable()
                log("已打开“做任务领肥料”弹窗")
                return
            }
            screen.clock.sleep(0.6)
        }
        throw AutomationError("未识别到屏幕右下方的“领肥料”按钮")
    }

    fun returnToFarm(timeout: Double = 20.0) {
        fun isFarm(snapshot: ScreenSnapshot) = !hasTaskDialog(snapshot.items) &&
            parseFertilizer(snapshot.items, snapshot.shape) != null &&
            TextHandle.hasText(snapshot.items, "施肥", exact = true)
        val snapshot = screen.scan()
        if (!isFarm(snapshot)) {
            val title = TASK_DIALOG_TITLES.firstNotNullOfOrNull { TextHandle.findText(snapshot.items, it) }
                ?: throw AutomationError("未识别到任务弹窗或农场首页，停止关闭弹窗以避免误点")
            val (height, width) = snapshot.shape
            val maskTop = (height * 0.12).toInt()
            val maskBottom = (title.top - height * 0.06).toInt()
            if (maskBottom <= maskTop) throw AutomationError("任务弹窗上方没有可确认的遮罩区域，已停止以避免误点")
            screen.tapAndWait(width / 2 to (maskTop + maskBottom) / 2, { if (isFarm(it)) it else null },
                timeout = (timeout * 1000).toInt(), interval = 600,
                error = "点击遮罩后任务弹窗未关闭或未回到农场首页，已停止且不发送返回键")
        }
        screen.waitForStableScreen(::isFarm, stableScans = 2, timeout = (timeout * 1000).toInt(), interval = 600,
            error = "任务结束后芭芭农场首页未能稳定")
        log("已关闭任务弹窗并返回芭芭农场首页")
    }

    fun scrollTaskList(towardBottom: Boolean = true) {
        val image = device.screenshot()
        val startY = (image.height * if (towardBottom) 0.76 else 0.38).toInt()
        val endY = (image.height * if (towardBottom) 0.38 else 0.76).toInt()
        device.swipe(image.width / 2 to startY, image.width / 2 to endY, 650)
        screen.clock.sleep(0.8)
    }

    fun resetTaskList() { repeat(8) { scrollTaskList(towardBottom = false) } }

    fun taskListSignature(items: List<OcrText>): List<String> {
        val labels = TASK_POOL.flatMap { it.actionLabels + "领取" }.toSet()
        return items.map { it.normalizedText }.filterIndexed { index, text ->
            TASK_POOL.any { it.matches(items[index].text) } || labels.any { label -> label in text }
        }.sorted()
    }

    fun findActionInList(
        tasks: List<TaskDefinition> = TASK_POOL,
        actions: List<String>? = null,
        maxScrolls: Int = 10,
    ): Pair<TaskDefinition, OcrText>? {
        val current = screen.scan()
        logRecognized(current.items, current.shape, null)
        tasks.forEach { task ->
            findTaskAction(current.items, current.shape, task, actions)?.let { return task to it }
        }
        resetTaskList()
        var previous: List<String>? = null
        var unchanged = 0
        for (page in 0..maxScrolls) {
            val snapshot = screen.scan()
            logRecognized(snapshot.items, snapshot.shape, page + 1)
            tasks.forEach { task ->
                findTaskAction(snapshot.items, snapshot.shape, task, actions)?.let { return task to it }
            }
            val signature = TextHandle.screenSignature(snapshot.items)
            unchanged = if (signature == previous) unchanged + 1 else 0
            if (page == maxScrolls || unchanged >= 1) return null
            previous = signature
            scrollTaskList()
        }
        return null
    }

    private fun logRecognized(items: List<OcrText>, shape: Pair<Int, Int>, page: Int?) {
        val descriptions = describeRecognizedTasks(items, shape)
        val location = if (page == null) "当前屏幕" else "第 $page 屏"
        if (descriptions.isEmpty()) log("任务识别（$location）：未命中任务池") else {
            log("任务识别（$location）：")
            descriptions.forEach { log("  - $it") }
        }
    }

    fun waitForTaskTargetPage(timeout: Double = 20.0) {
        screen.waitForStableScreen({ snapshot ->
            TASK_DIALOG_TITLES.none { TextHandle.hasText(snapshot.items, it) } && snapshot.items.size >= 3
        }, stableScans = 2, timeout = (timeout * 1000).toInt(), interval = 500, error = "点击任务按钮后未确认进入目标页面")
    }

    fun waitForTaskListDeparture(timeout: Double = 10.0) {
        screen.waitForStableScreen({ !hasTaskDialog(it.items) }, stableScans = 1,
            timeout = (timeout * 1000).toInt(), interval = 100, error = "点击任务按钮后未离开任务列表")
    }

    fun claimReward(task: TaskDefinition) {
        val button = if (task.operation == TaskOperation.CLICK_AND_RETURN) {
            findActionInList(listOf(task), listOf("领取"))?.second
                ?: throw AutomationError("返回任务列表后未找到“${task.name}”的领取按钮")
        } else {
            val snapshot = screen.scan()
            findTaskAction(snapshot.items, snapshot.shape, task, listOf("领取"))
        }
        if (button == null) {
            log("“${task.name}”已自动发放奖励或刷新，无需点击领取")
            return
        }
        device.tap(button.center)
        log("已领取“${task.name}”奖励")
        screen.clock.sleep(1.2)
        waitForTaskDialog()
        waitForTaskListStable()
    }

    fun executeTask(task: TaskDefinition, button: OcrText) {
        log("开始执行“${task.name}”")
        when (task.operation) {
            TaskOperation.SWIPE_BROWSE -> {
                device.tap(button.center)
                waitForTaskTargetPage()
                val iteration = findBrowseIteration(screen.scan().texts)
                var duration = task.durationSeconds
                if (iteration != null) {
                    duration *= iteration
                    log("识别到“第 $iteration 次”，本轮浏览 ${formatG(duration)} 秒")
                }
                browseForReward(duration)
            }
            TaskOperation.CLICK_AND_RETURN -> {
                device.tap(button.center)
                waitForTaskListDeparture()
                if (task.staySeconds != 0.0) {
                    waitForTaskTargetPage()
                    log("任务页面停留 ${formatG(task.staySeconds)} 秒后返回")
                    screen.clock.sleep(task.staySeconds)
                }
            }
        }
        device.back()
        waitForTaskDialog(20.0)
        waitForTaskListStable(20.0)
        claimReward(task)
    }

    fun run() {
        openTaskDialog()
        var completed = 0
        while (true) {
            val found = findActionInList()
            if (found == null) {
                log("任务池中已无可执行任务，共完成 $completed 次")
                return
            }
            executeTask(found.first, found.second)
            completed += 1
        }
    }
}

class AlipayAutomation(
    device: FarmDevice,
    screen: TextHandle,
    val threshold: Int = 600,
    browseSeconds: Double = 18.0,
    log: (String) -> Unit = {},
) : AlipayFlow(device, screen, browseSeconds, log) {
    val tasks = TaskAutomation(device, screen, browseSeconds, log)

    fun isHome(snapshot: ScreenSnapshot): Boolean {
        fun hasLabel(text: String, region: RelativeRegion) =
            TextHandle.findText(snapshot.items, text, exact = true, region = region, imageShape = snapshot.shape) != null
        val top = RelativeRegion(0.0, 0.08, 1.0, 0.25)
        val bottom = RelativeRegion(0.0, 0.8, 1.0, 1.0)
        val actions = listOf("扫一扫", "收付款", "付钱/收钱").count { hasLabel(it, top) }
        val navigation = listOf("理财", "消息", "我的").count { hasLabel(it, bottom) }
        return (hasLabel("首页", bottom) && actions >= 1) || (actions >= 2 && navigation >= 2)
    }

    fun isFarm(snapshot: ScreenSnapshot) = !hasTaskDialog(snapshot.items) &&
        parseFertilizer(snapshot.items, snapshot.shape) != null &&
        TextHandle.hasText(snapshot.items, "施肥", exact = true)

    fun ensureFarmPage(timeout: Double = 60.0) {
        device.startActivity(ALIPAY_HOME_ACTIVITY)
        log("已启动支付宝，正在查找芭芭农场")
        val deadline = screen.clock.monotonic() + timeout
        while (screen.clock.monotonic() < deadline) {
            val snapshot = screen.scan()
            if (isFarm(snapshot)) {
                screen.waitForStableScreen(::isFarm, timeout = 20_000, interval = 500, error = "支付宝芭芭农场首页未能稳定")
                return
            }
            if (hasTaskDialog(snapshot.items)) {
                tasks.waitForTaskListStable()
                return
            }
            if (isHome(snapshot)) {
                val entry = screen.waitForStableText("芭芭农场", exact = true, screenPredicate = ::isHome,
                    timeout = 20_000, interval = 500, error = "支付宝首页未找到稳定的“芭芭农场”入口")
                screen.tapAndWait(entry.center, { if (isFarm(it)) it else null }, timeout = 30_000, interval = 500,
                    error = "点击支付宝首页“芭芭农场”后未进入农场首页")
                screen.waitForStableScreen(::isFarm, timeout = 20_000, interval = 500, error = "支付宝芭芭农场首页未能稳定")
                log("已从支付宝首页进入芭芭农场")
                return
            }
            screen.clock.sleep(0.5)
        }
        throw AutomationError("未能识别支付宝首页或芭芭农场，已停止且未发送返回键；请确认已登录并打开支付宝首页")
    }

    fun run(maxClicks: Int? = null) {
        ensureFarmPage()
        log("开始支付宝流程：做任务领肥料 → 逛农货 → 施肥")
        tasks.run()
        tasks.returnToFarm()
        GoodsAutomation(device, screen, browseSeconds, log).run()
        FarmAutomation(device, screen, threshold, browseSeconds, log).run(maxClicks)
        log("支付宝流程已完成")
    }
}
