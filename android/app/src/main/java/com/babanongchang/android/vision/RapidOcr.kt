package com.babanongchang.android.vision

import com.babanongchang.android.ClipperOffset
import com.babanongchang.android.OnnxSession
import com.babanongchang.android.engine.OcrEngine
import com.babanongchang.android.engine.OcrRaw
import com.babanongchang.android.engine.ScreenImage
import org.json.JSONArray
import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.MatOfPoint
import org.opencv.core.MatOfPoint2f
import org.opencv.core.Point
import org.opencv.core.Scalar
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min

data class OcrBox(val text: String, val box: List<Pair<Double, Double>>, val score: Double)

class RapidOcr(
    private val det: OnnxSession,
    private val cls: OnnxSession,
    private val rec: OnnxSession,
) : OcrEngine, AutoCloseable {
    private val characters: List<String>

    init {
        val raw = rec.customMetadata("character") ?: error("识别模型缺少字符表")
        val decoded = splitLines(raw)
        characters = listOf("blank") + decoded + listOf(" ")
    }

    fun read(image: Mat): List<OcrBox> = synchronized(this) {
        if (image.empty()) return emptyList()
        val originalH = image.rows()
        val originalW = image.cols()
        val (prepared, ratioH, ratioW) = resizeWithinBounds(image, 30.0, 2000.0)
        val (padded, padTop) = verticalPad(prepared, 8.0, 30.0)
        if (prepared !== padded && prepared !== image) prepared.release()
        val detected = try {
            detect(padded)
        } catch (_: Exception) {
            if (padded !== image) padded.release()
            return emptyList()
        }
        if (detected.isEmpty()) {
            if (padded !== image) padded.release()
            return emptyList()
        }
        val crops = detected.map { crop(padded, it) }
        if (padded !== image) padded.release()
        val rotated = classify(crops)
        val recognized = recognize(rotated)
        val released = java.util.Collections.newSetFromMap(java.util.IdentityHashMap<Mat, Boolean>())
        fun release(mat: Mat) {
            if (mat !== image && released.add(mat)) mat.release()
        }
        rotated.forEach(::release)
        crops.forEach(::release)
        val mapped = detected.map { box ->
            box.map { (x, y) ->
                (x * ratioW).coerceIn(0.0, originalW.toDouble()) to
                    ((y - padTop) * ratioH).coerceIn(0.0, originalH.toDouble())
            }
        }
        return recognized.indices.mapNotNull { index ->
            val (text, score) = recognized[index]
            if (text.trim().isEmpty() || score < 0.5) null else OcrBox(text, mapped[index], score)
        }
    }

    override fun recognize(image: ScreenImage): OcrRaw {
        val captured = image as? com.babanongchang.android.CapturedScreen
            ?: return OcrRaw(emptyList(), emptyList(), emptyList())
        val decoded = OpenCvKit.decodePng(captured.png)
        return try {
            val boxes = read(decoded)
            OcrRaw(boxes.map { it.text }, boxes.map { it.score }, boxes.map { it.box })
        } finally {
            decoded.release()
        }
    }

    fun recognizeJson(png: ByteArray): String {
        val decoded = OpenCvKit.decodePng(png)
        val boxes = try { read(decoded) } finally { decoded.release() }
        val array = JSONArray()
        boxes.forEach { item ->
            val box = JSONArray()
            item.box.forEach { (x, y) -> box.put(JSONArray().put(x).put(y)) }
            array.put(JSONArray().put(item.text).put(box).put(item.score))
        }
        return array.toString()
    }

    override fun close() {
        det.close(); cls.close(); rec.close()
    }

    private fun detect(image: Mat): List<List<Pair<Double, Double>>> {
        val resized = resizeDet(image) ?: return emptyList()
        val input = chw(resized, mean = 0.5, std = 0.5)
        val (pred, shape) = det.runFloats(input, longArrayOf(1, 3, resized.rows().toLong(), resized.cols().toLong()))
        val networkH = shape[shape.size - 2].toInt()
        val networkW = shape[shape.size - 1].toInt()
        val plane = networkH * networkW
        val map = FloatArray(plane) { pred[it] }
        val binary = Mat(networkH, networkW, CvType.CV_8U)
        for (y in 0 until networkH) for (x in 0 until networkW) {
            binary.put(y, x, if (map[y * networkW + x] > 0.3f) 255.0 else 0.0)
        }
        val kernel = Mat(2, 2, CvType.CV_8U, Scalar(1.0))
        val dilated = Mat()
        Imgproc.dilate(binary, dilated, kernel)
        binary.release(); kernel.release()
        val contours = ArrayList<MatOfPoint>()
        val hierarchy = Mat()
        Imgproc.findContours(dilated, contours, hierarchy, Imgproc.RETR_LIST, Imgproc.CHAIN_APPROX_SIMPLE)
        dilated.release(); hierarchy.release()
        val boxes = mutableListOf<List<Pair<Double, Double>>>()
        for (contour in contours.take(1000)) {
            val points = contour.toPoints()
            contour.release()
            val mini = miniBoxes(points) ?: continue
            if (mini.second < 3) continue
            val score = boxScore(map, networkW, networkH, mini.first)
            if (score <= 0.5) continue
            val expanded = unclip(mini.first, 1.6)
            val expandedMini = miniBoxes(expanded) ?: continue
            if (expandedMini.second < 5) continue
            val scaled = expandedMini.first.map { (x, y) ->
                (x / networkW * image.cols()).let { px -> pyRound(px.coerceIn(0.0, image.cols().toDouble())).toDouble() } to
                    pyRound((y / networkH * image.rows()).coerceIn(0.0, image.rows().toDouble())).toDouble()
            }
            val ordered = orderClockwise(scaled)
            val clipped = ordered.map { (x, y) ->
                min(max(x, 0.0), image.cols() - 1.0).toInt().toDouble() to
                    min(max(y, 0.0), image.rows() - 1.0).toInt().toDouble()
            }
            val width = hypot(clipped[0].first - clipped[1].first, clipped[0].second - clipped[1].second).toInt()
            val height = hypot(clipped[0].first - clipped[3].first, clipped[0].second - clipped[3].second).toInt()
            if (width <= 3 || height <= 3) continue
            boxes += clipped
        }
        resized.release()
        return sortedBoxes(boxes)
    }

    private fun classify(images: List<Mat>): List<Mat> {
        if (images.isEmpty()) return images
        val order = images.indices.sortedBy { images[it].cols().toDouble() / images[it].rows() }
        val output = images.toMutableList()
        order.chunked(6).forEach { batch ->
            val tensors = batch.map { resizeNorm(images[it], 48, 192) }
            val width = 192
            val input = FloatArray(batch.size * 3 * 48 * width)
            tensors.forEachIndexed { index, tensor -> tensor.copyInto(input, index * tensor.size) }
            val (pred, shape) = cls.runFloats(input, longArrayOf(batch.size.toLong(), 3, 48, width.toLong()))
            val classes = shape.last().toInt()
            batch.forEachIndexed { index, source ->
                var best = 0
                var bestValue = Float.NEGATIVE_INFINITY
                for (c in 0 until classes) {
                    val value = pred[index * classes + c]
                    if (value > bestValue) { bestValue = value; best = c }
                }
                if (best == 1 && bestValue > 0.9f) {
                    val rotated = Mat()
                    Core.rotate(images[source], rotated, Core.ROTATE_180)
                    output[source] = rotated
                }
            }
        }
        return output
    }

    private fun recognize(images: List<Mat>): List<Pair<String, Double>> {
        if (images.isEmpty()) return emptyList()
        val order = images.indices.sortedBy { images[it].cols().toDouble() / images[it].rows() }
        val results = MutableList(images.size) { "" to 0.0 }
        order.chunked(6).forEach { batch ->
            var maxRatio = 320.0 / 48.0
            batch.forEach { index ->
                val image = images[index]
                maxRatio = max(maxRatio, image.cols().toDouble() / image.rows())
            }
            val targetW = (48 * maxRatio).toInt()
            val tensors = batch.map { resizeNorm(images[it], 48, targetW) }
            val input = FloatArray(batch.size * 3 * 48 * targetW)
            tensors.forEachIndexed { index, tensor -> tensor.copyInto(input, index * tensor.size) }
            val (pred, shape) = rec.runFloats(input, longArrayOf(batch.size.toLong(), 3, 48, targetW.toLong()))
            decode(pred, shape).forEachIndexed { index, line -> results[batch[index]] = line }
        }
        return results
    }

    private fun decode(pred: FloatArray, shape: LongArray): List<Pair<String, Double>> {
        val batch = shape[0].toInt()
        val time = shape[1].toInt()
        val classes = shape[2].toInt()
        return List(batch) { b ->
            val indices = IntArray(time) { t -> argmax(pred, (b * time + t) * classes, classes) }
            val chars = StringBuilder()
            val scores = mutableListOf<Double>()
            for (t in indices.indices) {
                if (t > 0 && indices[t] == indices[t - 1]) continue
                if (indices[t] == 0) continue
                chars.append(characters.getOrElse(indices[t]) { "" })
                scores += round5(pred[(b * time + t) * classes + indices[t]].toDouble())
            }
            chars.toString() to round5(if (scores.isEmpty()) 0.0 else scores.average())
        }
    }
}

