#include <windows.h>
#include <wincodec.h>
#include <wincred.h>
#include <wincrypt.h>
#include <shobjidl.h>
#include <unknwn.h>
#include <WebView2.h>

#include <atomic>
#include <cwctype>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "engine.h"
#include "pdf_backend.h"

namespace {

// =====================
// WebView2 event handler boilerplate
// =====================
//
// The MSVC-only Microsoft::WRL::Callback<>/ComPtr<> helpers
// (<wrl.h>/<wrl/event.h>) aren't available under this project's MinGW-w64
// toolchain -- <wrl/event.h> doesn't exist in its header set at all (unlike
// <wrl.h>, confirmed by trying to compile it). These three classes hand-roll
// the same "wrap a std::function as a one-off COM callback" pattern with a
// raw IUnknown implementation instead, matching the approach already proven
// to build and run in this workspace's QuickFolderSize/core/native/
// webview_main.cpp.

class EnvCompletedHandler : public ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler {
    std::function<HRESULT(HRESULT, ICoreWebView2Environment*)> fn_;
    std::atomic<ULONG> ref_{1};

public:
    explicit EnvCompletedHandler(std::function<HRESULT(HRESULT, ICoreWebView2Environment*)> fn)
        : fn_(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler) {
            *ppv = static_cast<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++ref_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = --ref_;
        if (remaining == 0) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Environment* environment) override {
        return fn_(result, environment);
    }
};

class ControllerCompletedHandler : public ICoreWebView2CreateCoreWebView2ControllerCompletedHandler {
    std::function<HRESULT(HRESULT, ICoreWebView2Controller*)> fn_;
    std::atomic<ULONG> ref_{1};

public:
    explicit ControllerCompletedHandler(std::function<HRESULT(HRESULT, ICoreWebView2Controller*)> fn)
        : fn_(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2CreateCoreWebView2ControllerCompletedHandler) {
            *ppv = static_cast<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++ref_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = --ref_;
        if (remaining == 0) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT result, ICoreWebView2Controller* controller) override {
        return fn_(result, controller);
    }
};

class WebMessageReceivedHandler : public ICoreWebView2WebMessageReceivedEventHandler {
    std::function<HRESULT(ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs*)> fn_;
    std::atomic<ULONG> ref_{1};

public:
    explicit WebMessageReceivedHandler(
        std::function<HRESULT(ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs*)> fn)
        : fn_(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2WebMessageReceivedEventHandler) {
            *ppv = static_cast<ICoreWebView2WebMessageReceivedEventHandler*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++ref_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = --ref_;
        if (remaining == 0) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2* sender, ICoreWebView2WebMessageReceivedEventArgs* args) override {
        return fn_(sender, args);
    }
};

// Minimal RAII for CoCreateInstance-created interfaces (IFileOpenDialog,
// IShellItem, the WIC objects) -- std::unique_ptr with a Release()-calling
// deleter, so early returns can't leak a reference. Deliberately not
// Microsoft::WRL::ComPtr (see the note above); this needs nothing beyond
// the standard library.
template <typename T>
struct ComDeleter {
    void operator()(T* p) const {
        if (p) p->Release();
    }
};
template <typename T>
using ComPtr = std::unique_ptr<T, ComDeleter<T>>;

// =====================
// Global session state
// =====================

HWND g_window = nullptr;
ICoreWebView2Controller* g_controller = nullptr;
ICoreWebView2* g_webview = nullptr;
quickmarkpdf::WorkingDocument g_document;
// Password used to open each source file, so PdfBackend::save can reopen
// encrypted sources without asking again.
std::unordered_map<std::string, std::string> g_source_passwords;

// =====================
// String / JSON helpers
// =====================
//
// static/js/app.js is the only producer of the request messages below and
// the only consumer of the response messages, and its shape never varies,
// so a couple of targeted lookups are enough -- no need for a general JSON
// parser/serializer here.

std::wstring file_url(const std::filesystem::path& path) {
    return L"file:///" + path.generic_wstring();
}

std::wstring json_string(const std::wstring& value) {
    std::wstring escaped = L"\"";
    for (const auto character : value) {
        if (character == L'\\' || character == L'\"') escaped += L'\\';
        escaped += character;
    }
    escaped += L"\"";
    return escaped;
}

std::string wide_to_utf8(const std::wstring& value) {
    if (value.empty()) return {};
    const int size = ::WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr,
                                            0, nullptr, nullptr);
    std::string result(static_cast<std::size_t>(size), '\0');
    ::WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size,
                          nullptr, nullptr);
    return result;
}

