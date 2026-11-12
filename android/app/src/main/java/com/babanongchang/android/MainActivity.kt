package com.babanongchang.android

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var runStatus: TextView
    private lateinit var logs: TextView
    private lateinit var options: EditText
    private lateinit var selection: Spinner
    private val handler = Handler(Looper.getMainLooper())
    private val features = listOf("全部流程（支付宝 → 淘宝）", "支付宝：连续施肥", "支付宝：逛农货", "支付宝：任务池", "淘宝：完整流程", "游戏：麻将", "游戏：挪了个箭")
    private val modules = listOf("all", "fertilize", "goods", "tasks", "taobao", "games", "games")
    private val refresh = object : Runnable {
        override fun run() {
            val service = FarmAccessibilityService.connected
            runStatus.text = if (service == null) "无障碍服务未连接，请在系统设置中手动开启"
                else "${service.cliRun.message}\n${FarmAccessibilityService.overlayFailure.orEmpty()}"
            val latest = service?.cliRun?.logs.orEmpty()
            if (logs.text.toString() != latest) logs.text = latest
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val preferences = getSharedPreferences("cli", MODE_PRIVATE)
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 40, 24, 24)
        }
        fun text(value: String) = TextView(this).apply {
            text = value
            textSize = 16f
            setPadding(0, 10, 0, 10)
            layout.addView(this)
        }
        fun button(title: String, action: () -> Unit) {
            layout.addView(Button(this).apply { text = title; setOnClickListener { action() } })
        }
        text("芭芭农场 · CLI 全功能版")
        text("本机离线运行，与 CLI 共用任务池及游戏算法。无障碍授权后可截图、识别、点击、滑动、返回与启动支付宝／淘宝。不会自动登录或解锁。连续施肥会消耗肥料，游戏可能观看广告或使用已有金币／体力，规则与 CLI 参数一致。")
        text("全部流程会启动已安装的支付宝和淘宝；单项农场功能请先手动进入农场，游戏请先手动进入目标游戏。保持解锁，运行期间不要手动改变页面。")
        selection = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, features)
            setSelection(preferences.getInt("feature", 0).coerceIn(features.indices))
            layout.addView(this)
        }
        text("附加参数（与 CLI 相同，空白使用默认值；无需输入命令和模块名）")
        options = EditText(this).apply {
            hint = "例如 --threshold 600 --max-clicks 3\n挪了个箭：--mode safe --levels 3 --max-minutes 15"
            setText(preferences.getString("options", ""))
            minLines = 3
            maxLines = 7
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
            layout.addView(this)
        }
        text("可填写全部业务参数：挪了个箭 safe／fast、目标关卡、复活广告、连胜、重开上限、棋盘裁切、只读识别及离线截图。--serial／--adb 仅适用于电脑。")
        text("音量上暂停、音量下结束。暂停后从浮层继续；旧页面坐标失效时会停止，避免继续误点。已发出的手势无法撤销，结束后请检查未确认的操作。目标手机和实体音量键仍需验收。")
        status = text("")
        runStatus = text("")
        button("打开系统无障碍设置") { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        button("保存选择并显示控制浮层") {
            val index = selection.selectedItemPosition
            val service = FarmAccessibilityService.connected
            preferences.edit().putInt("feature", index).putString("options", options.text.toString()).apply()
            val gameFlag = when (index) { 5 -> "--majiang "; 6 -> "--nlgj "; else -> "" }
            status.text = when {
                service == null -> "请先启用无障碍服务"
                !service.configureCli(modules[index], gameFlag + options.text.toString()) -> "流程仍在运行，请先结束"
                else -> "已准备；进入目标页面后，从浮层手动开始"
            }
        }
        button("暂停当前流程") { FarmAccessibilityService.connected?.cliRun?.pause() }
        button("结束当前流程") { FarmAccessibilityService.connected?.cliRun?.end() }
        button("选择截图用于离线识别（挪了个箭）") {
            startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                type = "image/*"
                addCategory(Intent.CATEGORY_OPENABLE)
            }, 1)
        }
        button("查看完整 CLI 参数") {
            Thread {
                val help = runCatching { CliPython.get(this).getModule("babanongchang.android").callAttr("help_text").toString() }
                runOnUiThread {
                    android.app.AlertDialog.Builder(this).setTitle("CLI 参数")
                        .setMessage(help.getOrElse { it.message }).setPositiveButton("关闭", null).show()
                }
            }.start()
        }
        button("导出诊断（截图、识别报告及日志 ZIP）") {
            if (FarmAccessibilityService.connected?.cliRun?.busy == true) {
                status.text = "请先结束运行，再导出完整诊断"
            } else startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type = "application/zip"
                addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_TITLE, "babanongchang-diagnostics.zip")
            }, 2)
        }
        button("原单次施肥验证") { FarmAccessibilityService.connected?.showSingleAttempt() }
        text("截图和日志仅保存在应用私有目录。挪了个箭会保存诊断截图；只有手动导出才写入你选择的位置。中文 OCR 模型随 APK 打包，无网络权限。")
        logs = text("").apply { textSize = 12f; setTextIsSelectable(true) }
        setContentView(ScrollView(this).apply { addView(layout) })
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        Thread {
            val result = runCatching {
                if (requestCode == 1) {
                    val target = File(filesDir, "offline-board.png")
                    contentResolver.openInputStream(uri).use { input ->
                        checkNotNull(input)
                        target.outputStream().use { output -> input.copyTo(output) }
                    }
                    runOnUiThread {
                        selection.setSelection(6)
                        options.setText("--screenshot '${target.absolutePath}' --ocr")
                        status.text = "截图已导入，保存选择并从浮层开始；离线识别不会操作目标应用"
                    }
                } else if (requestCode == 2) {
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
}