private fun splitLines(text: String): List<String> {
    if (text.isEmpty()) return emptyList()
    val lines = text.split(Regex("\\r\\n|\\n|\\r"))
    return if (text.endsWith("\n") || text.endsWith("\r")) lines.dropLast(1) else lines
}

private fun round5(value: Double) = pyRound(value * 100_000.0) / 100_000.0

private fun argmax(values: FloatArray, offset: Int, count: Int): Int {
    var best = 0
    var bestValue = Float.NEGATIVE_INFINITY
    for (index in 0 until count) {
        val value = values[offset + index]
        if (value > bestValue) { bestValue = value; best = index }
    }
    return best
}

private fun resizeWithinBounds(image: Mat, minSide: Double, maxSide: Double): Triple<Mat, Double, Double> {
    var current = image
    var ratioH = 1.0
    var ratioW = 1.0
    val maxValue = max(current.rows(), current.cols())
    if (maxValue > maxSide) {
        val scaled = scaleSide(current, maxSide, grow = false)
        current = scaled.first
        ratioH *= scaled.second
        ratioW *= scaled.third
    }
    if (min(current.rows(), current.cols()) < minSide) {
        val scaled = scaleSide(current, minSide, grow = true)
        if (current !== image) current.release()
        current = scaled.first
        ratioH *= scaled.second
        ratioW *= scaled.third
    }
    return Triple(current, ratioH, ratioW)
}

