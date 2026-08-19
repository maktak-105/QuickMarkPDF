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
// <wrl.h>). These three classes hand-roll the same "wrap a std::function as
// a one-off COM callback" pattern with a raw IUnknown implementation.

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

class NavigationCompletedHandler : public ICoreWebView2NavigationCompletedEventHandler {
    std::function<HRESULT(ICoreWebView2*, ICoreWebView2NavigationCompletedEventArgs*)> fn_;
    std::atomic<ULONG> ref_{1};

public:
    explicit NavigationCompletedHandler(
        std::function<HRESULT(ICoreWebView2*, ICoreWebView2NavigationCompletedEventArgs*)> fn)
        : fn_(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2NavigationCompletedEventHandler) {
            *ppv = static_cast<ICoreWebView2NavigationCompletedEventHandler*>(this);
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
    HRESULT STDMETHODCALLTYPE Invoke(ICoreWebView2* sender, ICoreWebView2NavigationCompletedEventArgs* args) override {
        return fn_(sender, args);
    }
};

// Minimal RAII for CoCreateInstance-created interfaces (IFileOpenDialog,
// IShellItem) -- std::unique_ptr with a Release()-calling deleter, so early
// returns can't leak a reference. Deliberately not Microsoft::WRL::ComPtr
// (see the note above); this needs nothing beyond the standard library.
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
quickmarkpdf::PdfManager g_manager;
// Paths passed on the command line (main.py's CLI-args bypass, mirrored here
// so verification never has to fight the native file dialog -- see
// CPP_PORT_POSTMORTEM.md). Opened once, right after the page finishes its
// first navigation.
std::vector<std::wstring> g_startup_paths;

// =====================
// String / JSON helpers
// =====================
//
// static/js/app.js is the only producer of the request messages below and
// the only consumer of the response messages, and its shape never varies,
// so a couple of targeted lookups are enough -- no general JSON parser.

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

std::wstring utf8_to_wide(const std::string& value) {
    if (value.empty()) return {};
    const int size = ::MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    std::wstring result(static_cast<std::size_t>(size), L'\0');
    ::MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size);
    return result;
}

