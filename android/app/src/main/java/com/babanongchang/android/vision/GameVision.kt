package com.babanongchang.android.vision

import org.opencv.core.Core
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.core.Point
import org.opencv.core.Rect
import org.opencv.core.Scalar
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

val DIRECTIONS = listOf(0 to 1, 1 to 0, 0 to -1, -1 to 0)

data class Arrow(
    val label: Int,
    val x: Int,
    val y: Int,
    val dx: Int,
    val dy: Int,
    val confidence: Double,
    val scale: Double,
)

class Board(
    var image: Mat,
    var labels: Mat,
    val arrows: MutableMap<Int, Arrow> = mutableMapOf(),
    val blockers: MutableMap<Int, Set<Int>> = mutableMapOf(),
    var order: List<Int> = emptyList(),
    var reason: String = "",
    val noTap: MutableList<IntArray> = mutableListOf(),
) {
    val valid: Boolean get() = arrows.isNotEmpty() && reason.isEmpty()
}

fun topologicalOrder(blockers: Map<Int, Set<Int>>): List<Int> {
    val remaining = blockers.keys.toMutableSet()
    val order = mutableListOf<Int>()
    val removed = mutableSetOf<Int>()
    while (remaining.isNotEmpty()) {
        val ready = remaining.filter { blockers.getValue(it).all { dep -> dep in removed } }.sorted()
        if (ready.isEmpty()) break
        order += ready
        remaining.removeAll(ready.toSet())
        removed += ready
    }
    return order
}

fun normalizeWidth(image: Mat): Mat {
    val output = Mat()
    Imgproc.resize(image, output, Size(720.0, pyRound(image.rows() * 720.0 / image.cols()).toDouble()))
    return output
}

fun darkBoard(image: Mat, top: Double, bottom: Double, noTap: MutableList<IntArray>? = null): Mat {
    val mask = Mat()
    Core.inRange(image, Scalar(0.0, 0.0, 0.0), Scalar(115.0, 100.0, 100.0), mask)
    val red = Mat()
    Core.inRange(image, Scalar(40.0, 25.0, 180.0), Scalar(180.0, 160.0, 255.0), red)
    Core.bitwise_or(mask, red, mask)
    red.release()
    val height = mask.rows()
    val topRow = pyRound(height * top).coerceIn(0, height)
    val bottomRow = pyRound(height * bottom).coerceIn(0, height)
    if (topRow > 0) mask.rowRange(0, topRow).setTo(Scalar(0.0))
    if (bottomRow < height) mask.rowRange(bottomRow, height).setTo(Scalar(0.0))
    return removeEdgeOverlays(mask, noTap)
}

fun removeEdgeOverlays(mask: Mat, noTap: MutableList<IntArray>?): Mat {
    val width = mask.cols()
    val unit = width / 720.0
    val labels = Mat()
    val stats = Mat()
    val centroids = Mat()
    val count = Imgproc.connectedComponentsWithStats(mask, labels, stats, centroids)
    var distance: Mat? = null
    for (index in 1 until count) {
        val x = stat(stats, index, Imgproc.CC_STAT_LEFT)
        val componentWidth = stat(stats, index, Imgproc.CC_STAT_WIDTH)
        if (x > 3 * unit && x + componentWidth < width - 3 * unit) continue
        if (distance == null) {
            distance = Mat()
            Imgproc.distanceTransform(mask, distance, Imgproc.DIST_L2, 5)
        }
        var maxDistance = 0.0
        for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) {
            if (labelAt(labels, row, col) == index) maxDistance = max(maxDistance, distance.get(row, col)[0])
        }
        if (maxDistance >= 8 * unit) {
            for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) {
                if (labelAt(labels, row, col) == index) mask.put(row, col, 0.0)
            }
            if (noTap != null) {
                val y = stat(stats, index, Imgproc.CC_STAT_TOP)
                val componentHeight = stat(stats, index, Imgproc.CC_STAT_HEIGHT)
                val inward = (36 * unit).roundToInt()
                val up = (96 * unit).roundToInt()
                val down = (52 * unit).roundToInt()
                val x0 = if (x <= 3 * unit) 0.0 else x - inward
                val x1 = if (x + componentWidth >= width - 3 * unit) width - 1.0 else x + componentWidth + inward
                noTap += intArrayOf(x0.toInt(), (y - up).toInt(), x1.toInt(), (y + componentHeight + down).toInt())
            }
        }
    }
    labels.release(); stats.release(); centroids.release(); distance?.release()
    return mask
}