private fun scaleSide(image: Mat, side: Double, grow: Boolean): Triple<Mat, Double, Double> {
    val h = image.rows().toDouble()
    val w = image.cols().toDouble()
    val ratio = if (grow) {
        if (min(h, w) < side) side / min(h, w) else 1.0
    } else if (max(h, w) > side) side / max(h, w) else 1.0
    val resizedH = snap32(h * ratio).coerceAtLeast(32)
    val resizedW = snap32(w * ratio).coerceAtLeast(32)
    val output = Mat()
    Imgproc.resize(image, output, Size(resizedW.toDouble(), resizedH.toDouble()))
    return Triple(output, h / resizedH, w / resizedW)
}

private fun verticalPad(image: Mat, ratioLimit: Double, minHeight: Double): Pair<Mat, Int> {
    val h = image.rows()
    val w = image.cols()
    val needs = h <= minHeight || w.toDouble() / h > ratioLimit
    if (!needs) return image to 0
    val newH = max((w / ratioLimit).toInt(), minHeight.toInt()) * 2
    val pad = kotlin.math.abs(newH - h) / 2
    val output = Mat()
    Core.copyMakeBorder(image, output, pad, pad, 0, 0, Core.BORDER_CONSTANT, Scalar(0.0, 0.0, 0.0))
    return output to pad
}

