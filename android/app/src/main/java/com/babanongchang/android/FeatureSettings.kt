package com.babanongchang.android

import android.content.SharedPreferences

/** Only validated, feature-specific values reach the shared CLI. */
object FeatureSettings {
    data class Number(val key: String, val title: String, val default: String, val min: Double = 0.0, val max: Double = Int.MAX_VALUE.toDouble(), val decimal: Boolean = false, val optional: Boolean = false) {
        fun valid(value: String): Boolean = (optional && value.isBlank()) ||
            (value.toDoubleOrNull()?.let { it.isFinite() && it in min..max && (decimal || value.toIntOrNull() != null) } == true)
    }
    private val threshold = Number("threshold", "停止施肥的肥料余额", "600")
    private val clicks = Number("max-clicks", "最多施肥次数（留空不限）", "", 1.0, optional = true)
    private val browse = Number("browse-seconds", "浏览时长（秒，至少 15）", "18", 15.0, decimal = true)
    fun numbers(index: Int): List<Number> = when (index) {
        0 -> listOf(threshold, clicks, browse)
        1 -> listOf(threshold, clicks)
        2, 3 -> listOf(browse)
        6 -> listOf(
            Number("target", "目标关卡（留空不指定）", "", 1.0, optional = true),
            Number("levels", "通关次数（0 表示仅按时限停止）", "3"),
            Number("max-minutes", "最长运行时间（分钟）", "15", 0.01, decimal = true),
            Number("delay", "安全模式点击间隔（秒）", "0.65", 0.01, decimal = true),
            Number("idle-timeout", "页面等待时限（秒）", "35", 0.01, decimal = true),
            Number("max-restarts", "最多重开次数（消耗体力，0 禁止）", "0"),
            Number("ad-timeout", "复活广告等待时限（秒）", "180", 0.01, decimal = true),
            Number("board-top", "棋盘顶部位置（屏幕高度比例）", "0.146", 0.0, 1.0, true),
            Number("board-bottom", "棋盘底部位置（屏幕高度比例）", "0.824", 0.0, 1.0, true))
        else -> emptyList()
    }
    fun configurable(index: Int) = index in 0..4 || index == 6
    fun key(index: Int, field: String) = "feature_${index}_$field"
    fun value(preferences: SharedPreferences, index: Int, field: Number): String =
        preferences.getString(key(index, field.key), field.default).orEmpty().takeIf(field::valid) ?: field.default

    fun options(preferences: SharedPreferences, index: Int): String {
        val args = mutableListOf<String>()
        numbers(index).forEach { field ->
            val value = value(preferences, index, field)
            if (value.isNotBlank()) args += "--${field.key} $value"
        }
        if (index == 6) {
            val mode = preferences.getString(key(index, "mode"), "safe").takeIf { it == "safe" || it == "fast" } ?: "safe"
            val streak = preferences.getString(key(index, "streak-policy"), "coins-or-abandon").takeIf { it == "coins-or-abandon" || it == "stop" } ?: "coins-or-abandon"
            args += "--mode $mode --streak-policy $streak"
            if (!preferences.getBoolean(key(index, "revive-ads"), true)) args += "--no-revive-ads"
            if (preferences.getBoolean(key(index, "dry-run"), false)) args += "--dry-run"
            if (preferences.getBoolean(key(index, "offline"), false)) {
                preferences.getString(key(index, "screenshot"), null)?.let { args += "--screenshot '$it' --ocr" }
            }
        }
        return FarmFeatures.options(index, args.joinToString(" "))
    }
}
