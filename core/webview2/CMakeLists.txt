cmake_minimum_required(VERSION 3.20)
project(QuickMarkPDFWebView LANGUAGES CXX)

if (NOT WIN32 OR NOT MSVC)
    message(FATAL_ERROR "The WebView2 host requires Windows and MSVC.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(WEBVIEW2_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../third_party/webview2/build/native")
set(WEBVIEW2_INCLUDE "${WEBVIEW2_ROOT}/include")
set(WEBVIEW2_LIB "${WEBVIEW2_ROOT}/x64/WebView2Loader.dll.lib")

add_executable(QuickMarkPDF_webview WIN32 host.cpp ../native/pdf_backend.cpp)
target_include_directories(QuickMarkPDF_webview PRIVATE "${WEBVIEW2_INCLUDE}" "${CMAKE_CURRENT_LIST_DIR}/../native")
target_link_libraries(QuickMarkPDF_webview PRIVATE "${WEBVIEW2_LIB}" ole32 user32 comctl32 comdlg32)
target_compile_definitions(QuickMarkPDF_webview PRIVATE UNICODE _UNICODE NOMINMAX)
target_compile_options(QuickMarkPDF_webview PRIVATE /utf-8)

add_custom_command(TARGET QuickMarkPDF_webview POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        "${CMAKE_CURRENT_LIST_DIR}/../../third_party/webview2/runtimes/win-x64/native/WebView2Loader.dll"
        "$<TARGET_FILE_DIR:QuickMarkPDF_webview>/WebView2Loader.dll"
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        "${CMAKE_CURRENT_LIST_DIR}/../../ui"
        "$<TARGET_FILE_DIR:QuickMarkPDF_webview>/ui"
)