int extract_int(const std::wstring& message, const wchar_t* key, int fallback) {
    const std::wstring needle = std::wstring(L"\"") + key + L"\":";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return fallback;
    auto cursor = pos + needle.size();
    while (cursor < message.size() && message[cursor] == L' ') ++cursor;
    bool negative = cursor < message.size() && message[cursor] == L'-';
    if (negative) ++cursor;
    int value = 0;
    bool any_digit = false;
    while (cursor < message.size() && std::iswdigit(message[cursor])) {
        value = value * 10 + (message[cursor] - L'0');
        ++cursor;
        any_digit = true;
    }
    if (!any_digit) return fallback;
    return negative ? -value : value;
}

std::vector<std::size_t> extract_size_t_array(const std::wstring& message, const wchar_t* key) {
    std::vector<std::size_t> result;
    const std::wstring needle = std::wstring(L"\"") + key + L"\":[";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return result;
    auto cursor = pos + needle.size();
    while (cursor < message.size() && message[cursor] != L']') {
        while (cursor < message.size() && (message[cursor] == L' ' || message[cursor] == L',')) ++cursor;
        if (cursor >= message.size() || message[cursor] == L']') break;
        std::size_t value = 0;
        bool any_digit = false;
        while (cursor < message.size() && std::iswdigit(message[cursor])) {
            value = value * 10 + static_cast<std::size_t>(message[cursor] - L'0');
            ++cursor;
            any_digit = true;
        }
        if (any_digit) result.push_back(value);
    }
    return result;
}

std::string base64_encode(const unsigned char* data, DWORD size) {
    DWORD out_len = 0;
    if (!CryptBinaryToStringA(data, size, CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF, nullptr, &out_len)) {
        return {};
    }
    std::string out(out_len, '\0');
    if (!CryptBinaryToStringA(data, size, CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF, out.data(), &out_len)) {
        return {};
    }
    out.resize(out_len);
    return out;
}

std::wstring pages_json() {
    std::wstring pages = L"[";
    for (std::size_t i = 0; i < g_document.page_count(); ++i) {
        if (i > 0) pages += L",";
        const auto& page = g_document.page(i);
        pages += L"{\"path\":" + json_string(std::filesystem::u8path(page.source_path).wstring()) +
                 L",\"source_page\":" + std::to_wstring(page.source_page) + L",\"rotation\":" +
                 std::to_wstring(page.rotation) + L"}";
    }
    pages += L"]";
    return pages;
}

void post_document_state(const wchar_t* message_type) {
    if (!g_webview) return;
    const std::wstring response = std::wstring(L"{\"type\":\"") + message_type + L"\",\"page_count\":" +
                                   std::to_wstring(g_document.page_count()) + L",\"dirty\":" +
                                   (g_document.is_dirty() ? L"true" : L"false") + L",\"can_undo\":" +
                                   (g_document.can_undo() ? L"true" : L"false") + L",\"pages\":" +
                                   pages_json() + L"}";
    g_webview->PostWebMessageAsString(response.c_str());
}

void post_status(const wchar_t* text) {
    if (!g_webview) return;
    const std::wstring response = std::wstring(L"{\"type\":\"backend_status\",\"message\":") +
                                   json_string(text) + L"}";
    g_webview->PostWebMessageAsString(response.c_str());
}

