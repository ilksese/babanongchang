"""RapidOCR's polygon-offset API using the same Clipper 6.4.2 as pyclipper."""

import ctypes

JT_ROUND = 1
ET_CLOSEDPOLYGON = 0
_library = ctypes.CDLL("libocr_clipper.so")
_library.ocr_offset.argtypes = [ctypes.POINTER(ctypes.c_int64), ctypes.c_int,
                                ctypes.c_double, ctypes.POINTER(ctypes.c_int)]
_library.ocr_offset.restype = ctypes.POINTER(ctypes.c_int64)
_library.ocr_offset_free.argtypes = [ctypes.POINTER(ctypes.c_int64)]


class PyclipperOffset:
    def AddPath(self, points, join_type, end_type):
        if join_type != JT_ROUND or end_type != ET_CLOSEDPOLYGON:
            raise ValueError("Only closed round offsets used by RapidOCR are supported")
        self.points = [int(value) for point in points for value in point]

    def Execute(self, distance):
        points = (ctypes.c_int64 * len(self.points))(*self.points)
        size = ctypes.c_int()
        result = _library.ocr_offset(points, len(self.points) // 2, distance, ctypes.byref(size))
        if not result or size.value < 0:
            raise RuntimeError("Clipper polygon offset failed")
        try:
            paths, cursor = [], 1
            for _ in range(result[0]):
                count = result[cursor]
                cursor += 1
                paths.append([[result[cursor + 2*i], result[cursor + 2*i + 1]] for i in range(count)])
                cursor += count * 2
            return paths
        finally:
            _library.ocr_offset_free(result)
