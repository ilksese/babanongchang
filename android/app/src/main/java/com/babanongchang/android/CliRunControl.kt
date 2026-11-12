package com.babanongchang.android

/** A run cannot be replaced until its worker and outstanding platform requests drain. */
class CliRunControl(private val clock: () -> Long) {
    private val monitor = Object()
    private var stopped = false
    private var pausedAt: Long? = null
    private var pausedMillis = 0L
    var revision = 0
        private set

    fun checkpoint() = synchronized(monitor) {
        while (pausedAt != null && !stopped) monitor.wait()
        check(!stopped) { "已由用户结束；已发出的手势不能撤销" }
    }

    fun pause() = synchronized(monitor) {
        if (!stopped && pausedAt == null) {
            pausedAt = clock()
            revision++
        }
    }

    fun resume() = synchronized(monitor) {
        pausedAt?.let { pausedMillis += clock() - it }
        pausedAt = null
        monitor.notifyAll()
    }

    fun stop() = synchronized(monitor) {
        stopped = true
        monitor.notifyAll()
    }

    fun activeMillis(): Long {
        checkpoint()
        return synchronized(monitor) { (pausedAt ?: clock()) - pausedMillis }
    }

    fun sleepMillis(duration: Long) {
        require(duration >= 0)
        val until = activeMillis() + duration
        synchronized(monitor) {
            while (true) {
                checkpoint()
                val remaining = until - activeMillis()
                if (remaining <= 0) return
                monitor.wait(remaining.coerceAtMost(100))
            }
        }
    }

    fun requireFresh(observedRevision: Int) = synchronized(monitor) {
        check(!stopped && pausedAt == null && revision == observedRevision) {
            "暂停后旧页面证据已失效，本轮停止；请重新识别后开始"
        }
    }
}
