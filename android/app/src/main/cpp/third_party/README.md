# Clipper 6.4.2

`clipper.cpp` and `clipper.hpp` are unmodified sources from pyclipper 1.4.0,
the desktop dependency. Clipper's Boost Software License is in both source headers;
`LICENSE` is the pyclipper distribution's MIT license.

Source: https://pypi.org/project/pyclipper/1.4.0/

Source archive SHA-256:
`9882bd889f27da78add4dd6f881d25697efc740bf840274e749988d25496c8e1`

The small C ABI in `../clipper_bridge.cpp` exposes only the closed-polygon round
offset used by RapidOCR. It preserves integer coordinate truncation and Clipper's
default offset parameters, rather than approximating the expansion with another
geometry algorithm.
