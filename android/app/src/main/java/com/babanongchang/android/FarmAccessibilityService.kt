package com.babanongchang.android

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Path
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.view.Display
import android.view.Gravity
import android.view.MotionEvent
import android.view.ViewConfiguration
import android.widget.TextView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.FrameLayout
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager
import android.view.accessibility.AccessibilityWindowInfo

class FarmAccessibilityService : AccessibilityService(), SingleFertilizationPlatform {
    companion object {
        const val ALIPAY_PACKAGE = "com.eg.android.AlipayGphone"
        var connected: FarmAccessibilityService? = null
            private set
        var lastMessage: String? = null
            private set
        var overlayFailure: String? = null
            private set
    }

    private val handler = Handler(Looper.getMainLooper())
    private val run = SingleFertilizationRun(this)
    private val countdown = StartCountdown(SystemClock::elapsedRealtime) { delay, action -> handler.postDelayed(action, delay) }
    private var countdownNumber: TextView? = null
    val cliRun = CliAutomationRun(this)
    private var cliModule = "all"
    private var cliOptions = ""
    private var overlay: View? = null
    private var ballX: Int? = null
    private var ballY: Int? = null
    private var singleControls = false
    private var panelOpen = false
    private var alive = false
    private var recognizing = false
    private var lastScreenshotMillis = -500L
    private val cliHeldKeys = mutableSetOf<Int>()
    private var screenWakeLock: PowerManager.WakeLock? = null

    @Suppress("DEPRECATION") // Tasks operate in other apps, so an Activity window flag cannot keep them awake.
    fun keepTaskScreenOn(enabled: Boolean) {
        if (enabled && alive) {
            val wake = screenWakeLock ?: getSystemService(PowerManager::class.java).newWakeLock(
                PowerManager.SCREEN_BRIGHT_WAKE_LOCK, "babanongchang:task-screen",
            ).also { screenWakeLock = it }
            if (!wake.isHeld) wake.acquire()
        } else {
            screenWakeLock?.let { if (it.isHeld) it.release() }
        }
    }

    override fun onServiceConnected() {
        alive = true
        connected = this
        showControls()
    }

    fun showControls() {
        if (countdown.active) return
        if (!run.view.running && !run.view.paused) showCliControls()
    }

    fun configureCli(module: String, options: String): Boolean {
        if (countdown.active || cliRun.busy || run.view.running || run.view.paused) return false
        cliModule = module
        cliOptions = options
        showCliControls()
        return true
    }

    fun showSingleAttempt() {
        if (!countdown.active && !cliRun.busy) show(run.view)
    }

    fun hideControls() = removeOverlay()

    fun showCliControls() {
        singleControls = false
        showBall()
    }