// =====================
// Native dialogs
// =====================

// GetOpenFileNameW with OFN_ALLOWMULTISELECT + OFN_EXPLORER returns either a
// single null-terminated full path (one file picked), or a directory
// followed by one null-terminated filename per picked file, the whole
// group terminated by an extra null -- see OPENFILENAME's documented
// multi-select buffer layout.
std::vector<std::filesystem::path> parse_multiselect_buffer(const wchar_t* buffer) {
    std::vector<std::filesystem::path> result;
    const wchar_t* cursor = buffer;
    const std::wstring first(cursor);
    if (first.empty()) return result;
    cursor += first.size() + 1;
    if (*cursor == L'\0') {
        result.emplace_back(first);
        return result;
    }
    const std::filesystem::path directory(first);
    while (*cursor != L'\0') {
        const std::wstring name(cursor);
        result.push_back(directory / name);
        cursor += name.size() + 1;
    }
    return result;
}

std::vector<std::filesystem::path> prompt_open_pdfs() {
    std::vector<wchar_t> buffer(65536, L'\0');
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = g_window;
    dialog.lpstrFilter = L"PDF files (*.pdf)\0*.pdf\0All files (*.*)\0*.*\0";
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_ALLOWMULTISELECT;
    if (!GetOpenFileNameW(&dialog)) {
        // CommDlgExtendedError() is 0 when the user simply cancelled/closed
        // the dialog; anything else is a real failure that would otherwise
        // fail completely silently (no dialog, no error, nothing).
        const DWORD error = CommDlgExtendedError();
        if (error != 0) {
            post_status((L"ファイル選択ダイアログを開けませんでした (エラーコード: " + std::to_wstring(error) + L")")
                             .c_str());
        }
        return {};
    }
    return parse_multiselect_buffer(buffer.data());
}

std::optional<std::filesystem::path> prompt_save_pdf() {
    wchar_t selected[MAX_PATH]{};
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = g_window;
    dialog.lpstrFilter = L"PDF files (*.pdf)\0*.pdf\0\0";
    dialog.lpstrFile = selected;
    dialog.nMaxFile = MAX_PATH;
    dialog.lpstrDefExt = L"pdf";
    dialog.Flags = OFN_PATHMUSTEXIST | OFN_OVERWRITEPROMPT;
    if (!GetSaveFileNameW(&dialog)) return std::nullopt;
    return std::filesystem::path(selected);
}

// Folder picker for image export, via the modern IFileOpenDialog +
// FOS_PICKFOLDERS (the SHBrowseForFolder-era API is deprecated).
std::optional<std::filesystem::path> prompt_pick_folder() {
    IFileOpenDialog* raw_dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&raw_dialog)))) {
        return std::nullopt;
    }
    ComPtr<IFileOpenDialog> dialog(raw_dialog);

    DWORD options = 0;
    dialog->GetOptions(&options);
    dialog->SetOptions(options | FOS_PICKFOLDERS | FOS_PATHMUSTEXIST | FOS_FORCEFILESYSTEM);
    if (FAILED(dialog->Show(g_window))) return std::nullopt;

    IShellItem* raw_item = nullptr;
    if (FAILED(dialog->GetResult(&raw_item))) return std::nullopt;
    ComPtr<IShellItem> item(raw_item);

    PWSTR raw_path = nullptr;
    if (FAILED(item->GetDisplayName(SIGDN_FILESYSPATH, &raw_path))) return std::nullopt;
    std::filesystem::path result(raw_path);
    CoTaskMemFree(raw_path);
    return result;
}

