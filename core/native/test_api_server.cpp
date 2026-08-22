// Test-only TCP control server for QuickMarkPDF.exe.
//
// Why this exists: qa/check_behaviors_cpp.py spent a full day trying to
// drive the app through its real UI surface (WebView2 CDP, then Selenium +
// Microsoft Edge WebDriver, both attaching to window.chrome.webview's
// postMessage bridge). Both were blocked by the same class of problem --
// WebView2's WebMessageReceived delivery is asynchronous and, per
// Microsoft's own docs, "not guaranteed to be sequenced" with other events;
// in practice this made the message bus intermittently silent for 10s+
// after a fresh launch or a CLI-args auto-open, for reasons never fully
// isolated. See git history on qa/*.py for the full trail.
//
// This sidesteps the browser layer entirely: it's a plain newline-delimited
// JSON TCP server, listening only when QUICKMARKPDF_TEST_PORT is set (never
// in a normal user run), that hands each command straight to the same
// PdfManager methods handle_rotate_pages() etc. call -- the C++ analog of
// how qa/check_behaviors_python.py drives window.pdf_manager directly
// in-process rather than through Qt's UI event system. It does NOT
// exercise app.js or the WebMessage bridge, so it complements rather than
// replaces qa/extract_cpp.py's DOM-level UI measurement.
//
// Protocol: client connects, writes one line of UTF-8 JSON per command
// (LF-terminated), server writes back one line of UTF-8 JSON per response.
// One connection at a time; commands are processed strictly in order.
//
// windows.h must NOT be included before winsock2.h in this translation
// unit (winsock2.h has to come first, or windows.h silently pulls in the
// incompatible legacy winsock.h) -- this is exactly why this is a separate
// .cpp from webview_main.cpp, which already includes windows.h up top for
// unrelated reasons.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include "test_api_server.h"

#include <atomic>
#include <cstdlib>
#include <string>
#include <thread>

namespace quickmarkpdf {
namespace {

std::wstring utf8_to_wide(const std::string& s) {
    if (s.empty()) return {};
    int len = MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(len, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), len);
    return out;
}

std::string wide_to_utf8(const std::wstring& s) {
    if (s.empty()) return {};
    int len = WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), nullptr, 0, nullptr, nullptr);
    std::string out(len, '\0');
    WideCharToMultiByte(CP_UTF8, 0, s.data(), static_cast<int>(s.size()), out.data(), len, nullptr, nullptr);
    return out;
}

void server_thread_main(int port, std::function<std::wstring(const std::wstring&)> dispatch) {
    WSADATA wsa_data{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) return;

    SOCKET listen_sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listen_sock == INVALID_SOCKET) {
        WSACleanup();
        return;
    }

    // Loopback-only: this server executes arbitrary PdfManager operations
    // (including writing files to disk) with zero authentication, which is
    // fine ONLY because it never listens on anything but 127.0.0.1 and only
    // when explicitly opted into via an env var a normal launch never sets.
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<u_short>(port));
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (bind(listen_sock, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) == SOCKET_ERROR) {
        closesocket(listen_sock);
        WSACleanup();
        return;
    }
    if (listen(listen_sock, 1) == SOCKET_ERROR) {
        closesocket(listen_sock);
        WSACleanup();
        return;
    }

    for (;;) {
        SOCKET client = accept(listen_sock, nullptr, nullptr);
        if (client == INVALID_SOCKET) continue;

        std::string recv_buf;
        char chunk[4096];
        for (;;) {
            const int n = recv(client, chunk, sizeof(chunk), 0);
            if (n <= 0) break;  // client disconnected or error
            recv_buf.append(chunk, static_cast<std::size_t>(n));

            std::size_t newline;
            while ((newline = recv_buf.find('\n')) != std::string::npos) {
                std::string line = recv_buf.substr(0, newline);
                recv_buf.erase(0, newline + 1);
                if (line.empty()) continue;
                if (!line.empty() && line.back() == '\r') line.pop_back();

                const std::wstring response_w = dispatch(utf8_to_wide(line));
                std::string response = wide_to_utf8(response_w);
                response.push_back('\n');
                send(client, response.data(), static_cast<int>(response.size()), 0);
            }
        }
        closesocket(client);
    }
}

}  // namespace

void maybe_start_test_api_server(std::function<std::wstring(const std::wstring&)> dispatch) {
    wchar_t buffer[32]{};
    const DWORD len = GetEnvironmentVariableW(L"QUICKMARKPDF_TEST_PORT", buffer, 32);
    if (len == 0 || len >= 32) return;

    const int port = _wtoi(buffer);
    if (port <= 0 || port > 65535) return;

    std::thread(server_thread_main, port, std::move(dispatch)).detach();
}

}  // namespace quickmarkpdf
