package com.babanongchang.android

import android.app.Activity
import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

class MainActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        fun text(value: String) = TextView(this).apply {
            text = value
            textSize = 17f
            setPadding(0, 12, 0, 12)
            layout.addView(this)
        }
        text("芭芭农场 · 单次施肥验证（非正式可用版）")
        text("本应用在本机识别支付宝农场、肥料余额和施肥按钮。每次手动开始，在余额大于 600 且页面明确时最多尝试施肥一次，可能消耗真实肥料；余额不大于 600 时未执行。真实施肥前须另行明确授权。")
        text("点击前识别与点击后确认各最多等待 10 秒活跃时间；只有有效农场上的余额减少才报告施肥成功。手势完成不代表成功，结果未确认绝不自动补点。暂停不消耗等待额度；点击后继续只确认原结果，结束显示施肥结果未确认。")
        text("截图仅驻留内存，用完释放；中文模型随 APK 打包，无需联网。无截图存档、网络权限或历史日志，仅保留当前进程最近一轮必要结果。")
        text("请自行登录支付宝、解锁并保持亮屏，手动进入芭芭农场。识别期间不要操作手机。需要 Android 11+ 无障碍截图能力，目标手机尚未验证；能力不可用时停止，不采用其他权限路线。")
        text("运行中音量上暂停、音量下结束并恢复浮层；暂停后只能点击浮层继续，也可点击结束。暂停不再截图或启动识别，结束不退出 APK，重新开始必须手动点击。未运行时音量键正常调节音量。")
        text("音量键拦截需要系统无障碍按键过滤支持；即使已授权也不保证目标设备会发送音量键。存在其他按键过滤服务时拒绝运行；目标手机尚未验证，若按键无效请停止验证并关闭服务，不推进施肥功能。")
        text("请在系统无障碍设置中查看说明并自行授权。侧载应用如受系统限制，请遵循系统提示自行决定是否允许；应用不会代为修改设置。")
        status = text("")
        layout.addView(Button(this).apply {
            text = "打开系统无障碍设置"
            setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        layout.addView(Button(this).apply {
            text = "显示单次验证控制浮层"
            setOnClickListener {
                val service = FarmAccessibilityService.connected
                if (service == null) status.text = "服务未连接，请先在系统设置中启用无障碍服务"
                else service.showControls()
            }
        })
        val scroll = android.widget.ScrollView(this)
        scroll.addView(layout, ViewGroup.LayoutParams(-1, -2))
        setContentView(scroll)
    }

    override fun onResume() {
        super.onResume()
        val name = ComponentName(this, FarmAccessibilityService::class.java).flattenToString()
        val enabled = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            ?.split(':')?.any { it.equals(name, ignoreCase = true) } == true
        status.text = when {
            FarmAccessibilityService.connected != null -> "权限状态：无障碍服务已连接；从农场浮层手动开始"
            enabled -> "权限状态：系统已启用，服务尚未连接；请等待或检查系统设置"
            else -> "权限状态：无障碍服务未授权；不会启动截图或识别"
        }
    }
}
