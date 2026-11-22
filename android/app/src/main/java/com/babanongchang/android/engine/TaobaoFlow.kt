package com.babanongchang.android.engine

val TAOBAO_SEARCH_TASKS = listOf("搜一搜你喜欢的商品", "搜一搜你心仪的宝贝")

enum class TaobaoTaskOperation { SIGN_IN, SEARCH, SWIPE_BROWSE, STAY, COINS_STAY }

data class TaobaoTaskDefinition(val name: String, val operation: TaobaoTaskOperation)

val TAOBAO_TASKS = TAOBAO_SEARCH_TASKS.map { TaobaoTaskDefinition(it, TaobaoTaskOperation.SEARCH) } + listOf(
    TaobaoTaskDefinition("发现精选好物", TaobaoTaskOperation.SWIPE_BROWSE),
    TaobaoTaskDefinition("逛精选好物", TaobaoTaskOperation.SWIPE_BROWSE),
    TaobaoTaskDefinition("看严选推荐商品", TaobaoTaskOperation.STAY),
    TaobaoTaskDefinition("去淘金币", TaobaoTaskOperation.COINS_STAY),
)
val TAOBAO_SIGN_IN_TASK = TaobaoTaskDefinition("去签到", TaobaoTaskOperation.SIGN_IN)

fun findTaobaoFarmEntry(items: List<OcrText>) = TextHandle.findText(items, "芭芭农场")

fun isTaobaoFarmPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { "芭芭农场" in it && "免费领水果" in it } && texts.any { it == "施肥" }
}

fun isTaobaoFertilizerTasksPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { it == "做任务赚肥料" } && texts.any { "肥料明细" in it }
}

fun findTaobaoTaskAction(
    items: List<OcrText>,
    imageShape: Pair<Int, Int>,
    taskText: String,
    actionText: String = "去完成",
): OcrText? {
    val normalized = normalizeText(taskText)
    return TextHandle.findSameRowText(
        items, imageShape, { normalized in it.normalizedText }, listOf(actionText), RelativeRegion(left = 0.55),
    )
}

fun findAvailableTaobaoTask(items: List<OcrText>, imageShape: Pair<Int, Int>): Pair<TaobaoTaskDefinition, OcrText>? {
    val available = mutableListOf<Pair<TaobaoTaskDefinition, OcrText>>()
    TextHandle.findText(items, "去签到", exact = true)?.let { available += TAOBAO_SIGN_IN_TASK to it }
    TAOBAO_TASKS.forEach { task ->
        findTaobaoTaskAction(items, imageShape, task.name)?.let { available += task to it }
    }
    return available.minWithOrNull(compareBy({ it.second.center.second }, { it.second.center.first }))
}

fun isTaobaoSearchRewardPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { "搜索有福利" in it } && texts.any { "搜索后浏览立得奖励" in it }
}

fun findTaobaoRecommendedKeyword(items: List<OcrText>): OcrText? {
    val marker = items.filter { it.normalizedText == "搜索发现" }.maxByOrNull { it.score } ?: return null
    return items.filter {
        it.center.second > marker.center.second + 30 && it.center.second < marker.center.second + 140 &&
            it.center.first < 360 && "近一个月" !in it.normalizedText
    }.minWithOrNull(compareBy({ it.center.second }, { it.center.first }))
}

fun isTaobaoSearchResultsPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { "搜索有福利" in it } && texts.any { "滑动浏览得肥料" in it }
}

fun isTaobaoDiscoveryPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { it == "浏览得奖励" } && texts.any { "下单得肥料" in it }
}

fun isTaobaoRecommendedVideoPage(items: List<OcrText>): Boolean {
    val texts = items.map { it.normalizedText }
    return texts.any { "滑动浏览得" in it } && texts.any { it == "肥料" }
}

