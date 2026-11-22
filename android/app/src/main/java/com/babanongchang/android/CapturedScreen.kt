package com.babanongchang.android

import com.babanongchang.android.engine.ScreenImage

class CapturedScreen(override val width: Int, override val height: Int, val png: ByteArray) : ScreenImage
