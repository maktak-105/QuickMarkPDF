#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace quickmarkpdf {

// Writes an 8-bit RGB PNG (alpha dropped -- PDF pages render opaque) with no
// third-party dependency: a hand-rolled PNG encoder using zlib "stored"
// (uncompressed) deflate blocks. Produces a valid, larger-than-optimal PNG
// -- fine for page-image export, where correctness matters far more than
// file size. `rgba` must be `width * height * 4` bytes, row-major,
// top-left origin (matches PdfBackend::RenderedPage).
//
// Throws std::runtime_error if the file cannot be written.
void write_png_rgb(const std::string& path, int width, int height, const std::vector<unsigned char>& rgba);

// Writes an 8-bit RGB JPEG via Windows Imaging Component (WIC) -- unlike
// PNG, a correct JPEG encoder (DCT + quantization + Huffman coding) isn't
// practical to hand-roll, and this project already targets Windows only
// (WebView2, Win32 dialogs), so reaching for the OS's own encoder is the
// pragmatic choice rather than a third-party library. `quality` is 1-100,
// matching the Python baseline's JPEG quality slider. Initializes and
// uninitializes COM internally for the duration of the call.
//
// Throws std::runtime_error if the file cannot be written or WIC is
// unavailable.
void write_jpeg_rgb(const std::string& path, int width, int height, const std::vector<unsigned char>& rgba,
                     int quality);

}  // namespace quickmarkpdf