class TaobaoAutomation(
    val device: FarmDevice,
    val screen: TextHandle,
    val log: (String) -> Unit = {},
) {
    fun waitForFarmPageReady(timeout: Double = 30.0) = screen.waitForStableText(
        "集肥料", stableScans = 3, positionTolerance = 8,
        screenPredicate = { isTaobaoFarmPage(it.items) }, timeout = (timeout * 1000).toInt(), interval = 500,
        exact = true, error = "淘宝芭芭农场页面加载超时，未能稳定识别“集肥料”",
    )

    fun waitForFertilizerTasksAfterClick(timeout: Double = 15.0): Boolean {
        val deadline = screen.clock.monotonic() + timeout
        var leftFarmAt: Double? = null
        while (screen.clock.monotonic() < deadline) {
            val snapshot = screen.scan()
            if (isTaobaoFertilizerTasksPage(snapshot.items)) return true
            if (isTaobaoFarmPage(snapshot.items)) leftFarmAt = null
            else if (leftFarmAt == null) leftFarmAt = screen.clock.monotonic()
            else if (screen.clock.monotonic() - leftFarmAt >= 2) return false
            screen.clock.sleep(0.5)
        }
        return false
    }

    fun returnToFarmPage(timeout: Double = 20.0) {
        backUntil(device, screen, { isTaobaoFarmPage(it.items) }, timeout = (timeout * 1000).toInt(),
            clock = screen.clock, error = "进入错误页面后未能返回淘宝芭芭农场")
    }

    fun openFertilizerTasksFromFarm(maxAttempts: Int = 3) {
        for (attempt in 1..maxAttempts) {
            val entry = waitForFarmPageReady()
            log("第 $attempt 次点击“集肥料”")
            device.tap(entry.center)
            if (waitForFertilizerTasksAfterClick()) {
                log("已稳定进入淘宝肥料任务列表")
                return
            }
            log("点击后未进入任务列表，返回农场首页重试")
            returnToFarmPage()
        }
        throw AutomationError("多次点击“集肥料”后仍未进入任务列表")
    }

    fun waitAfterFarmEntryClick(timeout: Double = 30.0) {
        val destination = screen.waitForScreen({ snapshot ->
            when {
                isTaobaoFertilizerTasksPage(snapshot.items) -> "tasks"
                isTaobaoFarmPage(snapshot.items) -> "farm"
                else -> null
            }
        }, timeout = (timeout * 1000).toInt(), interval = 500, error = "点击淘宝首页“芭芭农场”后未进入农场页面")
        if (destination == "tasks") {
            log("已稳定进入淘宝肥料任务列表")
            return
        }
        openFertilizerTasksFromFarm()
    }

    fun ensureFertilizerTasksPage(timeout: Double = 60.0) {
        if (isTaobaoFertilizerTasksPage(screen.scan().items)) {
            log("检测到已在淘宝肥料任务列表")
            return
        }
        device.startActivity(HOME_ACTIVITY)
        log("已启动淘宝主页 Activity")
        val deadline = screen.clock.monotonic() + timeout
        var unknownSince = screen.clock.monotonic()
        while (screen.clock.monotonic() < deadline) {
            val snapshot = screen.scan()
            if (isTaobaoFertilizerTasksPage(snapshot.items)) {
                log("已稳定进入淘宝肥料任务列表")
                return
            }
            val now = screen.clock.monotonic()
            val onFarm = isTaobaoFarmPage(snapshot.items)
            if (onFarm) {
                openFertilizerTasksFromFarm()
                return
            }
            val entry = findTaobaoFarmEntry(snapshot.items)
            if (entry != null) {
                device.tap(entry.center)
                log("已点击淘宝首页“芭芭农场”")
                waitAfterFarmEntryClick()
                return
            }
            if (now - unknownSince >= 10) {
                device.back()
                log("当前页面无法识别，尝试返回以关闭遮挡页面")
                unknownSince = now
            }
            screen.clock.sleep(0.5)
        }
        throw AutomationError("未能从当前页面稳定进入淘宝肥料任务列表")
    }

    fun openSearchTask(taskName: String, button: OcrText, timeout: Double = 20.0) {
        log("开始执行“$taskName”")
        screen.tapAndWait(button.center, { if (isTaobaoSearchRewardPage(it.items)) it else null },
            timeout = (timeout * 1000).toInt(), interval = 500, error = "点击“$taskName”后未进入搜索奖励页面")
        log("已打开“$taskName”任务")
    }

    fun browseRecommendedSearchResult(durationSeconds: Double = 18.0, timeout: Double = 20.0) {
        val keyword = screen.waitForScreen({ findTaobaoRecommendedKeyword(it.items) },
            timeout = (timeout * 1000).toInt(), interval = 500, error = "搜索奖励页面未找到推荐关键词")
        log("点击推荐关键词：${keyword.text.trim()}")
        screen.tapAndWait(keyword.center, { if (isTaobaoSearchResultsPage(it.items)) it else null },
            timeout = (timeout * 1000).toInt(), interval = 500, error = "点击推荐关键词后未进入搜索结果列表")
        swipeBrowse(device, durationSeconds, screen.clock, log)
    }

    fun returnToFertilizerTasks(timeout: Double = 30.0) {
        val result = backUntil(device, screen, { isTaobaoFertilizerTasksPage(it.items) },
            timeout = (timeout * 1000).toInt(), clock = screen.clock, error = "多次返回后仍未回到淘宝肥料任务列表")
        log("已返回淘宝肥料任务列表，共返回 ${result.backCount} 次")
    }

    fun completeSupportedTasks() {
        var completed = 0
        while (true) {
            val snapshot = screen.scan()
            val found = findAvailableTaobaoTask(snapshot.items, snapshot.shape)
            if (found == null) {
                log("所有已接入任务均不可执行，今日任务已清空，共完成 $completed 次")
                return
            }
            val (task, button) = found
            when (task.operation) {
                TaobaoTaskOperation.SIGN_IN -> {
                    log("点击“去签到”")
                    screen.tapAndWait(button.center, { current ->
                        if (isTaobaoFertilizerTasksPage(current.items) &&
                            !TextHandle.hasText(current.items, "去签到", exact = true)
                        ) current else null
                    }, error = "签到后未确认任务列表中的“去签到”按钮消失")
                    completed += 1
                    continue
                }
                TaobaoTaskOperation.SEARCH -> {
                    openSearchTask(task.name, button)
                    browseRecommendedSearchResult()
                }
                TaobaoTaskOperation.SWIPE_BROWSE -> {
                    log("开始执行“${task.name}”")
                    screen.tapAndWait(button.center, { if (isTaobaoDiscoveryPage(it.items)) it else null },
                        timeout = 20_000, interval = 500, error = "点击“${task.name}”后未进入商品浏览页面")
                    swipeBrowse(device, 18.0, screen.clock, log)
                }
                TaobaoTaskOperation.COINS_STAY -> {
                    log("开始执行“${task.name}”")
                    device.tap(button.center)
                    log("已点击“去淘金币”，等待 3 秒自动跳转")
                    screen.clock.sleep(3.0)
                    log("淘金币页面停留 8 秒")
                    screen.clock.sleep(8.0)
                }
                TaobaoTaskOperation.STAY -> {
                    log("开始执行“看严选推荐商品”")
                    screen.tapAndWait(button.center, { if (isTaobaoRecommendedVideoPage(it.items)) it else null },
                        timeout = 20_000, interval = 500, error = "点击“看严选推荐商品”后未进入视频页面")
                    log("视频页面停留 18 秒")
                    screen.clock.sleep(18.0)
                }
            }
            returnToFertilizerTasks()
            completed += 1
        }
    }

    fun run() {
        ensureFertilizerTasksPage()
        completeSupportedTasks()
    }

    companion object {
        const val PACKAGE = "com.taobao.taobao"
        const val HOME_ACTIVITY = "$PACKAGE/com.taobao.tao.welcome.Welcome"
    }
}