fun whiteBoardBackground(image: Mat, top: Double, bottom: Double): Boolean {
    val y0 = pyRound(image.rows() * top).coerceIn(0, image.rows())
    val y1 = pyRound(image.rows() * bottom).coerceIn(0, image.rows())
    if (y1 <= y0) return false
    var white = 0
    var background = 0
    val channels = image.channels()
    val row = ByteArray(image.cols() * channels)
    for (y in y0 until y1) {
        image.get(y, 0, row)
        for (x in 0 until image.cols()) {
            var minChannel = 255
            for (c in 0 until channels) minChannel = min(minChannel, row[x * channels + c].toInt() and 0xff)
            if (minChannel > 235) white += 1
            if (minChannel > 120) background += 1
        }
    }
    val size = (y1 - y0) * image.cols()
    return white.toDouble() / size >= 0.45 && white.toDouble() / max(1, background) >= 0.90
}

fun heartCount(image: Mat): Int {
    val y0 = pyRound(image.rows() * 0.065)
    val y1 = pyRound(image.rows() * 0.097)
    val x0 = pyRound(image.cols() * 0.38)
    val x1 = pyRound(image.cols() * 0.62)
    if (y1 <= y0 || x1 <= x0) return 0
    val roi = image.submat(Rect(x0, y0, x1 - x0, y1 - y0))
    val mask = Mat()
    Core.inRange(roi, Scalar(30.0, 30.0, 200.0), Scalar(150.0, 150.0, 255.0), mask)
    roi.release()
    val labels = Mat(); val stats = Mat(); val centroids = Mat()
    val count = Imgproc.connectedComponentsWithStats(mask, labels, stats, centroids)
    val hearts = (1 until count).count { stat(stats, it, Imgproc.CC_STAT_AREA) > 180 }
    mask.release(); labels.release(); stats.release(); centroids.release()
    return hearts
}

fun heartLost(previous: Int?, hearts: Int, finalTap: Boolean = false) =
    previous != null && previous > 0 && hearts > 0 && hearts < previous && !finalTap

fun arrowHasLeft(mask: Mat, original: Mat, count: Int, previousCount: Int, expectedAfter: Mat?): Boolean {
    val overlap = overlapCount(mask, original)
    val unchanged = expectedAfter == null || differenceCount(mask, expectedAfter) <= 2
    val originalCount = countNonZero(original)
    return count == previousCount - 1 && unchanged && overlap <= max(3, (0.01 * originalCount).toInt())
}