// Native password prompt for an encrypted source file. Built on CredUI
// rather than a hand-rolled dialog template, since a single documented API
// call is far less likely to have a subtle mistake I can't catch without
// interactively running the dialog myself. The username field it shows is
// unused (there's no username concept for a PDF password) -- it's just
// prefilled with the file name for context.
std::optional<std::string> prompt_for_password(const std::filesystem::path& path, bool retry) {
    CREDUI_INFOW ui_info{};
    ui_info.cbSize = sizeof(ui_info);
    ui_info.hwndParent = g_window;
    const std::wstring message = L"パスワード付きPDFです: " + path.filename().wstring();
    const std::wstring caption = L"PDFパスワードの入力";
    ui_info.pszMessageText = message.c_str();
    ui_info.pszCaptionText = caption.c_str();

    wchar_t username[CREDUI_MAX_USERNAME_LENGTH + 1]{};
    wchar_t password[CREDUI_MAX_PASSWORD_LENGTH + 1]{};
    const auto filename = path.filename().wstring();
    wcsncpy_s(username, filename.c_str(), _TRUNCATE);
    BOOL save = FALSE;

    const DWORD result = CredUIPromptForCredentialsW(
        &ui_info, filename.c_str(), nullptr, retry ? static_cast<DWORD>(ERROR_LOGON_FAILURE) : 0, username,
        CREDUI_MAX_USERNAME_LENGTH + 1, password, CREDUI_MAX_PASSWORD_LENGTH + 1, &save,
        CREDUI_FLAGS_GENERIC_CREDENTIALS | CREDUI_FLAGS_DO_NOT_PERSIST | CREDUI_FLAGS_EXCLUDE_CERTIFICATES);
    if (result != NO_ERROR) return std::nullopt;
    return wide_to_utf8(password);
}

// =====================
// Image export (PNG via WIC)
// =====================

bool write_png(const std::filesystem::path& path, const quickmarkpdf::RenderedPage& page) {
    IWICImagingFactory* raw_factory = nullptr;
    if (FAILED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
                                 IID_PPV_ARGS(&raw_factory)))) {
        return false;
    }
    ComPtr<IWICImagingFactory> factory(raw_factory);

    IWICStream* raw_stream = nullptr;
    if (FAILED(factory->CreateStream(&raw_stream))) return false;
    ComPtr<IWICStream> stream(raw_stream);
    if (FAILED(stream->InitializeFromFilename(path.c_str(), GENERIC_WRITE))) return false;

    IWICBitmapEncoder* raw_encoder = nullptr;
    if (FAILED(factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, &raw_encoder))) return false;
    ComPtr<IWICBitmapEncoder> encoder(raw_encoder);
    if (FAILED(encoder->Initialize(stream.get(), WICBitmapEncoderNoCache))) return false;

    IWICBitmapFrameEncode* raw_frame = nullptr;
    if (FAILED(encoder->CreateNewFrame(&raw_frame, nullptr))) return false;
    ComPtr<IWICBitmapFrameEncode> frame(raw_frame);
    if (FAILED(frame->Initialize(nullptr))) return false;
    if (FAILED(frame->SetSize(static_cast<UINT>(page.width), static_cast<UINT>(page.height)))) return false;

    WICPixelFormatGUID format = GUID_WICPixelFormat32bppRGBA;
    if (FAILED(frame->SetPixelFormat(&format))) return false;
    if (format != GUID_WICPixelFormat32bppRGBA) return false;

    const UINT stride = static_cast<UINT>(page.width) * 4;
    if (FAILED(frame->WritePixels(static_cast<UINT>(page.height), stride,
                                   static_cast<UINT>(page.rgba.size()),
                                   const_cast<BYTE*>(page.rgba.data())))) {
        return false;
    }
    if (FAILED(frame->Commit())) return false;
    if (FAILED(encoder->Commit())) return false;
    return true;
}

// =====================
// Request handlers
// =====================

