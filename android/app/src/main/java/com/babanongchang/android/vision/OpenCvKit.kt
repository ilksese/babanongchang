package com.babanongchang.android.vision

import org.opencv.android.OpenCVLoader
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.Scalar
import org.opencv.imgcodecs.Imgcodecs
import kotlin.math.floor

object OpenCvKit {
    @Volatile private var ready = false

    fun ensure() {
        if (ready) return
        synchronized(this) {
            if (!ready) {
                check(OpenCVLoader.initLocal()) { "OpenCV 初始化失败" }
                ready = true
            }
        }
    }

    fun decodePng(png: ByteArray): Mat {
        ensure()
        val encoded = Mat(1, png.size, CvType.CV_8U)
        encoded.put(0, 0, png)
        val image = Imgcodecs.imdecode(encoded, Imgcodecs.IMREAD_COLOR)
        encoded.release()
        if (image.empty()) {
            image.release()
            throw IllegalArgumentException("无法解码 OCR 图片")
        }
        return image
    }
}

fun pyRound(value: Double): Int {
    val base = floor(value)
    val fraction = value - base
    val lower = base.toInt()
    return when {
        fraction > 0.5 -> lower + 1
        fraction < 0.5 -> lower
        lower % 2 == 0 -> lower
        else -> lower + 1
    }
}

fun snap32(value: Double): Int = pyRound(value / 32.0) * 32

fun Mat.u8(row: Int, col: Int): Int = get(row, col)[0].toInt() and 0xff

fun Mat.setU8(row: Int, col: Int, value: Int) { put(row, col, value.toDouble()) }

fun Mat.f32(row: Int, col: Int): Double = get(row, col)[0]

fun countNonZero(mat: Mat): Int {
    var count = 0
    val data = ByteArray(mat.cols() * mat.channels())
    for (row in 0 until mat.rows()) {
        mat.get(row, 0, data)
        for (value in data) if (value.toInt() != 0) count += 1
    }
    return count
}

fun black(): Scalar = Scalar(0.0, 0.0, 0.0)