fun recognizeBoard(image: Mat, top: Double = 0.146, bottom: Double = 0.824): Board {
    val normalized = normalizeWidth(image)
    val height = normalized.rows()
    val width = normalized.cols()
    val y0 = pyRound(height * top)
    val y1 = pyRound(height * bottom)
    val empty = Mat.zeros(height, width, CvType.CV_32S)
    val board = Board(normalized, empty)
    if (!whiteBoardBackground(normalized, top, bottom)) {
        board.reason = "Board is dimmed/covered or not on a white game screen"
        return board
    }
    val mask = darkBoard(normalized, top, bottom, board.noTap)
    val labels = Mat(); val stats = Mat(); val centroids = Mat()
    val count = Imgproc.connectedComponentsWithStats(mask, labels, stats, centroids)
    val expected = (1 until count).filter { stat(stats, it, Imgproc.CC_STAT_AREA) >= 35 }.toSet()
    board.labels = labels
    empty.release()
    if (expected.isEmpty()) {
        board.reason = "No arrows"
        mask.release(); stats.release(); centroids.release()
        return board
    }
    for (index in expected) {
        val x = stat(stats, index, Imgproc.CC_STAT_LEFT)
        val y = stat(stats, index, Imgproc.CC_STAT_TOP)
        val boxWidth = stat(stats, index, Imgproc.CC_STAT_WIDTH)
        val boxHeight = stat(stats, index, Imgproc.CC_STAT_HEIGHT)
        if (x <= 1 || x + boxWidth >= width - 1 || y <= y0 + 1 || y + boxHeight >= y1 - 1) {
            board.reason = "An arrow touches the board crop; zoom out or adjust --board-top/bottom"
            mask.release(); stats.release(); centroids.release()
            return board
        }
    }
    val base = headTemplate()
    val scales = listOf(1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3, 0.6, 1.45, 0.5, 1.6, 0.4, 1.75)
    for (scale in scales) {
        val scaled = resizeNearest(base, scale)
        matchHeads(mask, labels, expected, board.arrows, scaled, scale)
        scaled.release()
        if (board.arrows.keys == expected) break
    }
    val ranked = board.arrows.values.sortedByDescending { it.confidence }
    val seeds = ranked.take(2).toMutableList()
    for (arrow in ranked) if (seeds.none { it.scale == arrow.scale }) seeds += arrow
    seeds.sortByDescending { it.confidence }
    for (seed in seeds) {
        val missing = expected - board.arrows.keys
        if (missing.isEmpty() || seed.confidence < 0.88) break
        val radius = max(10, (20 * seed.scale).roundToInt())
        if (!(radius < seed.x && seed.x < width - radius && radius < seed.y && seed.y < height - radius)) continue
        val patch = Mat.zeros(radius * 2 + 1, radius * 2 + 1, CvType.CV_8U)
        for (row in 0 until patch.rows()) for (col in 0 until patch.cols()) {
            if (labelAt(labels, seed.y - radius + row, seed.x - radius + col) == seed.label) patch.put(row, col, 255.0)
        }
        val rotation = DIRECTIONS.indexOf(seed.dx to seed.dy)
        val upright = rot90(patch, -rotation)
        patch.release()
        val halfWidth = (12 * seed.scale).roundToInt()
        val yStart = radius - (7 * seed.scale).roundToInt()
        val yEnd = radius + (17 * seed.scale).roundToInt()
        val template = upright.submat(Rect(radius - halfWidth, yStart, halfWidth * 2, yEnd - yStart + 1)).clone()
        upright.release()
        matchHeads(mask, labels, missing, board.arrows, template, seed.scale, 0.86)
        template.release()
    }
    val sortedScales = scales.sorted()
    for (index in 0 until sortedScales.size - 1) {
        val missing = expected - board.arrows.keys
        if (missing.isEmpty()) break
        val scale = (sortedScales[index] + sortedScales[index + 1]) / 2
        val scaled = resizeNearest(base, scale)
        matchHeads(mask, labels, missing, board.arrows, scaled, scale)
        scaled.release()
    }
    base.release(); mask.release(); stats.release(); centroids.release()
    val missing = expected - board.arrows.keys
    if (missing.isNotEmpty()) {
        board.reason = "Unrecognized strokes/animation: ${missing.size} components"
        return board
    }
    for ((label, arrow) in board.arrows) {
        val margin = max(2, (2 * arrow.scale).roundToInt())
        val hits = mutableSetOf<Int>()
        if (arrow.dx != 0) {
            val yStart = max(0, arrow.y - margin)
            val yEnd = min(height - 1, arrow.y + margin)
            val xRange = if (arrow.dx > 0) arrow.x until width else 0..arrow.x
            for (y in yStart..yEnd) for (x in xRange) hits += labelAt(labels, y, x)
        } else {
            val xStart = max(0, arrow.x - margin)
            val xEnd = min(width - 1, arrow.x + margin)
            val yRange = if (arrow.dy > 0) arrow.y until height else 0..arrow.y
            for (y in yRange) for (x in xStart..xEnd) hits += labelAt(labels, y, x)
        }
        board.blockers[label] = (hits intersect expected) - label
    }
    board.order = topologicalOrder(board.blockers)
    if (board.order.size != board.arrows.size) board.reason = "Dependency cycle or unknown obstacle; refusing to guess"
    return board
}

fun predictRemoval(board: Board, label: Int): Board {
    val labels = board.labels.clone()
    for (row in 0 until labels.rows()) for (col in 0 until labels.cols()) {
        if (labelAt(labels, row, col) == label) labels.put(row, col, 0.0)
    }
    val arrows = board.arrows.filterKeys { it != label }.toMutableMap()
    val blockers = board.blockers.filterKeys { it != label }
        .mapValues { (_, deps) -> deps - label }.toMutableMap()
    return Board(board.image, labels, arrows, blockers, topologicalOrder(blockers),
        reason = if (arrows.isEmpty()) "No arrows" else "", noTap = board.noTap.toMutableList())
}