void handle_open_pdf() {
    const auto selected = prompt_open_pdfs();
    if (selected.empty()) return;

    std::size_t loaded_files = 0;
    std::vector<std::wstring> failed_files;

    for (const auto& path : selected) {
        const auto utf8_path = path.u8string();
        std::string password;
        quickmarkpdf::PdfDocumentInfo info;
        bool opened = false;
        bool retry = false;
        for (int attempt = 0; attempt < 3; ++attempt) {
            try {
                info = quickmarkpdf::PdfBackend::inspect(utf8_path, password);
                opened = true;
                break;
            } catch (const quickmarkpdf::PdfPasswordRequiredError&) {
                auto entered = prompt_for_password(path, retry);
                if (!entered) break;
                password = *entered;
                retry = true;
            } catch (const std::exception&) {
                break;
            }
        }
        if (!opened) {
            failed_files.push_back(path.filename().wstring());
            continue;
        }
        if (!password.empty()) g_source_passwords[utf8_path] = password;
        for (std::size_t i = 0; i < info.page_count; ++i) {
            g_document.append_page({utf8_path, i, info.page_rotations[i]});
        }
        ++loaded_files;
    }

    std::wstring failed_json = L"[";
    for (std::size_t i = 0; i < failed_files.size(); ++i) {
        if (i > 0) failed_json += L",";
        failed_json += json_string(failed_files[i]);
    }
    failed_json += L"]";

    const std::wstring response = L"{\"type\":\"pdf_opened\",\"loaded_files\":" + std::to_wstring(loaded_files) +
                                   L",\"failed_files\":" + failed_json + L",\"page_count\":" +
                                   std::to_wstring(g_document.page_count()) + L",\"dirty\":" +
                                   (g_document.is_dirty() ? L"true" : L"false") + L",\"can_undo\":" +
                                   (g_document.can_undo() ? L"true" : L"false") + L",\"pages\":" + pages_json() +
                                   L"}";
    g_webview->PostWebMessageAsString(response.c_str());
}

void handle_render_page(const std::wstring& message) {
    const int page_index = extract_int(message, L"page_index", -1);
    const int width = extract_int(message, L"width", 160);
    if (page_index < 0 || static_cast<std::size_t>(page_index) >= g_document.page_count()) return;
    const auto& ref = g_document.page(static_cast<std::size_t>(page_index));
    try {
        const auto rendered = quickmarkpdf::PdfBackend::render_page(ref.source_path, ref.source_page, width,
                                                                      ref.rotation);
        const auto pixels_b64 =
            base64_encode(rendered.rgba.data(), static_cast<DWORD>(rendered.rgba.size()));
        const std::wstring response = L"{\"type\":\"page_rendered\",\"page_index\":" +
                                       std::to_wstring(page_index) + L",\"width\":" +
                                       std::to_wstring(rendered.width) + L",\"height\":" +
                                       std::to_wstring(rendered.height) + L",\"pixels\":\"" +
                                       std::wstring(pixels_b64.begin(), pixels_b64.end()) + L"\"}";
        g_webview->PostWebMessageAsString(response.c_str());
    } catch (const std::exception&) {
        // Rendering is best-effort per page; leave that thumbnail blank
        // rather than surfacing a global error for the whole document.
    }
}

void handle_reorder_pages(const std::wstring& message) {
    try {
        g_document.reorder(extract_size_t_array(message, L"order"));
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"並べ替えに失敗しました");
    }
}

void handle_rotate_page(const std::wstring& message) {
    const int page_index = extract_int(message, L"page_index", -1);
    const int degrees = extract_int(message, L"degrees", 0);
    if (page_index < 0) return;
    try {
        g_document.rotate(static_cast<std::size_t>(page_index), degrees);
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"回転に失敗しました");
    }
}

void handle_delete_pages(const std::wstring& message) {
    try {
        g_document.erase(extract_size_t_array(message, L"indices"));
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"削除に失敗しました");
    }
}

void handle_undo_edit() {
    g_document.undo();
    post_document_state(L"document_state");
}

