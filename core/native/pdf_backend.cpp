#include "pdf_backend.h"

#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

#include <windows.h>

#include "fpdfview.h"

namespace quickmarkpdf {
namespace {

using FPDF_InitLibrary_t = void(FPDF_CALLCONV*)();
using FPDF_GetLastError_t = unsigned long(FPDF_CALLCONV*)();
using FPDF_LoadMemDocument64_t = FPDF_DOCUMENT(FPDF_CALLCONV*)(const void*, size_t, FPDF_BYTESTRING);
using FPDF_GetPageCount_t = int(FPDF_CALLCONV*)(FPDF_DOCUMENT);
using FPDF_CloseDocument_t = void(FPDF_CALLCONV*)(FPDF_DOCUMENT);

struct PdfiumApi {
    FPDF_InitLibrary_t InitLibrary = nullptr;
    FPDF_GetLastError_t GetLastError = nullptr;
    FPDF_LoadMemDocument64_t LoadMemDocument64 = nullptr;
    FPDF_GetPageCount_t GetPageCount = nullptr;
    FPDF_CloseDocument_t CloseDocument = nullptr;
};

template <typename Fn>
Fn load_symbol(HMODULE module, const char* name) {
    auto* address = ::GetProcAddress(module, name);
    if (!address) throw std::runtime_error(std::string("pdfium.dll is missing export: ") + name);
    return reinterpret_cast<Fn>(address);
}

// pdfium.dll is copied next to every executable that links pdf_backend.cpp
// (see the CMake POST_BUILD steps), so the plain module name resolves via
// the application-directory search rule.
const PdfiumApi& pdfium() {
    static const PdfiumApi api = [] {
        HMODULE module = ::LoadLibraryW(L"pdfium.dll");
        if (!module) throw std::runtime_error("failed to load pdfium.dll");
        PdfiumApi loaded;
        loaded.InitLibrary = load_symbol<FPDF_InitLibrary_t>(module, "FPDF_InitLibrary");
        loaded.GetLastError = load_symbol<FPDF_GetLastError_t>(module, "FPDF_GetLastError");
        loaded.LoadMemDocument64 = load_symbol<FPDF_LoadMemDocument64_t>(module, "FPDF_LoadMemDocument64");
        loaded.GetPageCount = load_symbol<FPDF_GetPageCount_t>(module, "FPDF_GetPageCount");
        loaded.CloseDocument = load_symbol<FPDF_CloseDocument_t>(module, "FPDF_CloseDocument");
        loaded.InitLibrary();
        return loaded;
    }();
    return api;
}

std::string describe_error(unsigned long code) {
    switch (code) {
        case FPDF_ERR_FILE: return "file not found or could not be opened";
        case FPDF_ERR_FORMAT: return "file is not a PDF or is corrupted";
        case FPDF_ERR_PASSWORD: return "password required or incorrect";
        case FPDF_ERR_SECURITY: return "unsupported security scheme";
        case FPDF_ERR_PAGE: return "page not found or content error";
        default: return "unknown error";
    }
}

}  // namespace

PdfDocumentInfo PdfBackend::inspect(const std::string& path) {
    std::ifstream input(std::filesystem::u8path(path), std::ios::binary);
    if (!input) throw std::runtime_error("cannot open PDF");
    const std::string data((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    if (data.empty()) throw std::runtime_error("cannot open PDF");

    const auto& api = pdfium();
    FPDF_DOCUMENT document = api.LoadMemDocument64(data.data(), data.size(), nullptr);
    if (!document) throw std::runtime_error("cannot inspect PDF: " + describe_error(api.GetLastError()));

    const int pages = api.GetPageCount(document);
    api.CloseDocument(document);
    if (pages <= 0) throw std::runtime_error("PDF page tree could not be inspected");
    return {path, static_cast<std::size_t>(pages)};
}

}  // namespace quickmarkpdf