// Extracts the exact string value of `"type":"..."` from a request message.
// Deliberately NOT a substring search over the whole message (a page's
// source file path could legitimately contain e.g. "rotate_page" as text
// and misfire a substring match) -- this only looks at the "type" key's own
// value, matching the one place dispatch is allowed to branch on.
std::wstring extract_type(const std::wstring& message) {
    const std::wstring needle = L"\"type\":\"";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return L"";
    const auto start = pos + needle.size();
    const auto end = message.find(L'\"', start);
    if (end == std::wstring::npos) return L"";
    return message.substr(start, end - start);
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

std::wstring extract_string(const std::wstring& message, const wchar_t* key, const wchar_t* fallback = L"") {
    const std::wstring needle = std::wstring(L"\"") + key + L"\":\"";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return fallback;
    const auto start = pos + needle.size();
    const auto end = message.find(L'\"', start);
    if (end == std::wstring::npos) return fallback;
    return message.substr(start, end - start);
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
        while (cursor < message.size() && message[cursor] == L' ') ++cursor;
        if (cursor < message.size() && message[cursor] == L',') ++cursor;
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
    const auto infos = g_manager.page_infos();
    for (std::size_t i = 0; i < infos.size(); ++i) {
        if (i > 0) pages += L",";
        const auto& page = infos[i];
        pages += L"{\"path\":" + json_string(std::filesystem::u8path(page.source_path).wstring()) +
                 L",\"source_page\":" + std::to_wstring(page.original_page_index) + L",\"rotation\":" +
                 std::to_wstring(page.rotation) + L"}";
    }
    pages += L"]";
    return pages;
}

void post_document_state(const wchar_t* message_type) {
    if (!g_webview) return;
    const std::wstring response = std::wstring(L"{\"type\":\"") + message_type + L"\",\"page_count\":" +
                                   std::to_wstring(g_manager.get_page_count()) + L",\"can_undo\":" +
                                   (g_manager.can_undo() ? L"true" : L"false") + L",\"can_overwrite\":" +
                                   (g_manager.can_overwrite_source() ? L"true" : L"false") + L",\"pages\":" +
                                   pages_json() + L"}";
    g_webview->PostWebMessageAsString(response.c_str());
}

void post_status(const std::wstring& text) {
    if (!g_webview) return;
    const std::wstring response = std::wstring(L"{\"type\":\"backend_status\",\"message\":") +
                                   json_string(text) + L"}";
    g_webview->PostWebMessageAsString(response.c_str());
}

// =====================
// Native dialogs
// =====================

// Native dialogs triggered from a WebView2 WebMessage callback don't
// reliably get focus on their own: GetOpenFileNameW's dialog appears
// fully on-screen, enabled, not minimized -- just not the foreground
// window (Windows' focus-stealing prevention apparently doesn't treat
// "click inside the WebView2-rendered page" as equivalent to direct
// native window input for this purpose). AttachThreadInput to temporarily
// share input state with whatever thread currently owns the foreground is
// the standard workaround.
void force_foreground_window() {
    if (!g_window) return;
    if (IsIconic(g_window)) ShowWindow(g_window, SW_RESTORE);

    const HWND foreground = GetForegroundWindow();
    const DWORD foreground_thread = foreground ? GetWindowThreadProcessId(foreground, nullptr) : 0;
    const DWORD current_thread = GetCurrentThreadId();
    const bool attached =
        foreground_thread != 0 && foreground_thread != current_thread &&
        AttachThreadInput(foreground_thread, current_thread, TRUE);

    SetWindowPos(g_window, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
    SetWindowPos(g_window, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE);
    SetForegroundWindow(g_window);
    BringWindowToTop(g_window);
    SetActiveWindow(g_window);

    if (attached) AttachThreadInput(foreground_thread, current_thread, FALSE);
}

// GetOpenFileNameW with OFN_ALLOWMULTISELECT + OFN_EXPLORER returns either a
// single null-terminated full path (one file picked), or a directory
// followed by one null-terminated filename per picked file, the whole
// group terminated by an extra null.
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
    force_foreground_window();
    if (!GetOpenFileNameW(&dialog)) {
        const DWORD error = CommDlgExtendedError();
        if (error != 0) {
            post_status(L"ファイル選択ダイアログを開けませんでした (エラーコード: " + std::to_wstring(error) + L")");
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
    force_foreground_window();
    if (!GetSaveFileNameW(&dialog)) return std::nullopt;
    return std::filesystem::path(selected);
}

// Folder picker for image export, via IFileOpenDialog + FOS_PICKFOLDERS.
std::optional<std::filesystem::path> prompt_pick_folder() {
    IFileOpenDialog* raw_dialog = nullptr;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&raw_dialog)))) {
        return std::nullopt;
    }
    ComPtr<IFileOpenDialog> dialog(raw_dialog);

    DWORD options = 0;
    dialog->GetOptions(&options);
    dialog->SetOptions(options | FOS_PICKFOLDERS | FOS_PATHMUSTEXIST | FOS_FORCEFILESYSTEM);
    force_foreground_window();
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

// Native password prompt for an encrypted source file, via CredUI (a single
// documented API call is far less likely to have a subtle mistake than a
// hand-rolled dialog template). The username field is unused/prefilled with
// the file name for context -- there's no username concept for a PDF
// password.
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

    force_foreground_window();
    const DWORD result = CredUIPromptForCredentialsW(
        &ui_info, filename.c_str(), nullptr, retry ? static_cast<DWORD>(ERROR_LOGON_FAILURE) : 0, username,
        CREDUI_MAX_USERNAME_LENGTH + 1, password, CREDUI_MAX_PASSWORD_LENGTH + 1, &save,
        CREDUI_FLAGS_GENERIC_CREDENTIALS | CREDUI_FLAGS_DO_NOT_PERSIST | CREDUI_FLAGS_EXCLUDE_CERTIFICATES);
    if (result != NO_ERROR) return std::nullopt;
    return wide_to_utf8(password);
}

