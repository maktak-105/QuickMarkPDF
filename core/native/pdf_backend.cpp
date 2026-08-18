#include "pdf_backend.h"

#include <cctype>
#include <filesystem>
#include <fstream>
#include <stdexcept>

namespace quickmarkpdf {
namespace {
bool matches_page_object(const std::string& data, std::size_t offset) {
    constexpr char type_token[] = "/Type";
    constexpr char page_token[] = "/Page";
    if (data.compare(offset, sizeof(type_token) - 1, type_token) != 0) return false;
    auto cursor = offset + sizeof(type_token) - 1;
    while (cursor < data.size() && std::isspace(static_cast<unsigned char>(data[cursor]))) ++cursor;
    if (data.compare(cursor, sizeof(page_token) - 1, page_token) != 0) return false;
    const auto after = cursor + sizeof(page_token) - 1;
    return after == data.size() || !std::isalpha(static_cast<unsigned char>(data[after]));
}
}  // namespace

PdfDocumentInfo PdfBackend::inspect(const std::string& path) {
    std::ifstream input(std::filesystem::u8path(path), std::ios::binary);
    if (!input) throw std::runtime_error("cannot open PDF");
    const std::string data((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    if (data.rfind("%PDF-", 0) != 0) throw std::runtime_error("file is not a PDF");

    std::size_t pages = 0;
    for (std::size_t offset = 0; offset < data.size(); ++offset) {
        if (data[offset] == '/' && matches_page_object(data, offset)) ++pages;
    }
    if (pages == 0) throw std::runtime_error("PDF page tree could not be inspected");
    return {path, pages};
}
}  // namespace quickmarkpdf
