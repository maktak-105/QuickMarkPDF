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

}  // namespace quickmarkpdf
