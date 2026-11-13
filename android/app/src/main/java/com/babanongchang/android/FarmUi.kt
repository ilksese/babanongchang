package com.babanongchang.android

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.text.SpannableString
import android.text.style.RelativeSizeSpan
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.TextView

/** Shared native styling for the home screen and accessibility controls. */
object FarmUi {
    val background = Color.rgb(246, 247, 242)
    val ink = Color.rgb(32, 48, 40)
    val muted = Color.rgb(89, 103, 94)
    val green = Color.rgb(39, 100, 69)
    val pale = Color.rgb(232, 241, 232)
    val border = Color.rgb(181, 195, 182)
    val danger = Color.rgb(163, 47, 47)
    private val controlBorder = Color.rgb(108, 127, 112)
    private val disabledFill = Color.rgb(229, 232, 229)
    private val disabledInk = Color.rgb(112, 120, 114)
    enum class ButtonStyle { PRIMARY, SECONDARY, DANGER, TEXT }

    private fun colors(normal: Int, disabled: Int) = ColorStateList(
        arrayOf(intArrayOf(-android.R.attr.state_enabled), intArrayOf()),
        intArrayOf(disabled, normal)
    )

    private fun controlBackground(context: Context, fill: Int, stroke: Int?, checked: Boolean = false): RippleDrawable {
        val radius = dp(context, if (checked) 16 else 12).toFloat()
        fun surface(color: Int, outline: Int?) = shape(color, radius).apply {
            if (outline != null) setStroke(dp(context, 1), outline)
        }
        val states = StateListDrawable().apply {
            addState(intArrayOf(-android.R.attr.state_enabled), surface(disabledFill, border))
            if (checked) addState(intArrayOf(android.R.attr.state_checked), surface(pale, green).apply {
                setStroke(dp(context, 2), green)
            })
            addState(intArrayOf(android.R.attr.state_focused), surface(fill, green).apply {
                setStroke(dp(context, 2), if (fill == green) ink else green)
            })
            addState(intArrayOf(), surface(fill, stroke))
        }
        return RippleDrawable(ColorStateList.valueOf(0x26000000), states, shape(Color.WHITE, radius))
    }
    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun shape(color: Int, radius: Float = 20f, stroke: Int? = null) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radius
        if (stroke != null) setStroke(2, stroke)
    }
    fun column(context: Context, padding: Int = 20) = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        val p = dp(context, padding)
        setPadding(p, p, p, p)
    }
    fun text(context: Context, value: String, size: Float = 16f, color: Int = ink, bold: Boolean = false) = TextView(context).apply {
        text = value
        textSize = size
        setTextColor(color)
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setLineSpacing(dp(context, 4).toFloat(), 1f)
        setPadding(0, dp(context, 4), 0, dp(context, 8))
    }
    fun button(context: Context, title: String, style: ButtonStyle = ButtonStyle.SECONDARY, action: () -> Unit) = Button(context).apply {
        text = title
        textSize = 16f
        setTypeface(typeface, Typeface.BOLD)
        isAllCaps = false
        stateListAnimator = null
        elevation = 0f
        minHeight = dp(context, 52)
        setPadding(dp(context, 12), dp(context, 12), dp(context, 12), dp(context, 12))
        val color = when (style) {
            ButtonStyle.PRIMARY -> Color.WHITE
            ButtonStyle.DANGER -> danger
            else -> green
        }
        setTextColor(colors(color, disabledInk))
        if (style == ButtonStyle.TEXT) paintFlags = paintFlags or android.graphics.Paint.UNDERLINE_TEXT_FLAG
        backgroundTintList = null
        background = controlBackground(context,
            if (style == ButtonStyle.PRIMARY) green else if (style == ButtonStyle.TEXT) Color.TRANSPARENT else Color.WHITE,
            when (style) {
                ButtonStyle.PRIMARY, ButtonStyle.TEXT -> null
                ButtonStyle.DANGER -> danger
                ButtonStyle.SECONDARY -> controlBorder
            })
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(context, 8) }
        setOnClickListener { action() }
    }

    fun choice(context: Context, title: String, description: String = "", action: () -> Unit) = RadioButton(context).apply {
        text = if (description.isEmpty()) title else SpannableString("$title\n$description").apply {
            setSpan(RelativeSizeSpan(13f / 16f), title.length + 1, length, 0)
        }
        textSize = 16f
        gravity = Gravity.CENTER_VERTICAL
        minHeight = dp(context, 56)
        setPadding(dp(context, 12), dp(context, 16), dp(context, 12), dp(context, 16))
        compoundDrawablePadding = dp(context, 8)
        setTextColor(colors(ink, disabledInk))
        buttonTintList = colors(green, disabledInk)
        backgroundTintList = null
        background = controlBackground(context, Color.WHITE, controlBorder, checked = true)
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(context, 8) }
        setOnClickListener { action() }
    }

    fun feature(context: Context, index: Int, choice: RadioButton): android.view.View {
        if (!FeatureSettings.configurable(index)) return choice
        val openSettings = {
            if (context is FarmAccessibilityService) context.hideControls()
            context.startActivity(android.content.Intent(context, FeatureSettingsActivity::class.java)
                .putExtra("feature", index).apply {
                    if (context !is android.app.Activity) addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                })
        }
        choice.setOnLongClickListener { openSettings(); true }
        choice.contentDescription = "${choice.text}，长按设置"
        val padding = dp(context, 12)
        choice.setPadding(padding, dp(context, 36), padding, dp(context, 16))
        return android.widget.FrameLayout(context).apply {
            layoutParams = choice.layoutParams
            addView(choice, android.widget.FrameLayout.LayoutParams(-1, -1))
            addView(text(context, "长按设置", 12f, green).apply {
                setPadding(dp(context, 8), dp(context, 2), dp(context, 8), dp(context, 2))
                background = shape(pale, dp(context, 8).toFloat())
                importantForAccessibility = android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO
                isClickable = false
            }, android.widget.FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.END).apply {
                topMargin = dp(context, 8)
                marginEnd = dp(context, 8)
            })
        }
    }

    fun arrow(button: Button, expanded: Boolean? = null) {
        val icon = button.context.getDrawable(if (expanded == null) R.drawable.ic_chevron_right else R.drawable.ic_expand_more)!!
        icon.setTint(green)
        if (expanded == true) icon.level = 1
        button.setCompoundDrawablesRelativeWithIntrinsicBounds(null, null, icon, null)
        button.compoundDrawablePadding = dp(button.context, 8)
    }
    fun card(context: Context) = column(context).apply {
        background = shape(Color.WHITE, dp(context, 24).toFloat())
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(context, 16) }
    }
}

object FarmFeatures {
    val titles = listOf("一键照料", "连续施肥", "逛农货", "领取任务", "淘宝农场", "麻将", "挪了个箭")
    val descriptions = listOf("依次照料支付宝与淘宝农场", "在支付宝农场使用肥料", "浏览农货，领取奖励", "完成支付宝农场任务", "完成淘宝任务与施肥", "进入游戏后辅助闯关", "进入游戏后辅助解题")
    private val modules = listOf("all", "fertilize", "goods", "tasks", "taobao", "games", "games")
    fun module(index: Int) = modules[index]
    fun options(index: Int, extra: String) = when (index) {
        5 -> "--majiang $extra"
        6 -> "--nlgj $extra"
        else -> extra
    }
}