    @android.annotation.SuppressLint("ClickableViewAccessibility") // Touch-up delegates to performClick for accessibility.
    private fun showBall() {
        removeOverlay()
        panelOpen = false
        if (!alive) return
        val size = FarmUi.dp(this, 60)
        val ball = FrameLayout(this).apply {
            background = FarmUi.shape(Color.argb(230, 54, 62, 58), size / 2f)
            elevation = FarmUi.dp(this@FarmAccessibilityService, 6).toFloat()
            contentDescription = "农场小白球，点击展开功能面板，可拖动位置"
            isFocusable = true
            isClickable = true
            stateDescription = "已收起"
        }
        ball.addView(View(this).apply {
            background = FarmUi.shape(Color.rgb(210, 216, 211), size / 2f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, FrameLayout.LayoutParams(FarmUi.dp(this, 42), FarmUi.dp(this, 42), Gravity.CENTER))
        ball.addView(View(this).apply {
            background = FarmUi.shape(Color.WHITE, size / 2f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, FrameLayout.LayoutParams(FarmUi.dp(this, 30), FarmUi.dp(this, 30), Gravity.CENTER))
        ball.setOnClickListener { showPanel() }
        var downX = 0f
        var downY = 0f
        var originX = 0
        var originY = 0
        var dragging = false
        ball.setOnTouchListener { view, event ->
            val params = view.layoutParams as? WindowManager.LayoutParams ?: return@setOnTouchListener false
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX; downY = event.rawY
                    originX = params.x; originY = params.y; dragging = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX
                    val dy = event.rawY - downY
                    if (kotlin.math.hypot(dx, dy) > ViewConfiguration.get(this).scaledTouchSlop) dragging = true
                    if (dragging) {
                        val bounds = overlayBounds(size, size)
                        params.x = (originX + dx.toInt()).coerceIn(bounds.left, bounds.right)
                        params.y = (originY + dy.toInt()).coerceIn(bounds.top, bounds.bottom)
                        updateOverlay(view, params)
                    }
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    if (dragging) {
                        val bounds = overlayBounds(size, size)
                        params.x = if (params.x < (bounds.left + bounds.right) / 2) bounds.left else bounds.right
                        ballX = params.x; ballY = params.y
                        updateOverlay(view, params)
                    } else if (event.actionMasked == MotionEvent.ACTION_UP) view.performClick()
                    true
                }
                else -> false
            }
        }
        attachOverlay(ball, size, size)
    }

    private fun showPanel() {
        removeOverlay()
        panelOpen = true
        if (!alive) return
        val layout = FarmUi.column(this, 16).apply {
            background = FarmUi.shape(Color.WHITE, FarmUi.dp(this@FarmAccessibilityService, 24).toFloat(), FarmUi.border)
        }
        fun text(value: String, size: Float = 15f, bold: Boolean = false) {
            layout.addView(FarmUi.text(this, value, size, bold = bold))
        }
        fun button(title: String, style: FarmUi.ButtonStyle = FarmUi.ButtonStyle.SECONDARY, action: () -> Unit) {
            layout.addView(FarmUi.button(this, title, style, action))
        }
        text(if (singleControls) "单次施肥验证" else "农场小助手", 22f, true)
        if (singleControls) {
            text(run.view.message)
            button(if (run.view.paused) "继续验证" else "开始单次施肥验证", FarmUi.ButtonStyle.PRIMARY) {
                if (run.view.paused) run.resume() else beginCountdown { run.start() }
            }
            if (run.view.paused) button("结束验证", FarmUi.ButtonStyle.DANGER) { run.end() }
            else button("返回功能选择") { singleControls = false; showPanel() }
        } else {
            val preferences = getSharedPreferences("cli", MODE_PRIVATE)
            var index = preferences.getInt("feature", 0).coerceIn(FarmFeatures.titles.indices)
            text(when {
                cliRun.paused -> "已暂停 · 可以继续或结束"
                cliRun.busy -> "正在运行，可暂停或结束。"
                else -> "选择功能，准备好后再开始。"
            })
            when {
                cliRun.paused -> {
                    button("继续运行", FarmUi.ButtonStyle.PRIMARY) { cliRun.resume() }
                    button("结束运行", FarmUi.ButtonStyle.DANGER) { cliRun.end() }
                }
                cliRun.busy -> {
                    button("暂停运行", FarmUi.ButtonStyle.PRIMARY) { cliRun.pause() }
                    button("结束运行", FarmUi.ButtonStyle.DANGER) { cliRun.end() }
                }
                else -> {
                    val selected = FarmUi.button(this, "切换功能：${FarmFeatures.titles[index]}") { }
                    FarmUi.arrow(selected, expanded = false)
                    selected.stateDescription = "已收起"
                    selected.setOnClickListener {
                        val choices = FarmUi.column(this, 0)
                        FarmFeatures.titles.forEachIndexed { i, title ->
                            val choice = FarmUi.choice(this, title) {
                                index = i
                                cliModule = FarmFeatures.module(i)
                                cliOptions = FeatureSettings.options(preferences, i)
                                preferences.edit().putInt("feature", i).apply()
                                showPanel()
                            }.apply { isChecked = i == index }
                            choices.addView(FarmUi.feature(this, i, choice))
                        }
                        layout.removeView(selected)
                        layout.addView(choices, 2)
                    }
                    layout.addView(selected)
                    text(if (index == 0) "将打开支付宝与淘宝。" else "请先进入对应农场或游戏页面。")
                    button("开始${FarmFeatures.titles[index]}", FarmUi.ButtonStyle.PRIMARY) {
                        cliModule = FarmFeatures.module(index)
                        cliOptions = FeatureSettings.options(preferences, index)
                        val module = cliModule
                        val options = cliOptions
                        beginCountdown { cliRun.start(module, options) }
                    }
                }
            }
            text("音量上暂停 · 音量下结束\n运行时小白球隐藏，暂停后重新出现。", 14f)
        }
        button("收起面板") { showBall() }
        button("移到另一侧") {
            val size = FarmUi.dp(this, 60)
            val bounds = overlayBounds(size, size)
            ballX = if ((ballX ?: bounds.right) > (bounds.left + bounds.right) / 2) bounds.left else bounds.right
            showBall()
        }
        val metrics = getSystemService(WindowManager::class.java).currentWindowMetrics
        val safe = metrics.windowInsets.getInsetsIgnoringVisibility(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
        val width = minOf(FarmUi.dp(this, 320), metrics.bounds.width() - safe.left - safe.right - FarmUi.dp(this, 16))
        val scroll = ScrollView(this).apply {
            addView(layout)
            isFillViewport = false
            setOnTouchListener { _, event ->
                if (event.actionMasked == MotionEvent.ACTION_OUTSIDE) { showBall(); true } else false
            }
        }
        val maxHeight = metrics.bounds.height() - safe.top - safe.bottom - FarmUi.dp(this, 24)
        scroll.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(maxHeight, View.MeasureSpec.AT_MOST))
        attachOverlay(scroll, width, scroll.measuredHeight.coerceAtMost(maxHeight))
    }

    private fun beginCountdown(action: () -> Unit) {
        if (!alive || countdown.active || cliRun.busy || run.view.running || run.view.paused) return
        removeOverlay()
        renderCountdown()
        if (overlay == null) return
        countdown.start(onTick = { seconds ->
            countdownNumber?.apply {
                text = seconds.toString()
                contentDescription = "任务将在${seconds}秒后开始"
            }
        }) {
            removeOverlay()
            if (alive) action()
        }
    }

    private fun renderCountdown() {
        removeOverlay(cancelCountdown = false)
        val content = FarmUi.column(this, 16).apply { gravity = Gravity.CENTER_HORIZONTAL }
        val circle = FrameLayout(this).apply {
            background = FarmUi.shape(Color.rgb(232, 234, 232), FarmUi.dp(this@FarmAccessibilityService, 80).toFloat())
        }
        countdownNumber = FarmUi.text(this, countdown.seconds.coerceAtLeast(1).toString(), 64f, bold = true).apply {
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 0)
            contentDescription = "任务开始倒计时"
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        circle.addView(countdownNumber, FrameLayout.LayoutParams(-1, -1))
        content.addView(circle, LinearLayout.LayoutParams(FarmUi.dp(this, 160), FarmUi.dp(this, 160)))
        val actions = LinearLayout(this)
        actions.addView(FarmUi.button(this, "取消") {
            countdown.cancel()
            lastMessage = "已取消本次任务"
            showBall()
        }, LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = FarmUi.dp(this@FarmAccessibilityService, 8) })
        actions.addView(FarmUi.button(this, "跳过", FarmUi.ButtonStyle.PRIMARY) { countdown.skip() }, LinearLayout.LayoutParams(0, -2, 1f))
        content.addView(actions, LinearLayout.LayoutParams(-1, -2).apply { topMargin = FarmUi.dp(this@FarmAccessibilityService, 24) })
        val metrics = getSystemService(WindowManager::class.java).currentWindowMetrics
        val safe = metrics.windowInsets.getInsetsIgnoringVisibility(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
        val width = minOf(FarmUi.dp(this, 288), metrics.bounds.width() - safe.left - safe.right - FarmUi.dp(this, 16))
        val maxHeight = metrics.bounds.height() - safe.top - safe.bottom - FarmUi.dp(this, 16)
        val scroll = ScrollView(this).apply { addView(content) }
        scroll.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(maxHeight, View.MeasureSpec.AT_MOST))
        attachOverlay(scroll, width, scroll.measuredHeight, centered = true)
    }

    private fun overlayBounds(width: Int, height: Int): Rect {
        val metrics = getSystemService(WindowManager::class.java).currentWindowMetrics
        val safe = metrics.windowInsets.getInsetsIgnoringVisibility(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
        val margin = FarmUi.dp(this, 8)
        val left = safe.left + margin
        val top = safe.top + margin
        val right = (metrics.bounds.width() - safe.right - width - margin).coerceAtLeast(left)
        val bottom = (metrics.bounds.height() - safe.bottom - height - margin).coerceAtLeast(top)
        return Rect(left, top, right, bottom)
    }

    private fun updateOverlay(view: View, params: WindowManager.LayoutParams) {
        try {
            getSystemService(WindowManager::class.java).updateViewLayout(view, params)
        } catch (error: RuntimeException) {
            overlayFailure = "小白球位置更新失败：${error.javaClass.simpleName}"
        }
    }

    override fun onConfigurationChanged(newConfig: android.content.res.Configuration) {
        super.onConfigurationChanged(newConfig)
        if (countdown.active) renderCountdown()
        else if (overlay != null) { if (panelOpen) showPanel() else showBall() }
    }

    override fun nowMillis() = SystemClock.elapsedRealtime()

    override fun unavailableReason(): String? {
        cliUnavailableReason()?.let { return it }
        if (rootInActiveWindow?.packageName?.toString() != ALIPAY_PACKAGE) {
            return "当前不是支付宝前台页面"
        }
        return null
    }

    fun cliUnavailableReason(): String? {
        if (!alive) return "无障碍服务未连接"
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_TAKE_SCREENSHOT == 0) {
            return "系统未提供无障碍截图能力（需要 Android 11+）"
        }
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_PERFORM_GESTURES == 0) {
            return "系统未提供无障碍手势能力"
        }
        if (serviceInfo.capabilities and AccessibilityServiceInfo.CAPABILITY_CAN_REQUEST_FILTER_KEY_EVENTS == 0 ||
            serviceInfo.flags and AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS == 0
        ) return "系统未提供辅助按键拦截能力，无法安全控制运行"
        val otherKeyFilter = getSystemService(AccessibilityManager::class.java)
            .getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            .any { it.id != serviceInfo.id &&
                it.flags and AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS != 0 }
        if (otherKeyFilter) return "其他无障碍服务正在请求按键拦截，无法保证音量键控制"
        if (!getSystemService(PowerManager::class.java).isInteractive ||
            getSystemService(KeyguardManager::class.java).isKeyguardLocked
        ) return "屏幕已关闭或锁定"
        val appWindows = windows.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
        if (appWindows.size != 1) return "存在多个应用窗口或弹窗，无法确认页面"
        return null
    }

