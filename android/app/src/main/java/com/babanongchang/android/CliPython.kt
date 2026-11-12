package com.babanongchang.android

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

object CliPython {
    @Synchronized
    fun get(context: Context): Python {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        return Python.getInstance()
    }
}
