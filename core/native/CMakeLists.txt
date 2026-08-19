cmake_minimum_required(VERSION 3.20)
project(QuickMarkPDFNative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(PDFIUM_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../third_party/pdfium")
set(PDFIUM_INCLUDE "${PDFIUM_ROOT}/include")
set(PDFIUM_DLL "${PDFIUM_ROOT}/bin/pdfium.dll")

add_executable(QuickMarkPDF_cli
    engine.cpp
    pdf_backend.cpp
    main_cli.cpp
)

add_executable(QuickMarkPDF_native_tests
    engine.cpp
    pdf_backend.cpp
    engine_tests.cpp
)

foreach(target QuickMarkPDF_cli QuickMarkPDF_native_tests)
    target_include_directories(${target} PRIVATE "${PDFIUM_INCLUDE}")
    target_compile_options(${target} PRIVATE
        $<$<CXX_COMPILER_ID:GNU>:-Wall;-Wextra;-pedantic>
    )
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${PDFIUM_DLL}" "$<TARGET_FILE_DIR:${target}>/pdfium.dll"
    )
endforeach()

enable_testing()
add_test(NAME QuickMarkPDF.native_model COMMAND QuickMarkPDF_native_tests)