fun tapPoint(board: Board, label: Int): Pair<Int, Int>? {
    val arrow = board.arrows.getValue(label)
    fun blocked(x: Int, y: Int) = board.noTap.any { x0y0x1y1 ->
        x in x0y0x1y1[0]..x0y0x1y1[2] && y in x0y0x1y1[1]..x0y0x1y1[3]
    }
    if (!blocked(arrow.x, arrow.y)) return arrow.x to arrow.y
    val distance = Mat()
    val body = Mat.zeros(board.labels.size(), CvType.CV_8U)
    val points = mutableListOf<Pair<Int, Int>>()
    for (row in 0 until body.rows()) for (col in 0 until body.cols()) {
        if (labelAt(board.labels, row, col) == label) {
            body.put(row, col, 255.0)
            points += col to row
        }
    }
    Imgproc.distanceTransform(body, distance, Imgproc.DIST_L2, 3)
    val keep = points.filter { (x, y) -> !blocked(x, y) }
    if (keep.isEmpty()) {
        body.release(); distance.release(); return null
    }
    val maxDepth = keep.maxOf { (x, y) -> distance.get(y, x)[0] }
    val center = keep.filter { (x, y) -> distance.get(y, x)[0] >= maxDepth - 0.5 }
    val best = center.maxBy { (x, y) ->
        board.noTap.minOfOrNull { rect ->
            val dx = max(max(rect[0] - x, x - rect[2]), 0)
            val dy = max(max(rect[1] - y, y - rect[3]), 0)
            hypot(dx.toDouble(), dy.toDouble())
        } ?: Double.POSITIVE_INFINITY
    }
    body.release(); distance.release()
    return best
}

fun crossCandidates(image: Mat, adCorners: Boolean = false): List<Triple<Double, Int, Int>> {
    val targets = (if (adCorners) listOf(2, 3, 5, 7, 9) else listOf(5, 7, 9)).map { thickness ->
        val target = Mat.zeros(32, 32, CvType.CV_8U)
        Imgproc.line(target, Point(5.0, 5.0), Point(26.0, 26.0), Scalar(255.0), thickness)
        Imgproc.line(target, Point(5.0, 26.0), Point(26.0, 5.0), Scalar(255.0), thickness)
        if (!adCorners) target else {
            val rect = Imgproc.boundingRect(target)
            val cropped = target.submat(rect).clone()
            val resized = Mat()
            Imgproc.resize(cropped, resized, Size(32.0, 32.0))
            target.release(); cropped.release(); resized
        }
    }
    val candidates = mutableListOf<Triple<Double, Int, Int>>()
    val ranges = listOf(Scalar(145.0, 180.0, 200.0) to Scalar(255.0, 255.0, 255.0), Scalar(0.0, 0.0, 0.0) to Scalar(205.0, 205.0, 205.0))
    for ((low, high) in ranges) {
        val mask = Mat()
        Core.inRange(image, low, high, mask)
        val labels = Mat(); val stats = Mat(); val centroids = Mat()
        val count = Imgproc.connectedComponentsWithStats(mask, labels, stats, centroids)
        for (label in 1 until count) {
            val x = stat(stats, label, Imgproc.CC_STAT_LEFT).toInt()
            val y = stat(stats, label, Imgproc.CC_STAT_TOP).toInt()
            val width = stat(stats, label, Imgproc.CC_STAT_WIDTH).toInt()
            val height = stat(stats, label, Imgproc.CC_STAT_HEIGHT).toInt()
            val area = stat(stats, label, Imgproc.CC_STAT_AREA)
            if (width !in 10..70 || height !in 10..70 || width.toDouble() / height !in 0.7..1.4) continue
            val cx = x + width / 2
            val cy = y + height / 2
            val inside = if (adCorners) {
                val corner = (cx < 0.18 * image.cols() || cx > 0.82 * image.cols()) &&
                    (cy < 0.25 * image.rows() || cy > 0.82 * image.rows())
                corner && !(cx > 0.74 * image.cols() && cy < 0.095 * image.rows())
            } else {
                cx > 0.04 * image.cols() && cx < 0.96 * image.cols() && cy > 0.18 * image.rows() && cy < 0.90 * image.rows()
            }
            if (!inside) continue
            val shape = Mat.zeros(height, width, CvType.CV_8U)
            for (row in 0 until height) for (col in 0 until width) {
                if (labelAt(labels, y + row, x + col) == label) shape.put(row, col, 255.0)
            }
            val resized = Mat()
            Imgproc.resize(shape, resized, Size(32.0, 32.0))
            shape.release()
            val score = targets.maxOf { target ->
                val result = Mat()
                Imgproc.matchTemplate(resized, target, result, Imgproc.TM_CCOEFF_NORMED)
                val value = result.get(0, 0)[0]
                result.release()
                value
            }
            resized.release()
            val fill = area / (width * height)
            if (score >= 0.82 && fill > (if (adCorners) 0.15 else 0.30) && fill < 0.85) {
                candidates += Triple(score, cx, cy)
            }
        }
        mask.release(); labels.release(); stats.release(); centroids.release()
    }
    targets.forEach { it.release() }
    return candidates.sortedByDescending { it.first }
}