private fun resizeDet(image: Mat): Mat? {
    val h = image.rows().toDouble()
    val w = image.cols().toDouble()
    val ratio = if (min(h, w) < 736) 736.0 / min(h, w) else 1.0
    val resizedH = snap32(h * ratio)
    val resizedW = snap32(w * ratio)
    if (resizedH <= 0 || resizedW <= 0) return null
    val output = Mat()
    Imgproc.resize(image, output, Size(resizedW.toDouble(), resizedH.toDouble()))
    return output
}

private fun chw(image: Mat, mean: Double, std: Double): FloatArray {
    val h = image.rows()
    val w = image.cols()
    val data = FloatArray(3 * h * w)
    val row = ByteArray(w * image.channels())
    for (y in 0 until h) {
        image.get(y, 0, row)
        for (x in 0 until w) {
            for (c in 0 until 3) {
                val pixel = (row[x * image.channels() + c].toInt() and 0xff) / 255.0
                data[c * h * w + y * w + x] = ((pixel - mean) / std).toFloat()
            }
        }
    }
    return data
}

private fun resizeNorm(image: Mat, height: Int, width: Int): FloatArray {
    val ratio = image.cols().toDouble() / image.rows()
    val resizedW = if (ceil(height * ratio) > width) width else ceil(height * ratio).toInt()
    val resized = Mat()
    Imgproc.resize(image, resized, Size(resizedW.toDouble(), height.toDouble()))
    val data = FloatArray(3 * height * width)
    val row = ByteArray(resizedW * resized.channels())
    for (y in 0 until height) {
        resized.get(y, 0, row)
        for (x in 0 until resizedW) {
            for (c in 0 until 3) {
                val pixel = (row[x * resized.channels() + c].toInt() and 0xff) / 255.0
                data[c * height * width + y * width + x] = ((pixel - 0.5) / 0.5).toFloat()
            }
        }
    }
    resized.release()
    return data
}

private fun MatOfPoint.toPoints(): List<Pair<Double, Double>> = toList().map { it.x to it.y }

private fun MatOfPoint.toList(): List<Point> = toArray().toList()

private fun miniBoxes(points: List<Pair<Double, Double>>): Pair<List<Pair<Double, Double>>, Double>? {
    if (points.size < 3) return null
    val source = MatOfPoint2f(*points.map { Point(it.first, it.second) }.toTypedArray())
    val rect = Imgproc.minAreaRect(source)
    source.release()
    val box = Mat()
    Imgproc.boxPoints(rect, box)
    val raw = List(4) { index -> box.get(index, 0).let { it[0] to it[1] } }
    box.release()
    val sorted = raw.sortedBy { it.first }
    val (leftA, leftB) = if (sorted[1].second > sorted[0].second) sorted[0] to sorted[1] else sorted[1] to sorted[0]
    val (rightA, rightB) = if (sorted[3].second > sorted[2].second) sorted[2] to sorted[3] else sorted[3] to sorted[2]
    return listOf(leftA, rightA, rightB, leftB) to min(rect.size.width, rect.size.height)
}

