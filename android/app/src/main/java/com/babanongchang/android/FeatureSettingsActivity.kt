package com.babanongchang.android

import android.app.Activity
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.Switch

class FeatureSettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val index = intent.getIntExtra("feature", -1)
        if (!FeatureSettings.configurable(index)) { finish(); return }
        val preferences = getSharedPreferences("cli", MODE_PRIVATE)
        val gutter = maxOf(20, (resources.configuration.screenWidthDp - 560) / 2)
        val layout = FarmUi.column(this, gutter)
        layout.addView(FarmUi.button(this, "返回功能选择") { finish() })
        layout.addView(FarmUi.text(this, "${FarmFeatures.titles[index]}设置", 28f, bold = true))
        val saved = FarmUi.text(this, "修改自动保存，下一次开始运行时生效。", 14f)
        saved.accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE
        layout.addView(saved)
        fun card(title: String) = FarmUi.card(this).also {
            layout.addView(it)
            it.addView(FarmUi.text(this, title, 20f, bold = true))
        }
        fun toggle(parent: LinearLayout, field: String, title: String, default: Boolean) {
            parent.addView(Switch(this).apply {
                text = title
                textSize = 16f
                setTextColor(FarmUi.ink)
                minimumHeight = FarmUi.dp(this@FeatureSettingsActivity, 56)
                isChecked = preferences.getBoolean(FeatureSettings.key(index, field), default)
                setOnCheckedChangeListener { _, checked ->
                    preferences.edit().putBoolean(FeatureSettings.key(index, field), checked).apply()
                    saved.text = "已自动保存，下次运行生效。"
                }
            })
        }
        fun choices(parent: LinearLayout, field: String, values: List<Pair<String, String>>, default: String) {
            val buttons = values.map { (value, title) ->
                FarmUi.choice(this, title) {}.apply {
                    isChecked = preferences.getString(FeatureSettings.key(index, field), default) == value
                    parent.addView(this)
                }
            }
            buttons.forEachIndexed { i, button -> button.setOnClickListener {
                preferences.edit().putString(FeatureSettings.key(index, field), values[i].first).apply()
                buttons.forEach { it.isChecked = it == button }
                saved.text = "已自动保存，下次运行生效。"
            } }
        }
        if (index == 5) {
            choices(card("运行模式"), "mode", listOf("safe" to "安全模式 · 每步识别确认", "fast" to "快速模式 · 按分析顺序连续点击"), "safe")
        }
        val fields = FeatureSettings.numbers(index)
        if (fields.isNotEmpty()) {
            val settings = card(if (index == 5) "关卡与运行限制" else "运行设置")
            if (index == 5) settings.addView(FarmUi.text(this, "设置目标关卡后，完成该关或更高关卡才停止，通关次数和最长运行时间不再作为停止条件。", 14f))
            val inputs = mutableMapOf<String, EditText>()
            fields.forEach { field ->
                val label = FarmUi.text(this, field.title)
                settings.addView(label)
                val input = EditText(this).apply {
                    id = android.view.View.generateViewId()
                    label.labelFor = id
                    setSingleLine(true)
                    textSize = 16f
                    setTextColor(FarmUi.ink)
                    minimumHeight = FarmUi.dp(this@FeatureSettingsActivity, 48)
                    inputType = InputType.TYPE_CLASS_NUMBER or (if (field.decimal) InputType.TYPE_NUMBER_FLAG_DECIMAL else 0)
                    setText(FeatureSettings.value(preferences, index, field))
                }
                inputs[field.key] = input
                settings.addView(input)
            }
            fun save() {
                var valid = true
                fields.forEach { field ->
                    val input = inputs.getValue(field.key)
                    val ok = field.valid(input.text.toString().trim())
                    input.error = if (ok) null else "请输入有效数值（${field.min}～${field.max}）"
                    if (!ok) valid = false
                }
                if (index == 5) {
                    val top = inputs.getValue("board-top").text.toString().toDoubleOrNull()
                    val bottom = inputs.getValue("board-bottom").text.toString().toDoubleOrNull()
                    if (top != null && bottom != null && top >= bottom) {
                        inputs.getValue("board-bottom").error = "棋盘底部必须大于顶部"
                        valid = false
                    }
                }
                if (!valid) { saved.text = "尚未保存：请修正标记的数值，上次有效设置仍然保留。"; return }
                val editor = preferences.edit()
                fields.forEach { editor.putString(FeatureSettings.key(index, it.key), inputs.getValue(it.key).text.toString().trim()) }
                editor.apply()
                saved.text = "已自动保存，下次运行生效。"
            }
            inputs.values.forEach { input -> input.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
                override fun afterTextChanged(s: Editable?) = save()
            }) }
        }
        if (index == 5) {
            val strategy = card("复活与连胜")
            toggle(strategy, "revive-ads", "允许观看广告复活", true)
            choices(strategy, "streak-policy", listOf("coins-or-abandon" to "连胜：金币足够则使用，否则放弃", "stop" to "连胜：遇到需要金币时停止"), "coins-or-abandon")
            val inspect = card("画面识别")
            toggle(inspect, "dry-run", "仅识别当前画面，不点击", false)
        }
        if (index == 0 || index == 4) {
            val ocr = card("淘宝文字识别")
            val label = FarmUi.text(this, "")
            ocr.addView(label)
            val confidence = SeekBar(this).apply {
                max = 100
                progress = preferences.getInt("taobao_confidence", 75).coerceIn(0, 100)
                minimumHeight = FarmUi.dp(this@FeatureSettingsActivity, 48)
                contentDescription = "淘宝文字识别置信度"
            }
            fun update(value: Int) { label.text = "识别置信度：%.2f".format(java.util.Locale.ROOT, value / 100.0) }
            update(confidence.progress)
            confidence.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(bar: SeekBar?, progress: Int, fromUser: Boolean) { update(progress) }
                override fun onStartTrackingTouch(bar: SeekBar?) = Unit
                override fun onStopTrackingTouch(bar: SeekBar?) {
                    preferences.edit().putInt("taobao_confidence", confidence.progress).apply()
                    saved.text = "已自动保存，下次运行生效。"
                }
            })
            ocr.addView(confidence)
            ocr.addView(FarmUi.text(this, "一键照料与淘宝农场共用此设置。默认 0.75，调低可能增加误识别。", 14f))
            ocr.addView(FarmUi.button(this, "恢复默认识别置信度", FarmUi.ButtonStyle.TEXT) {
                confidence.progress = 75
                preferences.edit().remove("taobao_confidence").apply()
                saved.text = "已恢复默认并自动保存。"
            })
        }
        val scroll = ScrollView(this).apply { setBackgroundColor(FarmUi.background); addView(layout) }
        scroll.setOnApplyWindowInsetsListener { view, insets ->
            val safe = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout() or android.view.WindowInsets.Type.ime())
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom)
            insets
        }
        setContentView(scroll)
        scroll.requestApplyInsets()
    }
}
