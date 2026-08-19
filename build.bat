@echo off
echo === QuickMarkPDF Native Build ===

python build_native.py
if errorlevel 1 (
    echo ERROR: build_native.py failed
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: dist\binary\QuickMarkPDF.exe
