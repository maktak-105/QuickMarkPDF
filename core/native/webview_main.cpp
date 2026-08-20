#include <windows.h>
#include <wincodec.h>
#include <wincred.h>
#include <wincrypt.h>
#include <shobjidl.h>
#include <commctrl.h>
#include <unknwn.h>
#include <WebView2.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cwctype>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "engine.h"
#include "pdf_backend.h"
#include "test_api_server.h"

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

class PrintToPdfCompletedHandler : public ICoreWebView2PrintToPdfCompletedHandler {
    std::function<HRESULT(HRESULT, BOOL)> fn_;
    std::atomic<ULONG> ref_{1};

public:
    explicit PrintToPdfCompletedHandler(std::function<HRESULT(HRESULT, BOOL)> fn) : fn_(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
        if (riid == IID_IUnknown || riid == IID_ICoreWebView2PrintToPdfCompletedHandler) {
            *ppv = static_cast<ICoreWebView2PrintToPdfCompletedHandler*>(this);
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
    HRESULT STDMETHODCALLTYPE Invoke(HRESULT errorCode, BOOL result) override { return fn_(errorCode, result); }
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
// The currently displayed Markdown document's path, if any (empty when in
// PDF mode or nothing has been opened yet) -- used as the default filename
// when exporting to PDF (see handle_save_markdown_pdf).
std::filesystem::path g_current_markdown_path;
// Last directory the user opened or saved a file in this session -- mirrors
// main_window.py's self._last_used_dir, used as every subsequent dialog's
// starting folder. Restored from the registry at startup and saved back
// on every change (see save_settings_to_registry).
std::filesystem::path g_last_used_dir;

// =====================
// Settings persistence (registry) -- mirrors main_window.py's QSettings
// (window geometry, thumbnail size, wheel mode, last-used folder all
// survive an app restart there; this port previously reset all of that on
// every launch). Deliberately skipped entirely when QUICKMARKPDF_OFFSCREEN
// is set: qa/extract_cpp.py's dashboard measurements depend on the window
// always being exactly 1280x820 at a fixed position, and a QA run must
// never read stray values from -- or write over -- a real user's saved
// settings.
// =====================

constexpr wchar_t kSettingsRegistryPath[] = L"Software\\QuickMarkPDF\\Settings";

void save_dword_setting(const wchar_t* name, DWORD value) {
    HKEY key;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, kSettingsRegistryPath, 0, nullptr, 0, KEY_WRITE, nullptr, &key,
                         nullptr) != ERROR_SUCCESS) {
        return;
    }
    RegSetValueExW(key, name, 0, REG_DWORD, reinterpret_cast<const BYTE*>(&value), sizeof(value));
    RegCloseKey(key);
}

std::optional<DWORD> load_dword_setting(const wchar_t* name) {
    HKEY key;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, kSettingsRegistryPath, 0, KEY_READ, &key) != ERROR_SUCCESS) {
        return std::nullopt;
    }
    DWORD value = 0;
    DWORD size = sizeof(value);
    DWORD type = 0;
    const LONG result = RegQueryValueExW(key, name, nullptr, &type, reinterpret_cast<BYTE*>(&value), &size);
    RegCloseKey(key);
    if (result != ERROR_SUCCESS || type != REG_DWORD) return std::nullopt;
    return value;
}

void save_string_setting(const wchar_t* name, const std::wstring& value) {
    HKEY key;
    if (RegCreateKeyExW(HKEY_CURRENT_USER, kSettingsRegistryPath, 0, nullptr, 0, KEY_WRITE, nullptr, &key,
                         nullptr) != ERROR_SUCCESS) {
        return;
    }
    RegSetValueExW(key, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(value.c_str()),
                   static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t)));
    RegCloseKey(key);
}

std::optional<std::wstring> load_string_setting(const wchar_t* name) {
    HKEY key;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, kSettingsRegistryPath, 0, KEY_READ, &key) != ERROR_SUCCESS) {
        return std::nullopt;
    }
    DWORD size = 0;
    DWORD type = 0;
    if (RegQueryValueExW(key, name, nullptr, &type, nullptr, &size) != ERROR_SUCCESS || type != REG_SZ ||
        size == 0) {
        RegCloseKey(key);
        return std::nullopt;
    }
    std::wstring value(size / sizeof(wchar_t), L'\0');
    RegQueryValueExW(key, name, nullptr, nullptr, reinterpret_cast<BYTE*>(value.data()), &size);
    RegCloseKey(key);
    while (!value.empty() && value.back() == L'\0') value.pop_back();
    return value;
}

bool is_offscreen_mode() {
    return GetEnvironmentVariableW(L"QUICKMARKPDF_OFFSCREEN", nullptr, 0) > 0;
}

// True when QUICKMARKPDF_TEST_PORT is set, i.e. the TCP test API
// (qa/check_behaviors_cpp.py) is reachable. A real MessageBoxW triggered
// from that path would block main-thread message processing forever with
// nothing to click it (no human, no dialog-injection hook for it) -- new
// notification dialogs added to real user-facing code paths must check
// this and fall back to post_status instead when true, the same way
// load_pdfs' password/close_all's confirm fields already let specific
// dialogs be bypassed for testing.
bool is_test_mode() {
    wchar_t buffer[8]{};
    return GetEnvironmentVariableW(L"QUICKMARKPDF_TEST_PORT", buffer, 8) > 0;
}

// Called once at startup, before the window is created -- window
// position/size need to be known before CreateWindowExW.
struct SavedWindowGeometry {
    int x = CW_USEDEFAULT, y = CW_USEDEFAULT, width = 1280, height = 820;
};

SavedWindowGeometry load_window_geometry() {
    SavedWindowGeometry geo;
    if (is_offscreen_mode()) return geo;
    if (auto v = load_dword_setting(L"WindowX")) geo.x = static_cast<int>(*v);
    if (auto v = load_dword_setting(L"WindowY")) geo.y = static_cast<int>(*v);
    if (auto v = load_dword_setting(L"WindowWidth")) geo.width = std::max(900, static_cast<int>(*v));
    if (auto v = load_dword_setting(L"WindowHeight")) geo.height = std::max(600, static_cast<int>(*v));
    return geo;
}

void save_window_geometry(HWND window) {
    if (is_offscreen_mode() || !window) return;
    RECT rect{};
    if (!GetWindowRect(window, &rect)) return;
    save_dword_setting(L"WindowX", static_cast<DWORD>(rect.left));
    save_dword_setting(L"WindowY", static_cast<DWORD>(rect.top));
    save_dword_setting(L"WindowWidth", static_cast<DWORD>(rect.right - rect.left));
    save_dword_setting(L"WindowHeight", static_cast<DWORD>(rect.bottom - rect.top));
}

