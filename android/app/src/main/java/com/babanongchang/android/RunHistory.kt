package com.babanongchang.android

import java.io.File
import java.util.Properties
import java.util.UUID

data class RunRecord(val id: String, val title: String, val startedAt: Long, val result: String?)

/** One private directory per run; log output is never overwritten by the next run. */
class RunHistory(private val directory: File) {
    fun create(title: String, module: String, options: String): RunRecord {
        val record = RunRecord(UUID.randomUUID().toString(), title, System.currentTimeMillis(), null)
        val folder = folder(record.id).apply { check(mkdirs()) { "无法创建运行记录" } }
        val metadata = Properties().apply {
            setProperty("title", title)
            setProperty("startedAt", record.startedAt.toString())
            setProperty("module", module)
            setProperty("options", options)
        }
        File(folder, "record.properties").outputStream().use { metadata.store(it, null) }
        File(folder, "run.log").writeText("功能：$title\n模块：$module\n参数：${options.ifBlank { "默认" }}\n\n")
        return record
    }

    fun append(id: String, text: String) { File(folder(id), "run.log").appendText(text) }
    fun finish(id: String, result: String) {
        append(id, "\n$result\n")
        File(folder(id), "result.txt").writeText(result)
    }

    fun list(): List<RunRecord> = directory.listFiles().orEmpty().filter { it.isDirectory }.mapNotNull { folder ->
        runCatching {
            val metadata = Properties().apply { File(folder, "record.properties").inputStream().use { load(it) } }
            RunRecord(folder.name, metadata.getProperty("title"), metadata.getProperty("startedAt").toLong(),
                File(folder, "result.txt").takeIf { it.isFile }?.readText())
        }.getOrNull()
    }.sortedByDescending { it.startedAt }

    fun read(id: String): String = File(folder(id), "run.log").readText()
    private fun folder(id: String): File {
        require(id.matches(Regex("[a-zA-Z0-9-]+"))) { "无效的运行记录" }
        return File(directory, id)
    }
}