private fun boxScore(pred: FloatArray, width: Int, height: Int, box: List<Pair<Double, Double>>): Double {
    val xmin = floor(box.minOf { it.first }).toInt().coerceIn(0, width - 1)
    val xmax = ceil(box.maxOf { it.first }).toInt().coerceIn(0, width - 1)
    val ymin = floor(box.minOf { it.second }).toInt().coerceIn(0, height - 1)
    val ymax = ceil(box.maxOf { it.second }).toInt().coerceIn(0, height - 1)
    val mask = Mat.zeros(ymax - ymin + 1, xmax - xmin + 1, CvType.CV_8U)
    val polygon = MatOfPoint(*box.map { Point(it.first - xmin, it.second - ymin) }.toTypedArray())
    Imgproc.fillPoly(mask, listOf(polygon), Scalar(1.0))
    var sum = 0.0
    var count = 0
    for (y in 0 until mask.rows()) for (x in 0 until mask.cols()) {
        if (mask.u8(y, x) != 0) {
            sum += pred[(ymin + y) * width + xmin + x]
            count += 1
        }
    }
    polygon.release(); mask.release()
    return if (count == 0) 0.0 else sum / count
}

private fun unclip(box: List<Pair<Double, Double>>, ratio: Double): List<Pair<Double, Double>> {
    val length = polygonLength(box)
    if (length == 0.0) return box
    val paths = ClipperOffset.execute(box, polygonArea(box) * ratio / length)
    return paths.maxByOrNull { polygonArea(it.map { point -> point.first.toDouble() to point.second.toDouble() }) }
        ?.map { it.first.toDouble() to it.second.toDouble() } ?: emptyList()
}

private fun polygonArea(points: List<Pair<Double, Double>>): Double {
    var sum = 0.0
    for (index in points.indices) {
        val next = points[(index + 1) % points.size]
        sum += points[index].first * next.second - next.first * points[index].second
    }
    return kotlin.math.abs(sum) / 2.0
}

private fun polygonLength(points: List<Pair<Double, Double>>): Double {
    var sum = 0.0
    for (index in points.indices) {
        val next = points[(index + 1) % points.size]
        sum += hypot(next.first - points[index].first, next.second - points[index].second)
    }
    return sum
}

private fun orderClockwise(points: List<Pair<Double, Double>>): List<Pair<Double, Double>> {
    val sorted = points.sortedBy { it.first }
    val left = sorted.take(2).sortedBy { it.second }
    val right = sorted.drop(2).sortedBy { it.second }
    return listOf(left[0], right[0], right[1], left[1])
}

private fun sortedBoxes(boxes: List<List<Pair<Double, Double>>>): List<List<Pair<Double, Double>>> {
    val byY = boxes.sortedBy { it[0].second }
    val lines = IntArray(byY.size)
    for (index in 1 until byY.size) {
        lines[index] = lines[index - 1] + if (byY[index][0].second - byY[index - 1][0].second >= 10) 1 else 0
    }
    return byY.indices.sortedWith(compareBy({ lines[it] }, { byY[it][0].first })).map { byY[it] }
}

private fun crop(image: Mat, box: List<Pair<Double, Double>>): Mat {
    val width = max(
        hypot(box[0].first - box[1].first, box[0].second - box[1].second),
        hypot(box[2].first - box[3].first, box[2].second - box[3].second),
    ).toInt().coerceAtLeast(1)
    val height = max(
        hypot(box[0].first - box[3].first, box[0].second - box[3].second),
        hypot(box[1].first - box[2].first, box[1].second - box[2].second),
    ).toInt().coerceAtLeast(1)
    val source = MatOfPoint2f(*box.map { Point(it.first, it.second) }.toTypedArray())
    val dest = MatOfPoint2f(
        Point(0.0, 0.0), Point(width.toDouble(), 0.0),
        Point(width.toDouble(), height.toDouble()), Point(0.0, height.toDouble()),
    )
    val transform = Imgproc.getPerspectiveTransform(source, dest)
    val warped = Mat()
    Imgproc.warpPerspective(image, warped, transform, Size(width.toDouble(), height.toDouble()),
        Imgproc.INTER_CUBIC, Core.BORDER_REPLICATE)
    source.release(); dest.release(); transform.release()
    if (height * 1.0 / width >= 1.5) {
        val rotated = Mat()
        Core.rotate(warped, rotated, Core.ROTATE_90_COUNTERCLOCKWISE)
        warped.release()
        return rotated
    }
    return warped
}