fun runFarm(
    module: String,
    options: FarmOptions,
    device: FarmDevice,
    ocr: OcrEngine,
    config: ProjectConfig,
    clock: Clock,
    log: (String) -> Unit,
) {
    if (module !in FARM_MODULES) throw IllegalArgumentException("未知农场功能：$module")
    fun screen(minScore: Double = 0.75) = TextHandle(device, ocr, minScore, config, clock)
    fun runTaobao() = TaobaoAutomation(device, screen(options.taobaoMinScore), log).run()
    when (module) {
        "taobao" -> runTaobao()
        "fertilize" -> FarmAutomation(device, screen(), options.threshold, options.browseSeconds, log).run(options.maxClicks)
        "goods" -> GoodsAutomation(device, screen(), options.browseSeconds, log).run()
        "tasks" -> TaskAutomation(device, screen(), options.browseSeconds, log).run()
        else -> {
            val completed = mutableSetOf<String>()
            while (true) {
                val installed = device.installedPackages()
                when {
                    ALIPAY_PACKAGE in installed && ALIPAY_PACKAGE !in completed -> {
                        AlipayAutomation(device, screen(), options.threshold, options.browseSeconds, log).run(options.maxClicks)
                        completed += ALIPAY_PACKAGE
                    }
                    TaobaoAutomation.PACKAGE in installed && TaobaoAutomation.PACKAGE !in completed -> {
                        runTaobao()
                        completed += TaobaoAutomation.PACKAGE
                    }
                    else -> {
                        log(if (completed.isEmpty()) "未安装支付宝或淘宝，流程结束" else "所有已安装应用的芭芭农场流程已完成")
                        return
                    }
                }
            }
        }
    }
}
