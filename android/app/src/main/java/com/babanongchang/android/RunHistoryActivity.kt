package com.babanongchang.android

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class RunHistoryActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val history by lazy { RunHistory(File(filesDir, "cli-output/runs")) }
    private val dateFormat = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())
    private lateinit var content: LinearLayout
    private lateinit var message: TextView
    private lateinit var refreshButton: android.widget.Button
    private var loading = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val id = intent.getStringExtra("record_id")
        val layout = FarmUi.column(this, 20).apply { setBackgroundColor(FarmUi.background) }
        layout.addView(FarmUi.button(this, if (id == null) "返回首页" else "返回运行记录") { finish() })
        layout.addView(FarmUi.text(this, if (id == null) "运行记录" else "日志详情", 28f, bold = true))
        message = FarmUi.text(this, "正在读取…", 14f).also { layout.addView(it) }
        refreshButton = FarmUi.button(this, "刷新记录") { load(id) }.also { layout.addView(it) }
        content = FarmUi.column(this, 0)
        layout.addView(content, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = FarmUi.dp(this@RunHistoryActivity, 16) })
        layout.setOnApplyWindowInsetsListener { view, insets ->
            val safe = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
            val p = FarmUi.dp(this, 20)
            view.setPadding(safe.left + p, safe.top + p, safe.right + p, safe.bottom + p)
            insets
        }
        setContentView(layout)
        layout.requestApplyInsets()
    }

    override fun onResume() {
        super.onResume()
        load(intent.getStringExtra("record_id"))
    }

    private fun result(record: RunRecord): String = record.result ?: if (
        FarmAccessibilityService.connected?.cliRun?.activeRecordId == record.id
    ) "运行中" else "运行已中断，未记录结束结果"

    private fun load(id: String?) {
        if (loading) return
        loading = true
        refreshButton.isEnabled = false
        worker.execute {
            val data = runCatching { history.list() to id?.let { history.read(it) } }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                loading = false
                refreshButton.isEnabled = true
                data.fold(onSuccess = { (records, log) ->
                    content.removeAllViews()
                    if (id == null) {
                        message.text = if (records.isEmpty()) "还没有运行记录。任务开始后会自动保存，倒计时取消不产生记录。"
                            else "共 ${records.size} 次运行 · 按时间倒序排列"
                        val list = ListView(this).apply {
                            divider = null
                            adapter = object : ArrayAdapter<RunRecord>(this@RunHistoryActivity, android.R.layout.simple_list_item_2, records) {
                                override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
                                    val view = convertView ?: layoutInflater.inflate(android.R.layout.simple_list_item_2, parent, false)
                                    val record = getItem(position)!!
                                    view.findViewById<TextView>(android.R.id.text1).apply {
                                        text = record.title + " · " + dateFormat.format(Date(record.startedAt))
                                        setTextColor(FarmUi.ink)
                                        textSize = 16f
                                        isSingleLine = false
                                    }
                                    view.findViewById<TextView>(android.R.id.text2).apply {
                                        text = result(record)
                                        setTextColor(FarmUi.muted)
                                        textSize = 14f
                                        maxLines = 3
                                    }
                                    val arrow = getDrawable(R.drawable.ic_chevron_right)!!
                                    arrow.setTint(FarmUi.green)
                                    view.findViewById<TextView>(android.R.id.text1).setCompoundDrawablesRelativeWithIntrinsicBounds(null, null, arrow, null)
                                    view.background = android.graphics.drawable.RippleDrawable(
                                        android.content.res.ColorStateList.valueOf(0x26000000),
                                        FarmUi.shape(android.graphics.Color.WHITE, FarmUi.dp(this@RunHistoryActivity, 12).toFloat(), FarmUi.border), null)
                                    view.minimumHeight = FarmUi.dp(this@RunHistoryActivity, 88)
                                    return view
                                }
                            }
                            setOnItemClickListener { _, _, position, _ ->
                                startActivity(Intent(this@RunHistoryActivity, RunHistoryActivity::class.java).putExtra("record_id", records[position].id))
                            }
                        }
                        content.addView(list, LinearLayout.LayoutParams(-1, -1))
                    } else {
                        val record = records.firstOrNull { it.id == id }
                        message.text = record?.let { "${it.title}\n${dateFormat.format(Date(it.startedAt))}\n${result(it)}" } ?: "运行记录"
                        val text = FarmUi.text(this, log.orEmpty().ifBlank { "暂无日志输出，可稍后刷新。" }, 14f).apply {
                            setTextIsSelectable(true)
                            typeface = android.graphics.Typeface.MONOSPACE
                        }
                        content.addView(ScrollView(this).apply { addView(text) }, LinearLayout.LayoutParams(-1, -1))
                    }
                }, onFailure = { message.text = "读取运行记录失败：${it.message}，请点击刷新重试。" })
            }
        }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }
}
