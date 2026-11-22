package com.babanongchang.android

/** Closed round polygon offset, matching the Clipper 6.4.2 path used by RapidOCR. */
object ClipperOffset {
    init {
        System.loadLibrary("ocr_clipper")
    }

    private external fun nativeExecute(coordinates: LongArray, distance: Double): LongArray?

    fun execute(points: List<Pair<Double, Double>>, distance: Double): List<List<Pair<Long, Long>>> {
        val coordinates = LongArray(points.size * 2)
        points.forEachIndexed { index, (x, y) ->
            coordinates[index * 2] = x.toLong()
            coordinates[index * 2 + 1] = y.toLong()
        }
        val raw = nativeExecute(coordinates, distance) ?: error("Clipper polygon offset failed")
        if (raw.isEmpty()) return emptyList()
        val paths = mutableListOf<List<Pair<Long, Long>>>()
        var cursor = 1
        repeat(raw[0].toInt()) {
            val count = raw[cursor].toInt()
            cursor += 1
            paths += List(count) { point ->
                raw[cursor + point * 2] to raw[cursor + point * 2 + 1]
            }
            cursor += count * 2
        }
        return paths
    }
}