// =====================
// Request handlers
// =====================

// Shared by the dialog-driven open (handle_open_pdf) and the CLI-args
// startup path (see wWinMain) -- mirrors main.py calling
// MainWindow.open_documents(files) directly to skip the dialog entirely,
// per CPP_PORT_POSTMORTEM.md's explicit recommendation not to rely on
// automating the native file dialog for verification.
void open_pdf_paths(const std::vector<std::filesystem::path>& paths) {
    if (paths.empty()) {
        post_status(L"ファイル選択をキャンセルしました");
        return;
    }

    std::vector<std::string> utf8_paths;
    utf8_paths.reserve(paths.size());
    for (const auto& p : paths) utf8_paths.push_back(p.u8string());

    auto result = g_manager.load_pdfs(utf8_paths);

    // Retry each password-required file interactively, up to 3 attempts --
    // mirrors python/.../main_window.py's _retry_password_protected_files.
    std::vector<std::wstring> failed_files;
    int extra_loaded = 0;
    for (const auto& absolute_path : result.password_required) {
        const std::filesystem::path path = std::filesystem::u8path(absolute_path);
        bool opened = false;
        bool retry = false;
        for (int attempt = 0; attempt < 3 && !opened; ++attempt) {
            auto entered = prompt_for_password(path, retry);
            if (!entered) break;
            retry = true;
            auto retry_result = g_manager.load_pdfs({absolute_path}, {{absolute_path, *entered}});
            if (retry_result.loaded_count > 0) {
                opened = true;
                ++extra_loaded;
            }
        }
        if (!opened) failed_files.push_back(path.filename().wstring());
    }

    const int total_loaded = result.loaded_count + extra_loaded;

    std::wstring failed_json = L"[";
    for (std::size_t i = 0; i < failed_files.size(); ++i) {
        if (i > 0) failed_json += L",";
        failed_json += json_string(failed_files[i]);
    }
    failed_json += L"]";

    const std::wstring response =
        L"{\"type\":\"pdf_opened\",\"loaded_files\":" + std::to_wstring(total_loaded) + L",\"failed_files\":" +
        failed_json + L",\"page_count\":" + std::to_wstring(g_manager.get_page_count()) + L",\"can_undo\":" +
        (g_manager.can_undo() ? L"true" : L"false") + L",\"can_overwrite\":" +
        (g_manager.can_overwrite_source() ? L"true" : L"false") + L",\"pages\":" + pages_json() + L"}";
    if (g_webview) g_webview->PostWebMessageAsString(response.c_str());
}

void handle_open_pdf() {
    open_pdf_paths(prompt_open_pdfs());
}

void handle_render_page(const std::wstring& message) {
    const int page_index = extract_int(message, L"page_index", -1);
    const int width = extract_int(message, L"width", 160);
    if (page_index < 0 || static_cast<std::size_t>(page_index) >= g_manager.get_page_count()) return;
    const auto infos = g_manager.page_infos();
    const auto& ref = infos[static_cast<std::size_t>(page_index)];
    try {
        const auto rendered =
            quickmarkpdf::PdfBackend::render_page(ref.source_path, ref.original_page_index, width, ref.rotation);
        const auto pixels_b64 = base64_encode(rendered.rgba.data(), static_cast<DWORD>(rendered.rgba.size()));
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
        g_manager.reorder_pages(extract_size_t_array(message, L"order"));
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"並べ替えに失敗しました");
    }
}

void handle_rotate_pages(const std::wstring& message) {
    const int degrees = extract_int(message, L"degrees", 0);
    try {
        g_manager.rotate_pages(extract_size_t_array(message, L"indices"), degrees);
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"回転に失敗しました");
    }
}

void handle_delete_pages(const std::wstring& message) {
    g_manager.delete_pages(extract_size_t_array(message, L"indices"));
    post_document_state(L"document_state");
}

