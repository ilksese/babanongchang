cmake_minimum_required(VERSION 3.22)
project(ocr_clipper)
add_library(ocr_clipper SHARED clipper_bridge.cpp third_party/clipper.cpp)
target_compile_features(ocr_clipper PRIVATE cxx_std_17)
