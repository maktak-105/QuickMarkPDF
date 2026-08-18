#include <windows.h>

#include <filesystem>
#include <string>

#include <WebView2.h>
#include <wrl.h>
#include <wrl/event.h>

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

namespace {
HWND g_window = nullptr;
ComPtr<ICoreWebView2Controller> g_controller;
ComPtr<ICoreWebView2> g_webview;

std::wstring file_url(const std::filesystem::path& path) {
    std::wstring value = L"file:///" + path.generic_wstring();
    return value;
}

void resize_webview() {
    if (!g_controller) return;
    RECT bounds{};
    GetClientRect(g_window, &bounds);
    g_controller->put_Bounds(bounds);
}

void load_ui(const std::filesystem::path& ui_path) {
    CreateCoreWebView2EnvironmentWithOptions(
        nullptr, nullptr, nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [ui_path](HRESULT result, ICoreWebView2Environment* environment) -> HRESULT {
                if (FAILED(result) || environment == nullptr) return result;
                return environment->CreateCoreWebView2Controller(
                    g_window,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [ui_path](HRESULT controller_result,
                                  ICoreWebView2Controller* controller) -> HRESULT {
                            if (FAILED(controller_result) || controller == nullptr) {
                                return controller_result;
                            }
                            g_controller = controller;
                            g_controller->get_CoreWebView2(&g_webview);
                            EventRegistrationToken message_token{};
                            g_webview->add_WebMessageReceived(
                                Callback<ICoreWebView2WebMessageReceivedEventHandler>(
                                    [](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
                                        LPWSTR raw_message = nullptr;
                                        if (FAILED(args->TryGetWebMessageAsString(&raw_message))) {
                                            return S_OK;
                                        }
                                        const std::wstring message(raw_message);
                                        CoTaskMemFree(raw_message);
                                        if (message.find(L"open_pdf") != std::wstring::npos) {
                                            g_webview->PostWebMessageAsString(
                                                L"{\"type\":\"backend_status\",\"message\":\"PDFバックエンド接続待ち\"}");
                                        } else if (message.find(L"save_pdf") != std::wstring::npos) {
                                            g_webview->PostWebMessageAsString(
                                                L"{\"type\":\"backend_status\",\"message\":\"保存機能はPDFエンジン接続後に有効になります\"}");
                                        }
                                        return S_OK;
                                    })
                                    .Get(),
                                &message_token);
                            resize_webview();
                            g_webview->Navigate(file_url(ui_path).c_str());
                            return S_OK;
                        })
                        .Get());
            })
            .Get());
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    switch (message) {
    case WM_SIZE:
        resize_webview();
        return 0;
    case WM_DESTROY:
        g_webview.Reset();
        g_controller.Reset();
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
    const auto ui_path = std::filesystem::absolute(executable_dir / L"ui" / L"index.html");

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
    load_ui(ui_path);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    CoUninitialize();
    return static_cast<int>(message.wParam);
}