void handle_save_pdf() {
    if (g_document.page_count() == 0) return;
    const auto target = prompt_save_pdf();
    if (!target) return;
    try {
        quickmarkpdf::PdfBackend::save(g_document, target->u8string(), g_source_passwords);
        g_document.mark_saved();
        post_status(L"保存しました");
        post_document_state(L"document_state");
    } catch (const quickmarkpdf::PdfPasswordRequiredError&) {
        post_status(L"保存に失敗しました(パスワードが必要なファイルがあります)");
    } catch (const std::exception&) {
        post_status(L"保存に失敗しました");
    }
}

void handle_export_images(const std::wstring& message) {
    if (g_document.page_count() == 0) return;
    auto indices = extract_size_t_array(message, L"indices");
    if (indices.empty()) {
        indices.resize(g_document.page_count());
        for (std::size_t i = 0; i < indices.size(); ++i) indices[i] = i;
    }
    const int dpi = extract_int(message, L"dpi", 150);

    const auto folder = prompt_pick_folder();
    if (!folder) return;

    int exported = 0;
    for (std::size_t order = 0; order < indices.size(); ++order) {
        const auto page_index = indices[order];
        if (page_index >= g_document.page_count()) continue;
        const auto& ref = g_document.page(page_index);
        try {
            const auto rendered = quickmarkpdf::PdfBackend::render_page_at_dpi(ref.source_path, ref.source_page,
                                                                                dpi, ref.rotation);
            wchar_t name[64]{};
            swprintf_s(name, L"page_%04zu.png", order + 1);
            if (write_png(*folder / name, rendered)) ++exported;
        } catch (const std::exception&) {
            // Best-effort: skip this page, continue exporting the rest.
        }
    }
    post_status((std::to_wstring(exported) + L"件の画像を書き出しました").c_str());
}

// =====================
// WebView2 host plumbing
// =====================

// CreateCoreWebView2EnvironmentWithOptions, resolved from WebView2Loader.dll
// at runtime instead of linking its import library -- the same pattern
// already used for pdfium.dll in pdf_backend.cpp, and for WebView2Loader.dll
// in QuickFolderSize's webview_main.cpp. Avoids any question of whether a
// Microsoft-format import .lib links cleanly under MinGW's ld.
using CreateEnvFn = HRESULT(STDAPICALLTYPE*)(PCWSTR, PCWSTR, ICoreWebView2EnvironmentOptions*,
                                              ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler*);

void resize_webview() {
    if (!g_controller) return;
    RECT bounds{};
    GetClientRect(g_window, &bounds);
    g_controller->put_Bounds(bounds);
}

void dispatch_message(const std::wstring& message) {
    if (message.find(L"open_pdf") != std::wstring::npos) {
        handle_open_pdf();
    } else if (message.find(L"render_page") != std::wstring::npos) {
        handle_render_page(message);
    } else if (message.find(L"reorder_pages") != std::wstring::npos) {
        handle_reorder_pages(message);
    } else if (message.find(L"rotate_page") != std::wstring::npos) {
        handle_rotate_page(message);
    } else if (message.find(L"delete_pages") != std::wstring::npos) {
        handle_delete_pages(message);
    } else if (message.find(L"undo_edit") != std::wstring::npos) {
        handle_undo_edit();
    } else if (message.find(L"export_images") != std::wstring::npos) {
        handle_export_images(message);
    } else if (message.find(L"save_pdf") != std::wstring::npos) {
        handle_save_pdf();
    }
}