void handle_undo_edit() {
    g_manager.undo();
    post_document_state(L"document_state");
}

void handle_close_document(const std::wstring& message) {
    const auto path = extract_string(message, L"path");
    if (g_manager.close_document(wide_to_utf8(path))) {
        post_document_state(L"document_state");
    }
}

// Mirrors main_window.py's save_pdf(): if every loaded page comes from the
// same single source file, ask whether to overwrite it in place or save as
// a new file; otherwise go straight to save-as. MB_YESNOCANCEL's fixed
// button set (rather than the Python baseline's custom-labelled "上書き保存
// / 新規で保存 / キャンセル" QMessageBox buttons) is a known simplification --
// the message text spells out what each button does.
void handle_save_pdf() {
    if (g_manager.get_page_count() == 0) return;

    std::filesystem::path target;
    bool overwrite = false;

    if (g_manager.can_overwrite_source()) {
        force_foreground_window();
        const int choice = MessageBoxW(
            g_window,
            L"開いているファイルを上書き保存しますか？\n"
            L"「はい」= 上書き保存 / 「いいえ」= 新しいファイルとして保存 / 「キャンセル」= 中止",
            L"保存方法の選択", MB_YESNOCANCEL | MB_ICONQUESTION);
        if (choice == IDCANCEL) return;
        overwrite = (choice == IDYES);
    }

    if (overwrite) {
        if (g_manager.overwrite_source()) {
            post_status(L"上書き保存しました");
        } else {
            post_status(L"上書き保存に失敗しました");
        }
        post_document_state(L"document_state");
        return;
    }

    const auto picked = prompt_save_pdf();
    if (!picked) return;
    if (g_manager.save_as(picked->u8string())) {
        post_status(L"保存しました: " + picked->wstring());
    } else {
        post_status(L"保存に失敗しました");
    }
    post_document_state(L"document_state");
}

void handle_export_images(const std::wstring& message) {
    if (g_manager.get_page_count() == 0) return;
    auto indices = extract_size_t_array(message, L"indices");
    const int dpi = extract_int(message, L"dpi", 150);

    const auto folder = prompt_pick_folder();
    if (!folder) return;

    const auto result = g_manager.export_pages_to_images(indices, folder->u8string(), "png", dpi, "page");
    post_status(std::to_wstring(result.success) + L"/" + std::to_wstring(result.attempted) +
                L" 件の画像を書き出しました");
}

// =====================
// WebView2 host plumbing
// =====================

