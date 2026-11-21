package com.babanongchang.android

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.RadioButton
import android.widget.TextView
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var runStatus: TextView
    private val handler = Handler(Looper.getMainLooper())
    private var selectedFeature = 0
    private val featureButtons = mutableListOf<RadioButton>()
    private lateinit var connection: TextView
    private lateinit var serviceHint: TextView
    private lateinit var serviceSettings: Button
    private lateinit var pauseButton: Button
    private lateinit var endButton: Button
    private val refresh = object : Runnable {
        override fun run() {
            val persistedFeature = getSharedPreferences("cli", MODE_PRIVATE).getInt("feature", 0).coerceIn(FarmFeatures.titles.indices)
            if (persistedFeature != selectedFeature) selectFeature(persistedFeature)
            val service = FarmAccessibilityService.connected
            serviceHint.visibility = if (service == null) android.view.View.VISIBLE else android.view.View.GONE
            serviceSettings.visibility = serviceHint.visibility
            connection.text = if (service == null) "需要开启无障碍服务" else "无障碍已连接 · 可以使用小白球"
            val message = when {
                service == null -> "开启服务后，选择功能并显示小白球。"
                service.cliRun.paused -> "已暂停，可点击小白球继续或结束。"
                service.cliRun.busy -> "正在照料中 · 音量上暂停，音量下结束"
                else -> service.cliRun.message
            } + FarmAccessibilityService.overlayFailure?.let { "\n$it" }.orEmpty()
            if (runStatus.text.toString() != message) runStatus.text = message
            pauseButton.isEnabled = service?.cliRun?.busy == true && !service.cliRun.paused
            endButton.isEnabled = service?.cliRun?.busy == true
            handler.postDelayed(this, 1000)
        }
    }

    private fun selectFeature(index: Int) {
        selectedFeature = index
        getSharedPreferences("cli", MODE_PRIVATE).edit().putInt("feature", index).apply()
        featureButtons.forEachIndexed { i, button ->
            button.isChecked = i == index
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val preferences = getSharedPreferences("cli", MODE_PRIVATE)
        val gutter = maxOf(20, (resources.configuration.screenWidthDp - 560) / 2)
        val layout = FarmUi.column(this, gutter)
        layout.setPadding(FarmUi.dp(this, gutter), FarmUi.dp(this, 20), FarmUi.dp(this, gutter), FarmUi.dp(this, 24))
        fun text(parent: LinearLayout, value: String, size: Float = 16f, bold: Boolean = false) =
            FarmUi.text(this, value, size, bold = bold).also { parent.addView(it) }
        fun button(parent: LinearLayout, title: String, style: FarmUi.ButtonStyle = FarmUi.ButtonStyle.SECONDARY, action: () -> Unit) =
            FarmUi.button(this, title, style, action).also { parent.addView(it) }
        text(layout, "芭芭农场", 30f, true)
        text(layout, "让照料农场，简单一点。", 16f)
        val welcome = FarmUi.card(this).also { layout.addView(it) }
        connection = text(welcome, "正在连接服务", 16f, true)
        serviceHint = text(welcome, "首次使用只需开启无障碍服务。截图与识别均在手机上完成，无需电脑。", 15f)
        serviceSettings = button(welcome, "设置无障碍服务") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        text(layout, "今天想做什么", 22f, true)
        text(layout, "选择一项，稍后在小白球里手动开始。", 15f)
        fun feature(index: Int): android.view.View {
            val choice = FarmUi.choice(this, FarmFeatures.titles[index], FarmFeatures.descriptions[index]) { selectFeature(index) }
            featureButtons += choice
            return FarmUi.feature(this, index, choice)
        }
        layout.addView(feature(0))
        val columns = if (minOf(resources.configuration.screenWidthDp, 560) / resources.configuration.fontScale < 320) 1 else 2
        for (first in 1 until FarmFeatures.titles.size step columns) {
            val row = LinearLayout(this)
            for (index in first until minOf(first + columns, FarmFeatures.titles.size)) {
                feature(index).also {
                    it.layoutParams = LinearLayout.LayoutParams(0, -1, 1f).apply {
                        topMargin = FarmUi.dp(this@MainActivity, 8)
                        if (columns > 1 && index == first) marginEnd = FarmUi.dp(this@MainActivity, 8)
                    }
                    row.addView(it)
                }
            }
            layout.addView(row, LinearLayout.LayoutParams(-1, -2))
        }
        selectFeature(savedInstanceState?.getInt("feature") ?: preferences.getInt("feature", 0).coerceIn(FarmFeatures.titles.indices))
        text(layout, "一键照料会打开支付宝和淘宝；其他功能请先进入对应农场或游戏。", 14f)
        status = text(layout, "点击下方按钮，仅显示小白球，不会立即运行。", 14f)
        status.accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE
        button(layout, "开启小白球", FarmUi.ButtonStyle.PRIMARY) {
            val index = selectedFeature
            val service = FarmAccessibilityService.connected
            preferences.edit().putInt("feature", index).apply()
            status.text = when {
                service == null -> "请先点击上方按钮，开启无障碍服务。"
                service.cliRun.busy -> { service.showControls(); "已显示小白球，可查看当前流程。" }
                !service.configureCli(FarmFeatures.module(index), FeatureSettings.options(preferences, index)) -> "请先结束单次施肥验证。"
                FarmAccessibilityService.overlayFailure != null -> FarmAccessibilityService.overlayFailure
                else -> "小白球已准备好。进入目标页面后，点击小白球选择功能并开始。"
            }
        }
        text(layout, "可拖动贴边 · 点击展开 · 运行时自动隐藏", 14f)
        val current = FarmUi.card(this).also { layout.addView(it) }
        text(current, "当前状态", 20f, true)
        runStatus = text(current, "尚未运行", 15f)
        pauseButton = button(current, "暂停当前流程") { FarmAccessibilityService.connected?.cliRun?.pause() }
        endButton = button(current, "结束当前流程", FarmUi.ButtonStyle.DANGER) { FarmAccessibilityService.connected?.cliRun?.end() }
        text(current, "运行时保持屏幕解锁，请勿手动切换页面。音量上暂停、音量下结束，暂停后点击小白球继续。", 14f)
        button(layout, "运行记录") { startActivity(Intent(this, RunHistoryActivity::class.java)) }.also { FarmUi.arrow(it) }
        val advanced = FarmUi.card(this)
        advanced.visibility = android.view.View.GONE
        val toggle = button(layout, "高级设置与工具") {
            advanced.visibility = if (advanced.visibility == android.view.View.VISIBLE) android.view.View.GONE else android.view.View.VISIBLE
        }
        FarmUi.arrow(toggle, expanded = false)
        toggle.stateDescription = "已收起"
        toggle.setOnClickListener {
            val expanded = advanced.visibility != android.view.View.VISIBLE
            advanced.visibility = if (expanded) android.view.View.VISIBLE else android.view.View.GONE
            toggle.text = if (expanded) "收起高级设置" else "高级设置与工具"
            toggle.stateDescription = if (expanded) "已展开" else "已收起"
            FarmUi.arrow(toggle, expanded)
        }
        layout.addView(advanced)
        button(advanced, "管理无障碍服务") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        button(advanced, "导出运行记录与诊断") {
            if (FarmAccessibilityService.connected?.cliRun?.busy == true) status.text = "请先结束运行，再导出完整诊断。"
            else startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type = "application/zip"
                addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_TITLE, "babanongchang-diagnostics.zip")
            }, 2)
        }
        button(advanced, "单次施肥验证") { FarmAccessibilityService.connected?.showSingleAttempt() }
        text(layout, "使用须知", 18f, true)
        text(layout, "连续施肥会消耗肥料；游戏可能观看广告或使用已有金币、体力。已发出的手势无法撤销，结束后请检查目标应用。", 14f)
        text(layout, "本机离线运行 · 无网络权限\n截图与日志仅保存在手机，手动导出时才写入你选择的位置。", 14f)
        val scroll = ScrollView(this).apply { id = R.id.home_scroll; setBackgroundColor(FarmUi.background); isFillViewport = true; addView(layout) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            val safe = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout() or android.view.WindowInsets.Type.ime())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
            insets
        }
        setContentView(scroll)
        scroll.requestApplyInsets()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putInt("feature", selectedFeature)
        getSharedPreferences("cli", MODE_PRIVATE).edit().apply()
        super.onSaveInstanceState(outState)
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 2 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        Thread {
            val result = runCatching {
                val directory = File(filesDir, "cli-output")
                contentResolver.openOutputStream(uri).use { stream ->
                    ZipOutputStream(checkNotNull(stream)).use { zip ->
                        directory.walkTopDown().filter { it.isFile }.forEach { file ->
                            zip.putNextEntry(ZipEntry(file.relativeTo(directory).path))
                            file.inputStream().use { it.copyTo(zip) }
                            zip.closeEntry()
                        }
                    }
                }
                runOnUiThread { status.text = "诊断已导出" }
            }
            result.exceptionOrNull()?.let { error -> runOnUiThread { status.text = "操作失败：${error.message}" } }
        }.start()
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    override fun onDestroy() {
        if (isFinishing) FarmAccessibilityService.connected?.keepTaskScreenOn(false)
        super.onDestroy()
    }
}