    override fun pageEvidence(): PageEvidence? {
        val root = rootInActiveWindow ?: return null
        val nodes = mutableListOf<PageNode>()
        fun visit(node: android.view.accessibility.AccessibilityNodeInfo) {
            if (!node.isVisibleToUser) return
            val rect = Rect()
            node.getBoundsInScreen(rect)
            nodes += PageNode(
                listOfNotNull(node.text, node.contentDescription).joinToString(" "),
                Bounds(rect.left, rect.top, rect.right, rect.bottom),
                node.className?.toString().orEmpty(), node.paneTitle?.toString(), node.isClickable,
            )
            for (index in 0 until node.childCount) node.getChild(index)?.let { child ->
                try { visit(child) } finally { child.recycle() }
            }
        }
        return try {
            if (root.packageName?.toString() != ALIPAY_PACKAGE) return null
            visit(root)
            PageEvidence(root.windowId, nodes)
        } finally { root.recycle() }
    }

    override fun schedule(delayMillis: Long, action: () -> Unit) {
        handler.postDelayed(action, delayMillis)
    }

    override fun show(view: RunView) {
        keepTaskScreenOn(view.running)
        lastMessage = view.message
        removeOverlay()
        singleControls = true
        if (alive && view.overlayVisible) showBall()
    }

