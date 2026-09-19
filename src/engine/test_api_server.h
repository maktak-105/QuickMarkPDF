#pragma once

#include <functional>
#include <string>

namespace quickmarkpdf {

// Test-only TCP control server -- see test_api_server.cpp's file comment
// for the full protocol and rationale (bypasses WebView2/JS entirely so
// test automation isn't at the mercy of the browser-side message-bus
// timing issues documented in qa/).
//
// No-ops unless the QUICKMARKPDF_TEST_PORT environment variable is set to a
// port number. `dispatch` is called once per received command line (a UTF-8
// JSON object as a wide string) and must return the UTF-8 JSON response as
// a wide string; the caller (webview_main.cpp) is responsible for running
// it on the app's main thread, since it touches g_manager, which is
// otherwise only ever touched from there.
void maybe_start_test_api_server(std::function<std::wstring(const std::wstring&)> dispatch);

}  // namespace quickmarkpdf
