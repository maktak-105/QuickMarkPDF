#include "image_io.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace quickmarkpdf {

namespace {

std::uint32_t crc32_of(const unsigned char* data, std::size_t length, std::uint32_t crc = 0xFFFFFFFFu) {
    static const auto table = [] {
        std::array<std::uint32_t, 256> t{};
        for (std::uint32_t n = 0; n < 256; ++n) {
            std::uint32_t c = n;
            for (int k = 0; k < 8; ++k) {
                c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            }
            t[n] = c;
        }
        return t;
    }();
    for (std::size_t i = 0; i < length; ++i) {
        crc = table[(crc ^ data[i]) & 0xFFu] ^ (crc >> 8);
    }
    return crc;
}

std::uint32_t crc32_final(const unsigned char* data, std::size_t length) {
    return crc32_of(data, length) ^ 0xFFFFFFFFu;
}

std::uint32_t adler32_of(const unsigned char* data, std::size_t length) {
    std::uint32_t a = 1, b = 0;
    constexpr std::uint32_t kMod = 65521u;
    std::size_t i = 0;
    while (i < length) {
        // Process in chunks small enough that b can't overflow before a modulo.
        std::size_t chunk = std::min<std::size_t>(length - i, 5552);
        for (std::size_t j = 0; j < chunk; ++j, ++i) {
            a += data[i];
            b += a;
        }
        a %= kMod;
        b %= kMod;
    }
    return (b << 16) | a;
}

void append_be32(std::vector<unsigned char>& out, std::uint32_t value) {
    out.push_back(static_cast<unsigned char>((value >> 24) & 0xFF));
    out.push_back(static_cast<unsigned char>((value >> 16) & 0xFF));
    out.push_back(static_cast<unsigned char>((value >> 8) & 0xFF));
    out.push_back(static_cast<unsigned char>(value & 0xFF));
}

void append_le16(std::vector<unsigned char>& out, std::uint16_t value) {
    out.push_back(static_cast<unsigned char>(value & 0xFF));
    out.push_back(static_cast<unsigned char>((value >> 8) & 0xFF));
}

void write_chunk(std::vector<unsigned char>& out, const char type[4], const std::vector<unsigned char>& data) {
    append_be32(out, static_cast<std::uint32_t>(data.size()));
    std::vector<unsigned char> type_and_data(type, type + 4);
    type_and_data.insert(type_and_data.end(), data.begin(), data.end());
    out.insert(out.end(), type_and_data.begin(), type_and_data.end());
    append_be32(out, crc32_final(type_and_data.data(), type_and_data.size()));
}

// Deflate "stored" (uncompressed) blocks, wrapped in a minimal zlib header
// and trailer -- a valid, if suboptimal, zlib stream (RFC 1950 / RFC 1951
// section 3.2.4).
std::vector<unsigned char> zlib_store(const std::vector<unsigned char>& raw) {
    std::vector<unsigned char> out;
    out.push_back(0x78);
    out.push_back(0x01);

    constexpr std::size_t kMaxBlock = 65535;
    std::size_t offset = 0;
    if (raw.empty()) {
        out.push_back(0x01);  // final, empty stored block
        append_le16(out, 0);
        append_le16(out, 0xFFFF);
    }
    while (offset < raw.size()) {
        const std::size_t remaining = raw.size() - offset;
        const std::size_t block_len = std::min(remaining, kMaxBlock);
        const bool is_final = (offset + block_len) >= raw.size();
        out.push_back(is_final ? 0x01 : 0x00);
        append_le16(out, static_cast<std::uint16_t>(block_len));
        append_le16(out, static_cast<std::uint16_t>(~static_cast<std::uint16_t>(block_len)));
        out.insert(out.end(), raw.begin() + static_cast<long>(offset),
                   raw.begin() + static_cast<long>(offset + block_len));
        offset += block_len;
    }

    append_be32(out, adler32_of(raw.data(), raw.size()));
    return out;
}

}  // namespace

void write_png_rgb(const std::string& path, int width, int height, const std::vector<unsigned char>& rgba) {
    if (width < 1 || height < 1) throw std::invalid_argument("write_png_rgb: width/height must be >= 1");
    if (rgba.size() != static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4) {
        throw std::invalid_argument("write_png_rgb: rgba buffer size does not match width*height*4");
    }

    std::vector<unsigned char> raw;
    raw.reserve(static_cast<std::size_t>(height) * (1 + static_cast<std::size_t>(width) * 3));
    for (int y = 0; y < height; ++y) {
        raw.push_back(0);  // filter type 0 (None) for every scanline
        const unsigned char* row = rgba.data() + static_cast<std::size_t>(y) * width * 4;
        for (int x = 0; x < width; ++x) {
            raw.push_back(row[x * 4 + 0]);
            raw.push_back(row[x * 4 + 1]);
            raw.push_back(row[x * 4 + 2]);
        }
    }

    std::vector<unsigned char> file_data = {0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A};

    std::vector<unsigned char> ihdr;
    append_be32(ihdr, static_cast<std::uint32_t>(width));
    append_be32(ihdr, static_cast<std::uint32_t>(height));
    ihdr.push_back(8);  // bit depth
    ihdr.push_back(2);  // color type: RGB
    ihdr.push_back(0);  // compression method
    ihdr.push_back(0);  // filter method
    ihdr.push_back(0);  // interlace method
    write_chunk(file_data, "IHDR", ihdr);

    write_chunk(file_data, "IDAT", zlib_store(raw));
    write_chunk(file_data, "IEND", {});

    std::ofstream out(std::filesystem::u8path(path), std::ios::binary | std::ios::trunc);
    if (!out) throw std::runtime_error("cannot open output path for writing: " + path);
    out.write(reinterpret_cast<const char*>(file_data.data()), static_cast<std::streamsize>(file_data.size()));
    if (!out) throw std::runtime_error("failed writing PNG: " + path);
}

}  // namespace quickmarkpdf