    private fun attachOverlay(layout: View, width: Int, height: Int, centered: Boolean = false) {
        val bounds = overlayBounds(width, height)
        val params = WindowManager.LayoutParams(
            width, height,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.LEFT
            x = if (centered) (bounds.left + bounds.right) / 2 else (ballX ?: bounds.right).coerceIn(bounds.left, bounds.right)
            y = if (centered) (bounds.top + bounds.bottom) / 2 else (ballY ?: FarmUi.dp(this@FarmAccessibilityService, 160)).coerceIn(bounds.top, bounds.bottom)
        }
        try {
            getSystemService(WindowManager::class.java).addView(layout, params)
            overlay = layout
            overlayFailure = null
        } catch (error: RuntimeException) {
            overlay = null
            countdown.cancel()
            overlayFailure = "控制浮层不可用：${error.javaClass.simpleName}"
            lastMessage = overlayFailure
            if (cliRun.busy) cliRun.end()
        }
    }

    private fun removeOverlay(cancelCountdown: Boolean = true) {
        if (cancelCountdown) countdown.cancel()
        countdownNumber = null
        overlay?.let {
            try {
                getSystemService(WindowManager::class.java).removeView(it)
            } catch (error: RuntimeException) {
                overlayFailure = "控制浮层不可用：${error.javaClass.simpleName}"
            }
        }
        overlay = null
    }