private fun headTemplate(): Mat {
    val template = Mat.zeros(35, 25, CvType.CV_8U)
    Imgproc.rectangle(template, Point(9.0, 2.0), Point(15.0, 17.0), Scalar(255.0), -1)
    val head = MatOfPoint(Point(4.0, 17.0), Point(20.0, 17.0), Point(12.0, 32.0))
    Imgproc.fillConvexPoly(template, head, Scalar(255.0))
    head.release()
    return template
}

private fun matchHeads(
    mask: Mat,
    labels: Mat,
    targets: Set<Int>,
    arrows: MutableMap<Int, Arrow>,
    templateDown: Mat,
    scale: Double,
    threshold: Double = 0.80,
) {
    DIRECTIONS.forEachIndexed { rotation, (dx, dy) ->
        val template = rot90(templateDown, rotation)
        val result = Mat()
        if (template.rows() <= mask.rows() && template.cols() <= mask.cols()) {
            Imgproc.matchTemplate(mask, template, result, Imgproc.TM_CCOEFF_NORMED)
            for (y in 0 until result.rows()) for (x in 0 until result.cols()) {
                val score = result.get(y, x)[0]
                if (score < threshold) continue
                val cx = x + template.cols() / 2
                val cy = y + template.rows() / 2
                val label = labelAt(labels, cy, cx)
                val previous = arrows[label]
                if (label in targets && (previous == null || score > previous.confidence)) {
                    arrows[label] = Arrow(label, cx, cy, dx, dy, score, scale)
                }
            }
        }
        result.release(); template.release()
    }
}

private fun resizeNearest(base: Mat, scale: Double): Mat {
    val output = Mat()
    Imgproc.resize(base, output, Size(), scale, scale, Imgproc.INTER_NEAREST)
    return output
}

private fun rot90(source: Mat, turns: Int): Mat {
    val output = Mat()
    when (Math.floorMod(turns, 4)) {
        1 -> Core.rotate(source, output, Core.ROTATE_90_COUNTERCLOCKWISE)
        2 -> Core.rotate(source, output, Core.ROTATE_180)
        3 -> Core.rotate(source, output, Core.ROTATE_90_CLOCKWISE)
        else -> source.copyTo(output)
    }
    return output
}

private fun stat(stats: Mat, index: Int, column: Int) = stats.get(index, column)[0]

private fun labelAt(labels: Mat, row: Int, col: Int): Int {
    if (row !in 0 until labels.rows() || col !in 0 until labels.cols()) return 0
    return labels.get(row, col)[0].toInt()
}

private fun overlapCount(mask: Mat, original: Mat): Int {
    var count = 0
    for (row in 0 until mask.rows()) for (col in 0 until mask.cols()) {
        if (mask.u8(row, col) > 0 && original.u8(row, col) > 0) count += 1
    }
    return count
}

private fun differenceCount(left: Mat, right: Mat): Int {
    var count = 0
    for (row in 0 until left.rows()) for (col in 0 until left.cols()) {
        if (left.u8(row, col) != right.u8(row, col)) count += 1
    }
    return count
}

private class MatOfPoint(vararg points: Point) : org.opencv.core.MatOfPoint(*points)