// CreateCoreWebView2EnvironmentWithOptions, resolved from WebView2Loader.dll
// at runtime instead of linking its import library -- the same pattern used
// for pdfium.dll in pdf_backend.cpp. Avoids any question of whether a
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
    const auto type = extract_type(message);
    if (type == L"open_pdf") {
        handle_open_pdf();
    } else if (type == L"render_page") {
        handle_render_page(message);
    } else if (type == L"reorder_pages") {
        handle_reorder_pages(message);
    } else if (type == L"rotate_pages") {
        handle_rotate_pages(message);
    } else if (type == L"delete_pages") {
        handle_delete_pages(message);
    } else if (type == L"undo_edit") {
        handle_undo_edit();
    } else if (type == L"close_document") {
        handle_close_document(message);
    } else if (type == L"export_images") {
        handle_export_images(message);
    } else if (type == L"save_pdf") {
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

    const HRESULT create_result = create_environment(
        nullptr, user_data_folder.c_str(), nullptr,
        new EnvCompletedHandler([ui_path](HRESULT result, ICoreWebView2Environment* environment) -> HRESULT {
            if (FAILED(result) || environment == nullptr) {
                wchar_t msg[256]{};
                swprintf_s(msg, L"WebView2環境の作成に失敗しました。WebView2 Runtimeが未インストールの可能性があります。\nHRESULT: 0x%08X",
                            static_cast<unsigned>(result));
                MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
                return result;
            }
            const HRESULT controller_request = environment->CreateCoreWebView2Controller(
                g_window, new ControllerCompletedHandler([ui_path](HRESULT controller_result,
                                                                    ICoreWebView2Controller* controller) -> HRESULT {
                    if (FAILED(controller_result) || controller == nullptr) {
                        wchar_t msg[256]{};
                        swprintf_s(msg, L"WebView2コントローラの作成に失敗しました。\nHRESULT: 0x%08X",
                                    static_cast<unsigned>(controller_result));
                        MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
                        return controller_result;
                    }

                    g_controller = controller;
                    g_controller->AddRef();
                    g_controller->get_CoreWebView2(&g_webview);
                    if (!g_webview) {
                        MessageBoxW(g_window, L"get_CoreWebView2に失敗しました。", L"QuickMarkPDF", MB_ICONERROR);
                        return E_FAIL;
                    }

                    EventRegistrationToken message_token{};
                    const HRESULT add_result = g_webview->add_WebMessageReceived(
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
                    if (FAILED(add_result)) {
                        wchar_t msg[256]{};
                        swprintf_s(msg, L"add_WebMessageReceivedに失敗しました。\nHRESULT: 0x%08X",
                                    static_cast<unsigned>(add_result));
                        MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
                    }

                    // Once the initial page load finishes, open any files
                    // passed on the command line -- bypasses the file
                    // dialog entirely, matching python/main.py's CLI-args
                    // path (see open_pdf_paths's docstring above).
                    EventRegistrationToken nav_token{};
                    g_webview->add_NavigationCompleted(
                        new NavigationCompletedHandler(
                            [](ICoreWebView2*, ICoreWebView2NavigationCompletedEventArgs*) -> HRESULT {
                                if (!g_startup_paths.empty()) {
                                    std::vector<std::filesystem::path> paths;
                                    for (const auto& p : g_startup_paths) paths.emplace_back(p);
                                    g_startup_paths.clear();
                                    open_pdf_paths(paths);
                                }
                                return S_OK;
                            }),
                        &nav_token);

                    resize_webview();
                    const HRESULT nav_result = g_webview->Navigate(file_url(ui_path).c_str());
                    if (FAILED(nav_result)) {
                        wchar_t msg[512]{};
                        swprintf_s(msg, L"Navigateに失敗しました。\nHRESULT: 0x%08X\nパス: %s",
                                    static_cast<unsigned>(nav_result), file_url(ui_path).c_str());
                        MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
                    }
                    return S_OK;
                }));
            if (FAILED(controller_request)) {
                wchar_t msg[256]{};
                swprintf_s(msg, L"CreateCoreWebView2Controllerの呼び出しに失敗しました。\nHRESULT: 0x%08X",
                            static_cast<unsigned>(controller_request));
                MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
            }
            return S_OK;
        }));
    if (FAILED(create_result)) {
        wchar_t msg[256]{};
        swprintf_s(msg, L"CreateCoreWebView2EnvironmentWithOptionsの呼び出しに失敗しました。\nHRESULT: 0x%08X",
                    static_cast<unsigned>(create_result));
        MessageBoxW(g_window, msg, L"QuickMarkPDF", MB_ICONERROR);
        return false;
    }
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

// Splits the command line into individual arguments (CommandLineToArgvW),
// keeping only ones that look like an existing .pdf path -- mirrors
// python/main.py's own filtering of sys.argv[1:].
std::vector<std::wstring> parse_startup_pdf_args(PWSTR command_line) {
    std::vector<std::wstring> result;
    if (!command_line || !*command_line) return result;
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(command_line, &argc);
    if (!argv) return result;
    for (int i = 0; i < argc; ++i) {
        std::filesystem::path candidate(argv[i]);
        auto ext = candidate.extension().wstring();
        for (auto& c : ext) c = static_cast<wchar_t>(std::towlower(c));
        if (ext == L".pdf" && std::filesystem::exists(candidate)) {
            result.push_back(std::filesystem::absolute(candidate).wstring());
        }
    }
    LocalFree(argv);
    return result;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR command_line, int show_command) {
    g_startup_paths = parse_startup_pdf_args(command_line);

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