    override fun captureAndRecognize(isCurrent: () -> Boolean, callback: (Result<OcrFrame>) -> Unit) {
        if (!alive || !isCurrent()) return
        if (recognizing) {
            // Drain an old in-flight request without failing or overlapping the resumed run.
            schedule(200) { captureAndRecognize(isCurrent, callback) }
            return
        }
        val waitMillis = 500 - (nowMillis() - lastScreenshotMillis)
        if (waitMillis > 0) {
            schedule(waitMillis) { captureAndRecognize(isCurrent, callback) }
            return
        }
        recognizing = true
        lastScreenshotMillis = nowMillis()
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onFailure(errorCode: Int) {
                    recognizing = false
                    val reason = when (errorCode) {
                        ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS -> "无障碍截图授权不可用"
                        ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> "系统限制截图频率，本轮已停止"
                        ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY -> "当前显示器不支持无障碍截图"
                        ERROR_TAKE_SCREENSHOT_SECURE_WINDOW -> "当前窗口禁止截图"
                        else -> "无障碍截图失败"
                    }
                    if (!alive || !isCurrent()) return
                    callback(Result.failure(PlatformFailure("$reason（错误码$errorCode）")))
                }

                override fun onSuccess(screenshot: ScreenshotResult) {
                    if (!alive || !isCurrent()) {
                        screenshot.hardwareBuffer.close()
                        recognizing = false
                        return
                    }
                    val bitmap = try {
                        screenshot.hardwareBuffer.use { buffer ->
                            val hardware = Bitmap.wrapHardwareBuffer(buffer, screenshot.colorSpace)
                                ?: error("No screenshot bitmap")
                            try {
                                hardware.copy(Bitmap.Config.ARGB_8888, false) ?: error("Empty screenshot")
                            } finally {
                                hardware.recycle()
                            }
                        }
                    } catch (error: Exception) {
                        recognizing = false
                        callback(Result.failure(error))
                        return
                    }
                    if (!alive || !isCurrent()) {
                        bitmap.recycle()
                        recognizing = false
                        return
                    }
                    Thread({
                        val result = runCatching {
                            val png = java.io.ByteArrayOutputStream().use { output ->
                                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output))
                                output.toByteArray()
                            }
                            val lines = org.json.JSONArray(NativeRuntime.recognizeJson(this@FarmAccessibilityService, png))
                            OcrFrame(bitmap.width, bitmap.height, (0 until lines.length()).map { index ->
                                val line = lines.getJSONArray(index)
                                val box = line.getJSONArray(1)
                                val xs = (0..3).map { box.getJSONArray(it).getDouble(0).toInt() }
                                val ys = (0..3).map { box.getJSONArray(it).getDouble(1).toInt() }
                                OcrLine(line.getString(0), Bounds(xs.min(), ys.min(), xs.max(), ys.max()))
                            })
                        }
                        bitmap.recycle()
                        handler.post {
                            recognizing = false
                            if (alive && isCurrent()) callback(result)
                        }
                    }, "single-attempt-ocr").start()
                }
            })
        } catch (error: Exception) {
            recognizing = false
            callback(Result.failure(error))
        }
    }

    override fun tap(button: Bounds, callback: (Boolean) -> Unit): Boolean {
        if (unavailableReason() != null) return false
        val path = Path().apply {
            moveTo((button.left + button.right) / 2f, (button.top + button.bottom) / 2f)
        }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
            .build()
        return dispatchGesture(gesture, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription) { callback(true) }
            override fun onCancelled(gestureDescription: GestureDescription) { callback(false) }
        }, handler)
    }

    override fun onKeyEvent(event: KeyEvent): Boolean {
        val key = when (event.keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> VolumeKey.UP
            KeyEvent.KEYCODE_VOLUME_DOWN -> VolumeKey.DOWN
            else -> return false
        }
        if (event.action != KeyEvent.ACTION_DOWN && event.action != KeyEvent.ACTION_UP) return false
        if (event.keyCode in cliHeldKeys) {
            if (event.action == KeyEvent.ACTION_UP) cliHeldKeys.remove(event.keyCode)
            return true
        }
        if (cliRun.busy) {
            if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0) {
                cliHeldKeys.add(event.keyCode)
                if (key == VolumeKey.UP) cliRun.pause() else cliRun.end()
            }
            return true
        }
        return run.onVolumeKey(key, event.action == KeyEvent.ACTION_DOWN, event.repeatCount)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (!run.view.running && !run.view.paused) return
        val problem = unavailableReason()
        if (problem != null) {
            run.stop(problem)
            return
        }
        if (event != null &&
            (event.eventType == AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED ||
                event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED)
        ) run.onPageChanged(event.windowId)
    }

    override fun onInterrupt() {
        if (countdown.active) { countdown.cancel(); showBall() }
        cliRun.end()
        run.stop("无障碍服务中断")
    }

    private fun disconnect() {
        alive = false
        keepTaskScreenOn(false)
        cliRun.end()
        if (connected === this) connected = null
        run.stop("无障碍服务断开")
        handler.removeCallbacksAndMessages(null)
        removeOverlay()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        disconnect()
        return super.onUnbind(intent)
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        keepTaskScreenOn(false)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        disconnect()
        super.onDestroy()
    }
}
