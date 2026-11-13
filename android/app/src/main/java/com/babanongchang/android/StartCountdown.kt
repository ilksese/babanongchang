package com.babanongchang.android

/** Main-thread countdown; cancelled or superseded callbacks cannot launch a task. */
class StartCountdown(private val clock: () -> Long, private val schedule: (Long, () -> Unit) -> Unit) {
    private var generation = 0
    private var deadline = 0L
    private var launch: (() -> Unit)? = null
    val active: Boolean get() = launch != null
    val seconds: Int get() = ((deadline - clock()).coerceAtLeast(0) + 999).div(1000).toInt()

    fun start(onTick: (Int) -> Unit, onFinish: () -> Unit) {
        cancel()
        deadline = clock() + 3000
        launch = onFinish
        val token = generation
        fun tick() {
            if (token != generation || !active) return
            if (seconds == 0) skip()
            else {
                onTick(seconds)
                schedule((deadline - clock()).coerceIn(1, 1000)) { tick() }
            }
        }
        tick()
    }

    fun cancel() {
        generation++
        launch = null
    }

    fun skip() {
        val action = launch ?: return
        cancel()
        action()
    }
}