void load_last_used_dir_setting() {
    if (is_offscreen_mode()) return;
    if (auto v = load_string_setting(L"LastUsedDir")) {
        std::error_code ec;
        if (std::filesystem::exists(*v, ec)) g_last_used_dir = *v;
    }
}

void save_last_used_dir_setting() {
    if (is_offscreen_mode() || g_last_used_dir.empty()) return;
    save_string_setting(L"LastUsedDir", g_last_used_dir.wstring());
}

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
    // Every response built here so far has been short, control-character-free
    // text (statuses, file paths), so escaping just backslash/quote was
    // enough. Markdown file content is neither -- it's arbitrary multi-line
    // text -- so this also escapes the control characters JSON requires
    // escaping (a bare newline inside a JSON string is invalid and breaks
    // parsing on the JS side).
    std::wstring escaped = L"\"";
    for (const auto character : value) {
        switch (character) {
            case L'\\': escaped += L"\\\\"; break;
            case L'\"': escaped += L"\\\""; break;
            case L'\n': escaped += L"\\n"; break;
            case L'\r': escaped += L"\\r"; break;
            case L'\t': escaped += L"\\t"; break;
            default:
                if (character < 0x20) {
                    wchar_t buf[8];
                    swprintf_s(buf, L"\\u%04x", static_cast<unsigned>(character));
                    escaped += buf;
                } else {
                    escaped += character;
                }
        }
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

// nullopt means the key was absent (caller should fall back to a real
// dialog); present-but-unparseable is treated the same as absent.
std::optional<bool> extract_optional_bool(const std::wstring& message, const wchar_t* key) {
    const std::wstring needle = std::wstring(L"\"") + key + L"\":";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return std::nullopt;
    const auto cursor = pos + needle.size();
    if (message.compare(cursor, 4, L"true") == 0) return true;
    if (message.compare(cursor, 5, L"false") == 0) return false;
    return std::nullopt;
}

// Pre-existing bug fixed here: this used to return the raw substring
// between quotes with no backslash-escape handling. Harmless for the
// short ASCII values (statuses, "path" on POSIX-style separators) every
// existing caller happened to pass, but any Windows path with backslashes
// (e.g. "path":"C:\\Users\\...") came back with the JSON escaping still
// literally in it (C:\\Users\\...), which silently broke every
// std::filesystem::path comparison against it -- discovered via the test
// API's close_document command comparing against PdfManager's
// std::filesystem::absolute()-normalized paths and never matching.
// extract_string_array() (added alongside the test API) already did this
// correctly; this brings the older, more-used function in line with it.
std::wstring extract_string(const std::wstring& message, const wchar_t* key, const wchar_t* fallback = L"") {
    const std::wstring needle = std::wstring(L"\"") + key + L"\":\"";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return fallback;
    auto cursor = pos + needle.size();
    std::wstring value;
    while (cursor < message.size() && message[cursor] != L'\"') {
        if (message[cursor] == L'\\' && cursor + 1 < message.size()) {
            ++cursor;
            switch (message[cursor]) {
                case L'n': value += L'\n'; break;
                case L't': value += L'\t'; break;
                case L'r': value += L'\r'; break;
                default: value += message[cursor]; break;  // \\ -> \, \" -> ", etc.
            }
        } else {
            value += message[cursor];
        }
        ++cursor;
    }
    if (cursor >= message.size()) return fallback;  // unterminated string
    return value;
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

// For "key":[x0,y0,x1,y1] -- PdfManager::export_pages_to_images' clip
// rectangle (PDF points, page-space). nullopt if the key is absent or
// doesn't contain exactly 4 numbers, so a malformed/omitted crop falls back
// to a full-page export rather than a wrong crop.
std::optional<std::array<double, 4>> extract_optional_double_array4(const std::wstring& message, const wchar_t* key) {
    const std::wstring needle = std::wstring(L"\"") + key + L"\":[";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return std::nullopt;
    auto cursor = pos + needle.size();
    std::array<double, 4> result{};
    for (int i = 0; i < 4; ++i) {
        while (cursor < message.size() && (message[cursor] == L' ' || message[cursor] == L',')) ++cursor;
        wchar_t* end = nullptr;
        result[i] = std::wcstod(message.c_str() + cursor, &end);
        if (end == message.c_str() + cursor) return std::nullopt;  // no number consumed
        cursor = static_cast<std::size_t>(end - message.c_str());
    }
    return result;
}

std::vector<std::wstring> extract_string_array(const std::wstring& message, const wchar_t* key) {
    std::vector<std::wstring> result;
    const std::wstring needle = std::wstring(L"\"") + key + L"\":[";
    const auto pos = message.find(needle);
    if (pos == std::wstring::npos) return result;
    auto cursor = pos + needle.size();
    while (cursor < message.size() && message[cursor] != L']') {
        while (cursor < message.size() && (message[cursor] == L' ' || message[cursor] == L',')) ++cursor;
        if (cursor >= message.size() || message[cursor] != L'\"') break;
        ++cursor;  // opening quote
        std::wstring value;
        while (cursor < message.size() && message[cursor] != L'\"') {
            if (message[cursor] == L'\\' && cursor + 1 < message.size()) {
                ++cursor;
                switch (message[cursor]) {
                    case L'n': value += L'\n'; break;
                    case L't': value += L'\t'; break;
                    case L'r': value += L'\r'; break;
                    default: value += message[cursor]; break;
                }
            } else {
                value += message[cursor];
            }
            ++cursor;
        }
        result.push_back(value);
        if (cursor < message.size() && message[cursor] == L'\"') ++cursor;  // closing quote
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

// Test hook for the "開く" button's file-picker step ONLY -- fires when the
// user (or a test) triggers open_pdf, never at startup. When
// QUICKMARKPDF_TEST_OPEN_PATHS is set (semicolon-separated absolute paths),
// returns those paths directly instead of showing GetOpenFileNameW. This is
// the C++ analog of Python's unittest.mock.patch(QFileDialog,
// "getOpenFileNames", ...) -- direct value injection into the same code
// path a real click takes, not dialog automation and not a
// startup/CLI-args auto-open (see g_startup_paths / open_pdf_paths for
// that separate, unrelated mechanism).
std::optional<std::vector<std::filesystem::path>> test_hook_open_documents() {
    wchar_t buffer[32768]{};
    const DWORD len = GetEnvironmentVariableW(L"QUICKMARKPDF_TEST_OPEN_PATHS", buffer, 32768);
    if (len == 0 || len >= 32768) return std::nullopt;
    std::vector<std::filesystem::path> result;
    std::wstring s(buffer, len);
    std::size_t pos = 0;
    while (pos < s.size()) {
        std::size_t next = s.find(L';', pos);
        if (next == std::wstring::npos) next = s.size();
        if (next > pos) result.emplace_back(s.substr(pos, next - pos));
        pos = next + 1;
    }
    return result;
}

// Gate for any action that would discard unsaved PDF edits (window close,
// opening a document that replaces the current session). Mirrors the
// Python spec's _confirm_discard_pdf_changes: returns true immediately if
// there's nothing unsaved, otherwise asks. forced_answer lets the TCP test
// API (qa/check_behaviors_cpp.py) supply the answer directly instead of a
// real MessageBoxW -- the same pattern load_pdfs' "password" field already
// uses to bypass the password-prompt dialog.
bool confirm_discard_dirty_state(std::optional<bool> forced_answer,
                                  const wchar_t* question = L"保存されていない変更があります。破棄してもよろしいですか?") {
    if (!g_manager.is_dirty()) return true;
    if (forced_answer.has_value()) return *forced_answer;
    const int result = MessageBoxW(g_window, question, L"QuickMarkPDF", MB_YESNO | MB_ICONWARNING);
    return result == IDYES;
}

std::vector<std::filesystem::path> prompt_open_documents() {
    if (auto injected = test_hook_open_documents()) return *injected;

    std::vector<wchar_t> buffer(65536, L'\0');
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = g_window;
    dialog.lpstrFilter =
        L"Supported Files (*.pdf;*.md;*.markdown)\0*.pdf;*.md;*.markdown\0"
        L"PDF Files (*.pdf)\0*.pdf\0Markdown Files (*.md;*.markdown)\0*.md;*.markdown\0"
        L"All files (*.*)\0*.*\0";
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    std::wstring dir_buf;
    if (!g_last_used_dir.empty() && std::filesystem::exists(g_last_used_dir)) {
        dir_buf = g_last_used_dir.wstring();
        dialog.lpstrInitialDir = dir_buf.c_str();
    }
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_ALLOWMULTISELECT;
    force_foreground_window();
    if (!GetOpenFileNameW(&dialog)) {
        const DWORD error = CommDlgExtendedError();
        if (error != 0) {
            post_status(L"ファイル選択ダイアログを開けませんでした (エラーコード: " + std::to_wstring(error) + L")");
        }
        return {};
    }
    const auto picked = parse_multiselect_buffer(buffer.data());
    if (!picked.empty()) g_last_used_dir = picked.front().parent_path();
    return picked;
}

// default_name/default_dir mirror main_window.py's _save_pdf_as_new_file
// suggesting "edited.pdf" in the last-used directory, and
// _save_markdown_as_pdf suggesting "<markdown filename>.pdf" -- both were
// previously missing here (dialog always opened blank at the OS default
// location).
std::optional<std::filesystem::path> prompt_save_pdf(const std::wstring& default_name = L"",
                                                       const std::filesystem::path& default_dir = {}) {
    wchar_t selected[MAX_PATH]{};
    if (!default_name.empty()) {
        wcsncpy_s(selected, MAX_PATH, default_name.c_str(), _TRUNCATE);
    }
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = g_window;
    dialog.lpstrFilter = L"PDF files (*.pdf)\0*.pdf\0\0";
    dialog.lpstrFile = selected;
    dialog.nMaxFile = MAX_PATH;
    dialog.lpstrDefExt = L"pdf";
    std::wstring dir_buf;
    if (!default_dir.empty() && std::filesystem::exists(default_dir)) {
        dir_buf = default_dir.wstring();
        dialog.lpstrInitialDir = dir_buf.c_str();
    }
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

std::wstring lowercase_extension(const std::filesystem::path& path) {
    auto ext = path.extension().wstring();
    for (auto& c : ext) c = static_cast<wchar_t>(std::towlower(c));
    return ext;
}

bool is_markdown_path(const std::filesystem::path& path) {
    const auto ext = lowercase_extension(path);
    return ext == L".md" || ext == L".markdown";
}

// Reads a UTF-8 text file whole. Used for Markdown, which -- unlike PDF --
// is read directly rather than through PdfBackend.
std::string read_text_file_utf8(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("cannot open file: " + path.u8string());
    std::string data((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
    return data;
}

void open_pdf_paths(const std::vector<std::filesystem::path>& paths);

// Loads `path` as the current Markdown document and tells the frontend to
// switch into Markdown view mode (Mermaid/MathJax rendering and PDF export
// from Markdown are not implemented in this port yet -- see
// plans/2026-08-20_*.md). The already-open PDF session (if any) is left
// untouched in memory so switching back to a PDF loses nothing, unlike the
// Python baseline's explicit discard-confirmation flow which this port
// does not reproduce.
void open_markdown_path(const std::filesystem::path& path) {
    std::string content;
    try {
        content = read_text_file_utf8(path);
    } catch (const std::exception&) {
        post_status(L"Markdownファイルを読み込めませんでした: " + path.filename().wstring());
        return;
    }
    g_current_markdown_path = path;
    if (g_window) SetWindowTextW(g_window, (L"QuickMarkPDF - " + path.filename().wstring()).c_str());
    const std::wstring response = L"{\"type\":\"markdown_opened\",\"path\":" +
                                   json_string(path.wstring()) + L",\"content\":" +
                                   json_string(utf8_to_wide(content)) + L"}";
    if (g_webview) g_webview->PostWebMessageAsString(response.c_str());
    post_status(L"Markdownを読み込みました: " + path.filename().wstring());
}

enum class DocumentOpenOutcome { Cancelled, RejectedMixed, OpenedMarkdown, OpenedPdf };

// Shared by the dialog-driven open (handle_open_documents) and the CLI-args
// startup path (see wWinMain) -- mirrors main.py's MainWindow.open_documents
// calling open_pdfs/_load_markdown_document directly to skip the dialog
// entirely, per CPP_PORT_POSTMORTEM.md's explicit recommendation not to
// rely on automating the native file dialog for verification. Matches the
// Mirrors main_window.py's open_documents() exactly: mixing PDF+Markdown in
// one selection is rejected with a real info dialog (not just a status-bar
// message, which is easy to miss), and selecting multiple Markdown files
// also gets a real dialog before silently proceeding with the first one --
// both previously silent in this port.
DocumentOpenOutcome open_document_paths(const std::vector<std::filesystem::path>& paths) {
    if (paths.empty()) {
        post_status(L"ファイル選択をキャンセルしました");
        return DocumentOpenOutcome::Cancelled;
    }

    bool has_markdown = false;
    bool has_pdf = false;
    std::filesystem::path first_markdown;
    int markdown_count = 0;
    for (const auto& path : paths) {
        if (is_markdown_path(path)) {
            has_markdown = true;
            ++markdown_count;
            if (first_markdown.empty()) first_markdown = path;
        } else {
            has_pdf = true;
        }
    }

    if (has_markdown && has_pdf) {
        const wchar_t* msg = L"Markdown と PDF の同時読み込みは未対応です。どちらか一方を選んでください。";
        if (is_test_mode()) {
            post_status(msg);
        } else {
            force_foreground_window();
            MessageBoxW(g_window, msg, L"読み込み方法", MB_OK | MB_ICONINFORMATION);
        }
        return DocumentOpenOutcome::RejectedMixed;
    }

    if (markdown_count > 1) {
        const wchar_t* msg = L"Markdown は1ファイルずつ表示します。先頭の1件を読み込みます。";
        if (is_test_mode()) {
            post_status(msg);
        } else {
            force_foreground_window();
            MessageBoxW(g_window, msg, L"読み込み方法", MB_OK | MB_ICONINFORMATION);
        }
    }

    if (has_markdown) {
        // Mirrors main_window.py's _load_markdown_document: ask before
        // discarding unsaved PDF edits, then actually discard the PDF
        // session (pdf_manager.close_all()) on confirm. Previously this
        // port left the PDF session untouched in memory when switching to
        // Markdown -- an intentional-sounding divergence that was in fact
        // just the confirmation gate never having been wired up here.
        if (!confirm_discard_dirty_state(
                is_test_mode() ? std::optional<bool>(true) : std::nullopt,
                L"保存されていない変更があります。破棄してMarkdownを開きますか？")) {
            return DocumentOpenOutcome::Cancelled;
        }
        g_manager.close_all();
        post_document_state(L"document_state");
        open_markdown_path(first_markdown);
        return DocumentOpenOutcome::OpenedMarkdown;
    }

    open_pdf_paths(paths);
    return DocumentOpenOutcome::OpenedPdf;
}

void open_pdf_paths(const std::vector<std::filesystem::path>& paths) {
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
    if (total_loaded > 0 && g_window) SetWindowTextW(g_window, L"QuickMarkPDF");
    if (!result.duplicate_files.empty()) {
        std::wstring names;
        for (std::size_t i = 0; i < result.duplicate_files.size(); ++i) {
            if (i > 0) names += L", ";
            names += std::filesystem::u8path(result.duplicate_files[i]).filename().wstring();
        }
        const std::wstring msg = L"既に読み込み済みのため読み込みをスキップしました:\n" + names;
        if (is_test_mode()) {
            post_status(msg);
        } else {
            force_foreground_window();
            MessageBoxW(g_window, msg.c_str(), L"重複ファイル", MB_OK | MB_ICONINFORMATION);
        }
    }

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

void handle_open_documents() {
    open_document_paths(prompt_open_documents());
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
                                       std::to_wstring(rendered.height) + L",\"page_width_pt\":" +
                                       std::to_wstring(rendered.page_width_pt) + L",\"page_height_pt\":" +
                                       std::to_wstring(rendered.page_height_pt) + L",\"pixels\":\"" +
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
        post_status(L"ページ順を更新しました");
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"並べ替えに失敗しました");
    }
}

void handle_rotate_pages(const std::wstring& message) {
    const int degrees = extract_int(message, L"degrees", 0);
    const auto indices = extract_size_t_array(message, L"indices");
    try {
        g_manager.rotate_pages(indices, degrees);
        if (indices.size() > 1) {
            post_status(std::to_wstring(indices.size()) + L"ページを" + std::to_wstring(degrees) + L"度回転しました");
        } else {
            post_status(L"ページを" + std::to_wstring(degrees) + L"度回転しました");
        }
        post_document_state(L"document_state");
    } catch (const std::exception&) {
        post_status(L"回転に失敗しました");
    }
}

void handle_delete_pages(const std::wstring& message) {
    const auto indices = extract_size_t_array(message, L"indices");
    g_manager.delete_pages(indices);
    if (indices.size() > 1) {
        post_status(std::to_wstring(indices.size()) + L"ページを削除しました");
    } else {
        post_status(L"ページを削除しました");
    }
    post_document_state(L"document_state");
}

void handle_undo_edit() {
    if (g_manager.undo()) {
        post_status(L"元に戻しました");
    } else {
        post_status(L"元に戻す操作がありません");
    }
    post_document_state(L"document_state");
}

void handle_close_document(const std::wstring& message) {
    const auto path = extract_string(message, L"path");
    const auto filename = std::filesystem::path(path).filename().wstring();
    if (g_manager.close_document(wide_to_utf8(path))) {
        post_status(filename + L" を閉じました");
        post_document_state(L"document_state");
    }
}

// Markdown -> PDF export via WebView2's own PrintToPdf (ICoreWebView2_7),
// mirroring main_window.py's _save_markdown_as_pdf (QWebEngineView.printToPdf,
// A4 portrait, 12mm margins). Unlike Python -- which polls
// document.body.dataset.rendered before printing, since QWebEngineView loads
// content via async navigation -- our Markdown content is set synchronously
// via markdownContent.innerHTML in the SAME script turn that handles the
// 'markdown_opened' message (no navigation involved), so by the time the
// user can even see it on screen (and click Save) it is already fully
// rendered; no readiness poll is needed here.
// The actual PrintToPdf call, factored out so the TCP test API
// (qa/check_behaviors_cpp.py) can exercise it with an explicit output path,
// bypassing the native save-as dialog -- same pattern as load_pdfs'
// injected "password" field and the QUICKMARKPDF_TEST_OPEN_PATHS hook.
void export_markdown_to_pdf(const std::filesystem::path& out_path,
                             std::function<void(bool)> on_complete = nullptr) {
    if (!g_webview) {
        post_status(L"PDF変換に失敗しました(WebViewが初期化されていません)");
        if (on_complete) on_complete(false);
        return;
    }
    ICoreWebView2_2* webview2 = nullptr;
    if (FAILED(g_webview->QueryInterface(IID_ICoreWebView2_2, reinterpret_cast<void**>(&webview2))) || !webview2) {
        post_status(L"PDF変換に失敗しました(WebView2バージョンが対応していません)");
        if (on_complete) on_complete(false);
        return;
    }
    ComPtr<ICoreWebView2_2> webview2_ptr(webview2);
    ICoreWebView2Environment* env_raw = nullptr;
    if (FAILED(webview2_ptr->get_Environment(&env_raw)) || !env_raw) {
        post_status(L"PDF変換に失敗しました(Environment取得エラー)");
        if (on_complete) on_complete(false);
        return;
    }
    ComPtr<ICoreWebView2Environment> env_ptr(env_raw);
    ICoreWebView2Environment6* env6_raw = nullptr;
    if (FAILED(env_ptr->QueryInterface(IID_ICoreWebView2Environment6, reinterpret_cast<void**>(&env6_raw))) ||
        !env6_raw) {
        post_status(L"PDF変換に失敗しました(このWebView2バージョンはPDF出力に対応していません)");
        if (on_complete) on_complete(false);
        return;
    }
    ComPtr<ICoreWebView2Environment6> env6_ptr(env6_raw);
    ICoreWebView2PrintSettings* settings_raw = nullptr;
    if (FAILED(env6_ptr->CreatePrintSettings(&settings_raw)) || !settings_raw) {
        post_status(L"PDF変換に失敗しました(PrintSettings作成エラー)");
        if (on_complete) on_complete(false);
        return;
    }
    ComPtr<ICoreWebView2PrintSettings> settings(settings_raw);
    // A4 in inches (8.27 x 11.69) with 12mm (0.4724in) margins on every
    // side -- matches main_window.py's QPageSize(A4)/QMarginsF(12,12,12,12).
    settings->put_PageWidth(8.27);
    settings->put_PageHeight(11.69);
    settings->put_MarginTop(0.4724);
    settings->put_MarginBottom(0.4724);
    settings->put_MarginLeft(0.4724);
    settings->put_MarginRight(0.4724);
    settings->put_ShouldPrintBackgrounds(TRUE);

    ICoreWebView2_7* webview7_raw = nullptr;
    if (FAILED(g_webview->QueryInterface(IID_ICoreWebView2_7, reinterpret_cast<void**>(&webview7_raw))) ||
        !webview7_raw) {
        post_status(L"PDF変換に失敗しました(このWebView2バージョンはPDF出力に対応していません)");
        if (on_complete) on_complete(false);
        return;
    }
    ComPtr<ICoreWebView2_7> webview7(webview7_raw);
    const std::wstring out_path_w = out_path.wstring();
    auto* handler = new PrintToPdfCompletedHandler(
        [out_path_w, on_complete](HRESULT errorCode, BOOL result) -> HRESULT {
            const bool ok = SUCCEEDED(errorCode) && result;
            if (ok) {
                post_status(L"PDFを保存しました: " + out_path_w);
            } else {
                post_status(L"PDF変換に失敗しました");
            }
            if (on_complete) on_complete(ok);
            return S_OK;
        });
    webview7->PrintToPdf(out_path_w.c_str(), settings.get(), handler);
    handler->Release();
    post_status(L"Markdownを PDF に変換しています...");
}

void handle_save_markdown_pdf() {
    if (g_current_markdown_path.empty()) {
        post_status(L"保存するMarkdownがありません");
        return;
    }
    const std::wstring default_name = g_current_markdown_path.stem().wstring() + L".pdf";
    const auto default_dir = g_last_used_dir.empty() ? g_current_markdown_path.parent_path() : g_last_used_dir;
    const auto picked = prompt_save_pdf(default_name, default_dir);
    if (!picked) return;
    g_last_used_dir = picked->parent_path();
    export_markdown_to_pdf(*picked);
}

// Mirrors PDFManager.suggest_export_basename() exactly: single source +
// single page -> "<stem>_pNNN"; single source + multiple pages ->
// "<stem>_selected"; multiple sources -> "selected_pages".
std::wstring suggest_export_basename(const std::vector<std::size_t>& indices) {
    if (indices.empty()) return L"selected";
    const auto infos = g_manager.page_infos();
    std::vector<quickmarkpdf::PdfManager::PageInfo> selected;
    for (auto i : indices) {
        if (i < infos.size()) selected.push_back(infos[i]);
    }
    if (selected.empty()) return L"selected";
    std::vector<std::string> unique_sources;
    for (const auto& info : selected) {
        if (std::find(unique_sources.begin(), unique_sources.end(), info.source_path) == unique_sources.end()) {
            unique_sources.push_back(info.source_path);
        }
    }
    const std::wstring stem = std::filesystem::u8path(unique_sources.front()).stem().wstring();
    if (unique_sources.size() == 1) {
        if (selected.size() == 1) {
            wchar_t buf[16];
            swprintf_s(buf, L"_p%03d", static_cast<int>(selected.front().original_page_index) + 1);
            return stem + buf;
        }
        return stem + L"_selected";
    }
    return L"selected_pages";
}

std::filesystem::path source_dir_for_pages(const std::vector<std::size_t>& indices) {
    const auto infos = g_manager.page_infos();
    for (auto i : indices) {
        if (i < infos.size()) return std::filesystem::u8path(infos[i].source_path).parent_path();
    }
    return g_last_used_dir;
}

// Mirrors main_window.py's _ask_overwrite_or_save_as(): three custom-labelled
// buttons ("上書き保存" / "新規で保存" / "キャンセル") via TaskDialogIndirect,
// rather than MessageBoxW's fixed Yes/No/Cancel wording (replaced; that was
// a known simplification). Returns "overwrite"/"save_as"/"cancel".
std::wstring ask_overwrite_or_save_as() {
    if (is_test_mode()) return L"save_as";  // never shown under TCP test automation
    force_foreground_window();

    TASKDIALOG_BUTTON buttons[] = {
        {101, L"上書き保存"},
        {102, L"新規で保存"},
    };
    TASKDIALOGCONFIG config{};
    config.cbSize = sizeof(config);
    config.hwndParent = g_window;
    config.dwFlags = TDF_ALLOW_DIALOG_CANCELLATION;
    config.pszWindowTitle = L"保存方法の選択";
    config.pszMainInstruction = L"保存方法の選択";
    config.pszContent = L"開いているファイルを上書き保存しますか？\nそれとも新しいファイルとして保存しますか？";
    config.cButtons = ARRAYSIZE(buttons);
    config.pButtons = buttons;
    config.pszMainIcon = TD_INFORMATION_ICON;

    int clicked = 0;
    if (FAILED(TaskDialogIndirect(&config, &clicked, nullptr, nullptr))) return L"cancel";
    if (clicked == 101) return L"overwrite";
    if (clicked == 102) return L"save_as";
    return L"cancel";
}

void handle_save_pdf() {
    if (g_manager.get_page_count() == 0) return;

    std::filesystem::path target;
    bool overwrite = false;

    if (g_manager.can_overwrite_source()) {
        const auto choice = ask_overwrite_or_save_as();
        if (choice == L"cancel") return;
        overwrite = (choice == L"overwrite");
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

    const auto picked = prompt_save_pdf(L"edited.pdf", g_last_used_dir);
    if (!picked) return;
    g_last_used_dir = picked->parent_path();
    if (g_manager.save_as(picked->u8string())) {
        post_status(L"保存しました: " + picked->wstring());
    } else {
        post_status(L"保存に失敗しました");
    }
    post_document_state(L"document_state");
}

// "PDF切り出し": writes the selected pages out as a brand-new PDF, leaving
// the currently open document untouched. Mirrors main_window.py's
// split_document()/_export_selected_as_pdf().
void handle_split_pdf(const std::wstring& message) {
    const auto indices = extract_size_t_array(message, L"indices");
    if (indices.empty() || g_manager.get_page_count() == 0) {
        post_status(L"PDFを切り出したいページをサムネイルで選択してください");
        return;
    }
    const auto default_name = suggest_export_basename(indices) + L".pdf";
    const auto default_dir = source_dir_for_pages(indices);
    const auto picked = prompt_save_pdf(default_name, default_dir);
    if (!picked) return;
    g_last_used_dir = picked->parent_path();
    if (g_manager.save_selected_pages(indices, picked->u8string())) {
        post_status(std::to_wstring(indices.size()) + L"ページを切り出しました: " + picked->wstring());
    } else {
        post_status(L"PDFの切り出しに失敗しました");
    }
}

// #export-overlay (templates/index.html) now supplies every field
// Python's ExportDialog does -- scope/area handled client-side (indices/
// crop already reflect the user's scope+area choice by the time this
// message arrives), format/dpi/jpeg_quality/output_dir/prefix arrive
// directly instead of the previous MessageBoxW yes/no + bare folder-picker
// + hardcoded dpi=150/quality=90/prefix="page".
void handle_export_images(const std::wstring& message) {
    if (g_manager.get_page_count() == 0) return;
    auto indices = extract_size_t_array(message, L"indices");
    const int dpi = extract_int(message, L"dpi", 150);
    const std::string fmt = wide_to_utf8(extract_string(message, L"fmt", L"png"));
    const int jpeg_quality = extract_int(message, L"jpeg_quality", 90);
    const std::string prefix = wide_to_utf8(extract_string(message, L"prefix", L"page"));
    auto output_dir = extract_string(message, L"output_dir");
    if (output_dir.empty()) {
        const auto folder = prompt_pick_folder();
        if (!folder) return;
        output_dir = folder->wstring();
    }
    g_last_used_dir = std::filesystem::path(output_dir);

    // "crop" mirrors the TCP test API's field (see dispatch_test_command):
    // an optional [x0,y0,x1,y1] PDF-point rectangle from app.js's rubber-band
    // preview selection (PreviewLabel/get_pdf_clip_rect's C++ counterpart).
    const auto crop = extract_optional_double_array4(message, L"crop");
    const auto result = g_manager.export_pages_to_images(indices, wide_to_utf8(output_dir), fmt, dpi, prefix, crop,
                                                           jpeg_quality);
    post_status(std::to_wstring(result.success) + L"/" + std::to_wstring(result.attempted) +
                L" 件の画像を書き出しました（" + (fmt == "jpg" ? L"JPEG" : L"PNG") +
                (crop ? L"、選択範囲でクロップ" : L"") + L"）");
}

// Populates #export-overlay's フォルダ/接頭辞 fields once it's already open
// (see doExport()'s post({type:'get_export_defaults', ...}) call) --
// mirrors ExportDialog's constructor computing initial_dir/suggested_prefix
// from PDFManager.get_source_dir_for_pages()/suggest_export_basename()
// before the dialog is even shown.
void handle_get_export_defaults(const std::wstring& message) {
    const auto indices = extract_size_t_array(message, L"indices");
    const auto dir = g_last_used_dir.empty() ? source_dir_for_pages(indices) : g_last_used_dir;
    const auto prefix = suggest_export_basename(indices);
    const std::wstring response = L"{\"type\":\"export_defaults\",\"output_dir\":" + json_string(dir.wstring()) +
                                   L",\"prefix\":" + json_string(prefix) + L"}";
    if (g_webview) g_webview->PostWebMessageAsString(response.c_str());
}

void handle_browse_export_folder() {
    const auto folder = prompt_pick_folder();
    if (!folder) return;
    g_last_used_dir = *folder;
    const std::wstring response = L"{\"type\":\"folder_picked\",\"path\":" + json_string(folder->wstring()) + L"}";
    if (g_webview) g_webview->PostWebMessageAsString(response.c_str());
}

// =====================
// Test API command dispatcher (see test_api_server.h)
// =====================
//
// Calls g_manager's methods directly -- the same PdfManager instance and
// methods handle_*() above call -- rather than going through app.js/the
// WebMessage bridge. Only reachable when QUICKMARKPDF_TEST_PORT is set (see
// maybe_start_test_api_server's call site in wWinMain); a normal user run
// never has this code path invoked.

// Set by export_markdown_to_pdf's completion callback. PrintToPdf is
// inherently async (its callback fires later on the same message loop that
// dispatch_test_command is itself invoked from via WM_APP_TEST_COMMAND) --
// blocking dispatch_test_command until completion would deadlock the very
// message pump PrintToPdf needs to finish, so the TCP command returns
// immediately after starting the export, and a separate polled command
// reports the result once it lands (mirrors qa/'s existing "poll, don't
// block on WebView2 async work" pattern -- see selenium_client.py's
// wait_bridge_alive docstring for why blocking on this kind of async isn't
// safe here).
std::atomic<int> g_last_markdown_pdf_result{-1};  // -1 = none yet, 0 = failed, 1 = succeeded

std::wstring get_test_state_json() {
    return L"{\"page_count\":" + std::to_wstring(g_manager.get_page_count()) + L",\"can_undo\":" +
           (g_manager.can_undo() ? L"true" : L"false") + L",\"can_overwrite\":" +
           (g_manager.can_overwrite_source() ? L"true" : L"false") + L",\"dirty\":" +
           (g_manager.is_dirty() ? L"true" : L"false") + L",\"pages\":" + pages_json() + L"}";
}

std::wstring json_string_array(const std::vector<std::string>& values) {
    std::wstring out = L"[";
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i) out += L",";
        out += json_string(utf8_to_wide(values[i]));
    }
    out += L"]";
    return out;
}

// Runs on the main thread (invoked via WM_APP_TEST_COMMAND, see
// run_test_command_on_main_thread) so every g_manager call below shares the
// exact same single-threaded-access contract handle_*() above already
// relies on -- no new locking around g_manager itself is needed.
std::wstring dispatch_test_command(const std::wstring& message) {
    const auto type = extract_type(message);
    try {
        if (type == L"get_state") {
            return get_test_state_json();
        } else if (type == L"load_pdfs") {
            const auto paths_w = extract_string_array(message, L"paths");
            std::vector<std::string> paths;
            paths.reserve(paths_w.size());
            for (const auto& p : paths_w) paths.push_back(wide_to_utf8(p));
            std::unordered_map<std::string, std::string> passwords;
            const auto password = extract_string(message, L"password");
            if (!password.empty()) {
                for (const auto& p : paths) passwords[p] = wide_to_utf8(password);
            }
            const auto result = g_manager.load_pdfs(paths, passwords);
            return L"{\"loaded_count\":" + std::to_wstring(result.loaded_count) +
                   L",\"duplicate_files\":" + json_string_array(result.duplicate_files) +
                   L",\"password_required\":" + json_string_array(result.password_required) +
                   L",\"state\":" + get_test_state_json() + L"}";
        } else if (type == L"rotate_pages") {
            g_manager.rotate_pages(extract_size_t_array(message, L"indices"), extract_int(message, L"degrees", 0));
            return get_test_state_json();
        } else if (type == L"delete_pages") {
            g_manager.delete_pages(extract_size_t_array(message, L"indices"));
            return get_test_state_json();
        } else if (type == L"reorder_pages") {
            g_manager.reorder_pages(extract_size_t_array(message, L"order"));
            return get_test_state_json();
        } else if (type == L"undo") {
            const bool ok = g_manager.undo();
            return L"{\"ok\":" + std::wstring(ok ? L"true" : L"false") + L",\"state\":" + get_test_state_json() + L"}";
        } else if (type == L"close_document") {
            const bool ok = g_manager.close_document(wide_to_utf8(extract_string(message, L"path")));
            return L"{\"ok\":" + std::wstring(ok ? L"true" : L"false") + L",\"state\":" + get_test_state_json() + L"}";
        } else if (type == L"close_all") {
            // "confirm" mirrors load_pdfs' "password" field: lets the test
            // supply the discard-confirmation answer directly. Unlike
            // confirm_discard_dirty_state (used by the real WM_CLOSE path),
            // this NEVER falls through to a real MessageBoxW -- the TCP test
            // API must never show a real dialog nothing will answer, so an
            // omitted "confirm" defaults to proceeding (true), matching
            // every pre-existing close_all call in qa/check_behaviors_cpp.py
            // that predates this parameter and doesn't pass it.
            const bool proceed = !g_manager.is_dirty() || extract_optional_bool(message, L"confirm").value_or(true);
            if (proceed) g_manager.close_all();
            return L"{\"ok\":" + std::wstring(proceed ? L"true" : L"false") + L",\"state\":" + get_test_state_json() + L"}";
        } else if (type == L"overwrite_source") {
            const bool ok = g_manager.overwrite_source();
            return L"{\"ok\":" + std::wstring(ok ? L"true" : L"false") + L"}";
        } else if (type == L"save_as") {
            const bool ok = g_manager.save_as(wide_to_utf8(extract_string(message, L"output_path")));
            return L"{\"ok\":" + std::wstring(ok ? L"true" : L"false") + L"}";
        } else if (type == L"save_selected_pages") {
            const bool ok = g_manager.save_selected_pages(extract_size_t_array(message, L"indices"),
                                                            wide_to_utf8(extract_string(message, L"output_path")));
            return L"{\"ok\":" + std::wstring(ok ? L"true" : L"false") + L"}";
        } else if (type == L"save_markdown_pdf") {
            g_last_markdown_pdf_result = -1;
            const auto out_path = std::filesystem::path(extract_string(message, L"output_path"));
            export_markdown_to_pdf(out_path, [](bool ok) { g_last_markdown_pdf_result = ok ? 1 : 0; });
            return L"{\"started\":true}";
        } else if (type == L"get_markdown_pdf_result") {
            return L"{\"result\":" + std::to_wstring(g_last_markdown_pdf_result.load()) + L"}";
        } else if (type == L"load_documents") {
            const auto paths_w = extract_string_array(message, L"paths");
            std::vector<std::filesystem::path> paths;
            paths.reserve(paths_w.size());
            for (const auto& p : paths_w) paths.push_back(std::filesystem::path(p));
            const auto outcome = open_document_paths(paths);
            const wchar_t* outcome_name = L"cancelled";
            switch (outcome) {
                case DocumentOpenOutcome::RejectedMixed: outcome_name = L"rejected_mixed"; break;
                case DocumentOpenOutcome::OpenedMarkdown: outcome_name = L"opened_markdown"; break;
                case DocumentOpenOutcome::OpenedPdf: outcome_name = L"opened_pdf"; break;
                case DocumentOpenOutcome::Cancelled: outcome_name = L"cancelled"; break;
            }
            return L"{\"outcome\":\"" + std::wstring(outcome_name) + L"\",\"state\":" + get_test_state_json() + L"}";
        } else if (type == L"export_pages_to_images") {
            const auto result = g_manager.export_pages_to_images(
                extract_size_t_array(message, L"indices"), wide_to_utf8(extract_string(message, L"output_dir")),
                wide_to_utf8(extract_string(message, L"fmt", L"png")), extract_int(message, L"dpi", 150),
                wide_to_utf8(extract_string(message, L"prefix", L"page")),
                extract_optional_double_array4(message, L"crop"),
                extract_int(message, L"jpeg_quality", 90));
            return L"{\"success\":" + std::to_wstring(result.success) + L",\"attempted\":" +
                   std::to_wstring(result.attempted) + L",\"errors\":" + json_string_array(result.errors) + L"}";
        }
        return L"{\"error\":\"unknown command\"}";
    } catch (const std::exception& ex) {
        return L"{\"error\":" + json_string(utf8_to_wide(ex.what())) + L"}";
    }
}

std::mutex g_test_mutex;
std::condition_variable g_test_cv;
std::wstring g_test_request;
std::wstring g_test_response;
bool g_test_response_ready = false;

constexpr UINT WM_APP_TEST_COMMAND = WM_APP + 1;

// Called from the TCP server thread (test_api_server.cpp, a different
// thread than the app's main/UI thread). Hands the command to the main
// thread via a plain window message and blocks until window_proc's
// WM_APP_TEST_COMMAND case has run dispatch_test_command() and posted the
// result back -- g_manager is otherwise only ever touched from the main
// thread (same as every handle_*() function above), and this preserves
// that invariant instead of adding locking around g_manager itself.
std::wstring run_test_command_on_main_thread(const std::wstring& command) {
    std::unique_lock<std::mutex> lock(g_test_mutex);
    g_test_request = command;
    g_test_response_ready = false;
    lock.unlock();

    PostMessageW(g_window, WM_APP_TEST_COMMAND, 0, 0);

    lock.lock();
    g_test_cv.wait(lock, [] { return g_test_response_ready; });
    return g_test_response;
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
        handle_open_documents();
    } else if (type == L"get_state") {
        // Read-only: re-sends the current document_state. Exists for
        // qa/check_behaviors_cpp.py, which attaches its CDP listener after
        // the process has already started (and CLI-args auto-open may have
        // already fired and been missed) -- lets it query current state on
        // demand instead of racing the initial NavigationCompleted handler.
        post_document_state(L"document_state");
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
    } else if (type == L"get_export_defaults") {
        handle_get_export_defaults(message);
    } else if (type == L"browse_export_folder") {
        handle_browse_export_folder();
    } else if (type == L"save_pdf") {
        handle_save_pdf();
    } else if (type == L"save_markdown_pdf") {
        handle_save_markdown_pdf();
    } else if (type == L"split_pdf") {
        handle_split_pdf(message);
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
                                    open_document_paths(paths);
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
    case WM_CLOSE:
        // Never intercepted by qa/*.py's own cleanup (taskkill /F /T,
        // not a graceful close), so this can't hang a headless QA run --
        // only reachable via a real user closing the window.
        if (confirm_discard_dirty_state(std::nullopt)) {
            DestroyWindow(g_window);
        }
        return 0;
    case WM_DESTROY:
        save_window_geometry(window);
        save_last_used_dir_setting();
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
    case WM_APP_TEST_COMMAND: {
        std::wstring cmd;
        {
            std::lock_guard<std::mutex> lock(g_test_mutex);
            cmd = g_test_request;
        }
        const std::wstring response = dispatch_test_command(cmd);
        {
            std::lock_guard<std::mutex> lock(g_test_mutex);
            g_test_response = response;
            g_test_response_ready = true;
        }
        g_test_cv.notify_all();
        return 0;
    }
    default:
        return DefWindowProcW(window, message, wparam, lparam);
    }
}

// Splits the command line into individual arguments (CommandLineToArgvW),
// keeping only ones that look like an existing .pdf path -- mirrors
// python/main.py's own filtering of sys.argv[1:].
std::vector<std::wstring> parse_startup_document_args(PWSTR command_line) {
    std::vector<std::wstring> result;
    if (!command_line || !*command_line) return result;
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(command_line, &argc);
    if (!argv) return result;
    for (int i = 0; i < argc; ++i) {
        std::filesystem::path candidate(argv[i]);
        const auto ext = lowercase_extension(candidate);
        if ((ext == L".pdf" || ext == L".md" || ext == L".markdown") && std::filesystem::exists(candidate)) {
            result.push_back(std::filesystem::absolute(candidate).wstring());
        }
    }
    LocalFree(argv);
    return result;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR command_line, int show_command) {
    g_startup_paths = parse_startup_document_args(command_line);

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

    // QA/test runs (extract_cpp.py's Selenium attach, check_behaviors_cpp.py's
    // TCP API) set this so the window never becomes visible on a real
    // monitor. Placing the window off-screen (large negative coordinates)
    // was tried first and made WebView2's own message bus intermittently
    // stop responding -- DWM likely treats a fully off-monitor window as
    // non-composited and throttles/skips work for it, which broke exactly
    // the postMessage delivery qa/*.py depends on. A WS_EX_LAYERED window
    // at alpha=0 stays in its normal on-screen position and fully
    // composited (so WebView2/DWM behave normally) while being genuinely
    // invisible and non-interactive to the user.
    const bool offscreen = GetEnvironmentVariableW(L"QUICKMARKPDF_OFFSCREEN", nullptr, 0) > 0;

    // CreateWindowExW's width/height are the OUTER window size, but the
    // Python spec's MainWindow.resize(1280, 820) sets its CLIENT area (what
    // extract_python.py measures via geometry()). Passing 1280x820 straight
    // through under-sizes the WebView2 content area by the title
    // bar/border chrome (measured 1264x821 instead of 1280x820).
    // AdjustWindowRectEx inflates a desired client rect to the outer size
    // needed for this window's style, so the client area actually ends up
    // 1280x820 regardless of the current DPI/theme's border metrics.
    const DWORD window_style = WS_OVERLAPPEDWINDOW;
    const DWORD window_ex_style = offscreen ? WS_EX_LAYERED : 0;

    // A saved geometry (previous session's GetWindowRect, i.e. already the
    // OUTER rect) is used as-is; falling back to the 1280x820 CLIENT default
    // goes through AdjustWindowRectEx same as before. Never loaded/applied
    // in offscreen (QA) mode -- see load_window_geometry's doc comment.
    const auto saved_geo = load_window_geometry();
    int window_x = saved_geo.x, window_y = saved_geo.y, window_w = saved_geo.width, window_h = saved_geo.height;
    if (window_x == CW_USEDEFAULT) {
        RECT client_rect{0, 0, window_w, window_h};
        AdjustWindowRectEx(&client_rect, window_style, FALSE, window_ex_style);
        window_w = client_rect.right - client_rect.left;
        window_h = client_rect.bottom - client_rect.top;
    }

    g_window = CreateWindowExW(window_ex_style, window_class.lpszClassName, L"QuickMarkPDF", window_style, window_x,
                                window_y, window_w, window_h, nullptr, nullptr, instance, nullptr);
    if (!g_window) return 1;
    load_last_used_dir_setting();

    if (offscreen) SetLayeredWindowAttributes(g_window, 0, 0, LWA_ALPHA);  // alpha=0: fully invisible

    ShowWindow(g_window, offscreen ? SW_SHOWNOACTIVATE : show_command);
    UpdateWindow(g_window);
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) return 1;
    // GetOpenFileNameW/GetSaveFileNameW's modern Explorer-style dialog is
    // documented to require OLE to be initialized (not just plain COM) --
    // without this, the common-item dialog can fail to appear at all, with
    // GetOpenFileNameW simply returning FALSE and no dialog ever shown.
    OleInitialize(nullptr);
    if (!load_ui(executable_dir, ui_path)) return 1;

    // No-ops unless QUICKMARKPDF_TEST_PORT is set -- see test_api_server.h.
    quickmarkpdf::maybe_start_test_api_server(run_test_command_on_main_thread);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    OleUninitialize();
    CoUninitialize();
    return static_cast<int>(message.wParam);
}