bool load_ui(const std::filesystem::path& executable_dir, const std::filesystem::path& ui_path) {
    const auto loader_path = executable_dir / L"WebView2Loader.dll";
    HMODULE loader = LoadLibraryW(loader_path.c_str());
    if (!loader) {
        MessageBoxW(g_window, L"WebView2Loader.dll が見つかりません。\nQuickMarkPDF.exe と同じフォルダに配置してください。",
                    L"QuickMarkPDF", MB_ICONERROR);
        return false;
    }
    auto create_environment = reinterpret_cast<CreateEnvFn>(GetProcAddress(loader, "CreateCoreWebView2EnvironmentWithOptions"));
    if (!create_environment) {
        MessageBoxW(g_window, L"WebView2Loader.dll からCreateCoreWebView2EnvironmentWithOptionsを取得できませんでした。",
                    L"QuickMarkPDF", MB_ICONERROR);
        return false;
    }

    wchar_t temp_dir[MAX_PATH]{};
    GetTempPathW(MAX_PATH, temp_dir);
    const std::wstring user_data_folder = std::wstring(temp_dir) + L"QuickMarkPDF_WVData";
    CreateDirectoryW(user_data_folder.c_str(), nullptr);

    create_environment(
        nullptr, user_data_folder.c_str(), nullptr,
        new EnvCompletedHandler([ui_path](HRESULT result, ICoreWebView2Environment* environment) -> HRESULT {
            if (FAILED(result) || environment == nullptr) return result;
            return environment->CreateCoreWebView2Controller(
                g_window, new ControllerCompletedHandler([ui_path](HRESULT controller_result,
                                                                    ICoreWebView2Controller* controller) -> HRESULT {
                    if (FAILED(controller_result) || controller == nullptr) return controller_result;

                    g_controller = controller;
                    g_controller->AddRef();
                    g_controller->get_CoreWebView2(&g_webview);

                    EventRegistrationToken message_token{};
                    g_webview->add_WebMessageReceived(
                        new WebMessageReceivedHandler(
                            [](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
                                LPWSTR raw_message = nullptr;
                                if (FAILED(args->TryGetWebMessageAsString(&raw_message))) return S_OK;
                                const std::wstring message(raw_message);
                                CoTaskMemFree(raw_message);
                                dispatch_message(message);
                                return S_OK;
                            }),
                        &message_token);
                    resize_webview();
                    g_webview->Navigate(file_url(ui_path).c_str());
                    return S_OK;
                }));
        }));
    return true;
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_SIZE:
        resize_webview();
        return 0;
    case WM_DESTROY:
        if (g_webview) {
            g_webview->Release();
            g_webview = nullptr;
        }
        if (g_controller) {
            g_controller->Close();
            g_controller->Release();
            g_controller = nullptr;
        }
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProcW(window, message, wparam, lparam);
    }
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR command_line, int show_command) {
    (void)command_line;
    wchar_t executable_path[MAX_PATH]{};
    GetModuleFileNameW(nullptr, executable_path, MAX_PATH);
    const auto executable_dir = std::filesystem::path(executable_path).parent_path();
    // dist/binary/ is a flat layout (see ___appli-template/01_フォルダ構成.md):
    // bundle_html.py always produces a single self-contained index.html next
    // to the exe, so there is no "ui/" subfolder to look for.
    const auto ui_path = std::filesystem::absolute(executable_dir / L"index.html");

    WNDCLASSW window_class{};
    window_class.hInstance = instance;
    window_class.lpfnWndProc = window_proc;
    window_class.lpszClassName = L"QuickMarkPDFWebViewHost";
    RegisterClassW(&window_class);

    g_window = CreateWindowExW(
        0, window_class.lpszClassName, L"QuickMarkPDF",
        WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 1280, 860,
        nullptr, nullptr, instance, nullptr);
    if (!g_window) return 1;

    ShowWindow(g_window, show_command);
    UpdateWindow(g_window);
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return 1;
    // GetOpenFileNameW/GetSaveFileNameW's modern Explorer-style dialog is
    // documented to require OLE to be initialized (not just plain COM) --
    // without this, the common-item dialog can fail to appear at all, with
    // GetOpenFileNameW simply returning FALSE and no dialog ever shown.
    OleInitialize(nullptr);
    if (!load_ui(executable_dir, ui_path)) return 1;

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    OleUninitialize();
    CoUninitialize();
    return static_cast<int>(message.wParam);
}
