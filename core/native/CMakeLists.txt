cmake_minimum_required(VERSION 3.20)
project(QuickMarkPDFNative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(QuickMarkPDF_cli
    engine.cpp
    main_cli.cpp
)

target_compile_options(QuickMarkPDF_cli PRIVATE
    $<$<CXX_COMPILER_ID:GNU>:-Wall;-Wextra;-pedantic>
)
