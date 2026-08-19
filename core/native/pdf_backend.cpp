#include "pdf_backend.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>

#include <windows.h>

#include "engine.h"
#include "fpdf_edit.h"
#include "fpdf_ppo.h"
#include "fpdf_save.h"
#include "fpdfview.h"

namespace quickmarkpdf {

PdfPasswordRequiredError::PdfPasswordRequiredError(const std::string& path)
    : std::runtime_error("password required or incorrect: " + path), path_(path) {}

namespace {

using FPDF_InitLibrary_t = void(FPDF_CALLCONV*)();
using FPDF_GetLastError_t = unsigned long(FPDF_CALLCONV*)();
using FPDF_LoadMemDocument64_t = FPDF_DOCUMENT(FPDF_CALLCONV*)(const void*, size_t, FPDF_BYTESTRING);
using FPDF_GetPageCount_t = int(FPDF_CALLCONV*)(FPDF_DOCUMENT);
using FPDF_CloseDocument_t = void(FPDF_CALLCONV*)(FPDF_DOCUMENT);
using FPDF_CreateNewDocument_t = FPDF_DOCUMENT(FPDF_CALLCONV*)();
using FPDF_ImportPagesByIndex_t =
    FPDF_BOOL(FPDF_CALLCONV*)(FPDF_DOCUMENT, FPDF_DOCUMENT, const int*, unsigned long, int);
using FPDF_LoadPage_t = FPDF_PAGE(FPDF_CALLCONV*)(FPDF_DOCUMENT, int);
using FPDF_ClosePage_t = void(FPDF_CALLCONV*)(FPDF_PAGE);
using FPDFPage_SetRotation_t = void(FPDF_CALLCONV*)(FPDF_PAGE, int);
using FPDF_SaveAsCopy_t = FPDF_BOOL(FPDF_CALLCONV*)(FPDF_DOCUMENT, FPDF_FILEWRITE*, FPDF_DWORD);
using FPDF_GetPageWidthF_t = float(FPDF_CALLCONV*)(FPDF_PAGE);
using FPDF_GetPageHeightF_t = float(FPDF_CALLCONV*)(FPDF_PAGE);
using FPDFBitmap_Create_t = FPDF_BITMAP(FPDF_CALLCONV*)(int, int, int);
using FPDFBitmap_FillRect_t = FPDF_BOOL(FPDF_CALLCONV*)(FPDF_BITMAP, int, int, int, int, FPDF_DWORD);
using FPDF_RenderPageBitmap_t = void(FPDF_CALLCONV*)(FPDF_BITMAP, FPDF_PAGE, int, int, int, int, int, int);
using FPDFBitmap_GetBuffer_t = void*(FPDF_CALLCONV*)(FPDF_BITMAP);
using FPDFBitmap_GetStride_t = int(FPDF_CALLCONV*)(FPDF_BITMAP);
using FPDFBitmap_Destroy_t = void(FPDF_CALLCONV*)(FPDF_BITMAP);

struct PdfiumApi {
    FPDF_InitLibrary_t InitLibrary = nullptr;
    FPDF_GetLastError_t GetLastError = nullptr;
    FPDF_LoadMemDocument64_t LoadMemDocument64 = nullptr;
    FPDF_GetPageCount_t GetPageCount = nullptr;
    FPDF_CloseDocument_t CloseDocument = nullptr;
    FPDF_CreateNewDocument_t CreateNewDocument = nullptr;
    FPDF_ImportPagesByIndex_t ImportPagesByIndex = nullptr;
    FPDF_LoadPage_t LoadPage = nullptr;
    FPDF_ClosePage_t ClosePage = nullptr;
    FPDFPage_SetRotation_t SetPageRotation = nullptr;
    FPDF_SaveAsCopy_t SaveAsCopy = nullptr;
    FPDF_GetPageWidthF_t GetPageWidthF = nullptr;
    FPDF_GetPageHeightF_t GetPageHeightF = nullptr;
    FPDFBitmap_Create_t BitmapCreate = nullptr;
    FPDFBitmap_FillRect_t BitmapFillRect = nullptr;
    FPDF_RenderPageBitmap_t RenderPageBitmap = nullptr;
    FPDFBitmap_GetBuffer_t BitmapGetBuffer = nullptr;
    FPDFBitmap_GetStride_t BitmapGetStride = nullptr;
    FPDFBitmap_Destroy_t BitmapDestroy = nullptr;
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
        loaded.CreateNewDocument = load_symbol<FPDF_CreateNewDocument_t>(module, "FPDF_CreateNewDocument");
        loaded.ImportPagesByIndex =
            load_symbol<FPDF_ImportPagesByIndex_t>(module, "FPDF_ImportPagesByIndex");
        loaded.LoadPage = load_symbol<FPDF_LoadPage_t>(module, "FPDF_LoadPage");
        loaded.ClosePage = load_symbol<FPDF_ClosePage_t>(module, "FPDF_ClosePage");
        loaded.SetPageRotation = load_symbol<FPDFPage_SetRotation_t>(module, "FPDFPage_SetRotation");
        loaded.SaveAsCopy = load_symbol<FPDF_SaveAsCopy_t>(module, "FPDF_SaveAsCopy");
        loaded.GetPageWidthF = load_symbol<FPDF_GetPageWidthF_t>(module, "FPDF_GetPageWidthF");
        loaded.GetPageHeightF = load_symbol<FPDF_GetPageHeightF_t>(module, "FPDF_GetPageHeightF");
        loaded.BitmapCreate = load_symbol<FPDFBitmap_Create_t>(module, "FPDFBitmap_Create");
        loaded.BitmapFillRect = load_symbol<FPDFBitmap_FillRect_t>(module, "FPDFBitmap_FillRect");
        loaded.RenderPageBitmap = load_symbol<FPDF_RenderPageBitmap_t>(module, "FPDF_RenderPageBitmap");
        loaded.BitmapGetBuffer = load_symbol<FPDFBitmap_GetBuffer_t>(module, "FPDFBitmap_GetBuffer");
        loaded.BitmapGetStride = load_symbol<FPDFBitmap_GetStride_t>(module, "FPDFBitmap_GetStride");
        loaded.BitmapDestroy = load_symbol<FPDFBitmap_Destroy_t>(module, "FPDFBitmap_Destroy");
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

std::string read_file(const std::string& path) {
    std::ifstream input(std::filesystem::u8path(path), std::ios::binary);
    if (!input) throw std::runtime_error("cannot open PDF: " + path);
    std::string data((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    if (data.empty()) throw std::runtime_error("cannot open PDF: " + path);
    return data;
}

// Owns the byte buffer backing a document opened with FPDF_LoadMemDocument64:
// pdfium keeps a reference to the buffer rather than copying it, so it must
// outlive the FPDF_DOCUMENT handle.
struct OpenSource {
    std::string bytes;
    FPDF_DOCUMENT doc = nullptr;
};

FPDF_DOCUMENT open_source(const PdfiumApi& api, const std::string& path, const std::string& password,
                           std::string& bytes_out) {
    bytes_out = read_file(path);
    const char* password_arg = password.empty() ? nullptr : password.c_str();
    FPDF_DOCUMENT doc = api.LoadMemDocument64(bytes_out.data(), bytes_out.size(), password_arg);
    if (!doc) {
        const auto code = api.GetLastError();
        if (code == FPDF_ERR_PASSWORD) throw PdfPasswordRequiredError(path);
        throw std::runtime_error("cannot open PDF: " + path + " (" + describe_error(code) + ")");
    }
    return doc;
}

struct FileWriter : FPDF_FILEWRITE {
    std::ofstream* stream = nullptr;

    static int write_block(FPDF_FILEWRITE* self, const void* data, unsigned long size) {
        auto* writer = static_cast<FileWriter*>(self);
        writer->stream->write(static_cast<const char*>(data), static_cast<std::streamsize>(size));
        return writer->stream->good() ? 1 : 0;
    }
};

}  // namespace

PdfDocumentInfo PdfBackend::inspect(const std::string& path, const std::string& password) {
    const auto& api = pdfium();
    std::string bytes;
    FPDF_DOCUMENT document = open_source(api, path, password, bytes);

    const int pages = api.GetPageCount(document);
    api.CloseDocument(document);
    if (pages <= 0) throw std::runtime_error("PDF page tree could not be inspected: " + path);
    return {path, static_cast<std::size_t>(pages)};
}

RenderedPage PdfBackend::render_page(const std::string& path, std::size_t page_index, int target_width,
                                      const std::string& password) {
    if (target_width < 1) throw std::invalid_argument("target_width must be at least 1");

    const auto& api = pdfium();
    std::string bytes;
    FPDF_DOCUMENT document = open_source(api, path, password, bytes);

    FPDF_PAGE page = api.LoadPage(document, static_cast<int>(page_index));
    if (!page) {
        api.CloseDocument(document);
        throw std::runtime_error("page not found: " + path + " page " + std::to_string(page_index));
    }

    const float page_width = api.GetPageWidthF(page);
    const float page_height = api.GetPageHeightF(page);
    const float scale = page_width > 0 ? static_cast<float>(target_width) / page_width : 1.0f;
    const int target_height = std::max(1, static_cast<int>(std::lround(page_height * scale)));

    FPDF_BITMAP bitmap = api.BitmapCreate(target_width, target_height, /*alpha=*/1);
    if (!bitmap) {
        api.ClosePage(page);
        api.CloseDocument(document);
        throw std::runtime_error("failed to allocate render target for: " + path);
    }

    api.BitmapFillRect(bitmap, 0, 0, target_width, target_height, 0xFFFFFFFFu);
    api.RenderPageBitmap(bitmap, page, 0, 0, target_width, target_height, /*rotate=*/0, FPDF_ANNOT);

    RenderedPage result;
    result.width = target_width;
    result.height = target_height;
    result.rgba.resize(static_cast<std::size_t>(target_width) * static_cast<std::size_t>(target_height) * 4);

    const auto* buffer = static_cast<const unsigned char*>(api.BitmapGetBuffer(bitmap));
    const int stride = api.BitmapGetStride(bitmap);
    for (int y = 0; y < target_height; ++y) {
        const unsigned char* src_row = buffer + static_cast<std::size_t>(y) * stride;
        unsigned char* dst_row = result.rgba.data() + static_cast<std::size_t>(y) * target_width * 4;
        for (int x = 0; x < target_width; ++x) {
            // pdfium's BGRA -> canvas ImageData's RGBA.
            dst_row[x * 4 + 0] = src_row[x * 4 + 2];
            dst_row[x * 4 + 1] = src_row[x * 4 + 1];
            dst_row[x * 4 + 2] = src_row[x * 4 + 0];
            dst_row[x * 4 + 3] = src_row[x * 4 + 3];
        }
    }

    api.BitmapDestroy(bitmap);
    api.ClosePage(page);
    api.CloseDocument(document);
    return result;
}

void PdfBackend::save(const WorkingDocument& document, const std::string& output_path,
                       const std::unordered_map<std::string, std::string>& passwords) {
    const auto& api = pdfium();

    FPDF_DOCUMENT dest = api.CreateNewDocument();
    if (!dest) throw std::runtime_error("failed to create output PDF: " + output_path);

    std::unordered_map<std::string, OpenSource> opened;
    auto close_all = [&] {
        for (auto& [path, source] : opened) {
            if (source.doc) api.CloseDocument(source.doc);
        }
        api.CloseDocument(dest);
    };

    try {
        for (std::size_t i = 0; i < document.page_count(); ++i) {
            const auto& ref = document.page(i);

            auto it = opened.find(ref.source_path);
            if (it == opened.end()) {
                std::string password;
                if (auto pw = passwords.find(ref.source_path); pw != passwords.end()) password = pw->second;

                OpenSource source;
                source.doc = open_source(api, ref.source_path, password, source.bytes);
                it = opened.emplace(ref.source_path, std::move(source)).first;
            }

            const int source_page_index = static_cast<int>(ref.source_page);
            const int dest_index = static_cast<int>(i);
            if (!api.ImportPagesByIndex(dest, it->second.doc, &source_page_index, 1, dest_index)) {
                throw std::runtime_error("failed to import page " + std::to_string(ref.source_page) +
                                          " from " + ref.source_path);
            }

            if (FPDF_PAGE dest_page = api.LoadPage(dest, dest_index)) {
                api.SetPageRotation(dest_page, (ref.rotation / 90) % 4);
                api.ClosePage(dest_page);
            }
        }

        std::ofstream output(std::filesystem::u8path(output_path), std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("cannot open output path for writing: " + output_path);

        FileWriter writer{};
        writer.version = 1;
        writer.WriteBlock = &FileWriter::write_block;
        writer.stream = &output;

        if (!api.SaveAsCopy(dest, &writer, 0)) {
            throw std::runtime_error("failed to save PDF: " + output_path);
        }
    } catch (...) {
        close_all();
        throw;
    }
    close_all();
}

}  // namespace quickmarkpdf
