#include "third_party/clipper.hpp"
#include <jni.h>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>

// pyclipper truncates float coordinates to int64 before Clipper sees the path.
extern "C" int64_t* ocr_offset(const int64_t* points, int count, double distance, int* size) {
    *size = -1;
    try {
        ClipperLib::Path path;
        for (int i = 0; i < count; ++i) path.emplace_back(points[2*i], points[2*i+1]);
        ClipperLib::ClipperOffset offset;
        offset.AddPath(path, ClipperLib::jtRound, ClipperLib::etClosedPolygon);
        ClipperLib::Paths paths;
        offset.Execute(paths, distance);
        // Encode path lengths as well: do not silently merge disjoint polygons.
        std::vector<int64_t> output{static_cast<int64_t>(paths.size())};
        for (const auto& polygon : paths) {
            output.push_back(polygon.size());
            for (const auto& point : polygon) {
                output.push_back(point.X);
                output.push_back(point.Y);
            }
        }
        auto* result = static_cast<int64_t*>(std::malloc(output.size() * sizeof(int64_t)));
        if (!result) return nullptr;
        std::memcpy(result, output.data(), output.size() * sizeof(int64_t));
        *size = output.size();
        return result;
    } catch (...) {
        return nullptr;
    }
}

extern "C" void ocr_offset_free(int64_t* result) { std::free(result); }

extern "C" JNIEXPORT jlongArray JNICALL
Java_com_babanongchang_android_ClipperOffset_nativeExecute(
    JNIEnv* env, jclass, jlongArray coordinates, jdouble distance) {
    if (coordinates == nullptr) return nullptr;
    const jsize count = env->GetArrayLength(coordinates);
    if (count < 0 || count % 2 != 0) return nullptr;
    std::vector<int64_t> points(static_cast<size_t>(count));
    if (count > 0) {
        env->GetLongArrayRegion(coordinates, 0, count, reinterpret_cast<jlong*>(points.data()));
    }
    int size = -1;
    int64_t* raw = ocr_offset(points.data(), count / 2, distance, &size);
    if (raw == nullptr || size < 0) {
        if (raw != nullptr) ocr_offset_free(raw);
        return nullptr;
    }
    jlongArray result = env->NewLongArray(size);
    if (result != nullptr) {
        env->SetLongArrayRegion(result, 0, size, reinterpret_cast<const jlong*>(raw));
    }
    ocr_offset_free(raw);
    return result;
}
