import os
import sys
import subprocess
import shutil
import glob


def find_compiler():
    for comp in ["g++", "clang++"]:
        p = shutil.which(comp)
        if p:
            return p

    local_app_data = os.environ.get("LOCALAPPDATA")
    winget_candidates = []
    if local_app_data:
        winget_bin = os.path.join(
            local_app_data,
            "Microsoft", "WinGet", "Packages",
            "BrechtSanders.WinLibs.MCF.UCRT_*", "mingw64", "bin"
        )
        winget_candidates.extend(glob.glob(os.path.join(winget_bin, "g++.exe")))
        winget_candidates.extend(glob.glob(os.path.join(winget_bin, "clang++.exe")))
    for c in winget_candidates:
        if os.path.exists(c):
            return c

    candidates = [
        r"C:\tools\llvm-mingw\bin\clang++.exe",
        r"C:\Program Files\LLVM\bin\clang++.exe",
        r"C:\Program Files (x86)\LLVM\bin\clang++.exe",
        r"C:\msys64\ucrt64\bin\g++.exe",
        r"C:\msys64\mingw64\bin\g++.exe",
        r"C:\tools\llvm\bin\clang++.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def run(cmd, cwd=None, label=""):
    print(f"\n[{label}] {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"[失敗] {label}:")
        print(result.stdout)
        print(result.stderr)
        return False
    if result.stdout.strip():
        print(result.stdout)
    return True


def build():
    compiler = find_compiler()
    if not compiler:
        print("[エラー] C++ コンパイラ (g++ または clang++) が見つかりませんでした。")
        return False
    print(f"[発見] 使用コンパイラ: {compiler}")
    compiler_dir = os.path.dirname(compiler)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    native_dir = os.path.join(base_dir, "core", "native")

    webview2_include = os.environ.get(
        "WEBVIEW2_INCLUDE",
        os.path.join(base_dir, "third_party", "webview2", "build", "native", "include"))
    if not os.path.isdir(webview2_include):
        print(f"[エラー] WebView2 SDK headers not found: {webview2_include}")
        print("  scripts/fetch_webview2_sdk.ps1 を先に実行してください。")
        return False

    pdfium_include = os.environ.get(
        "PDFIUM_INCLUDE", os.path.join(base_dir, "third_party", "pdfium", "include"))
    if not os.path.isdir(pdfium_include):
        print(f"[エラー] PDFium headers not found: {pdfium_include}")
        print("  scripts/fetch_pdfium.ps1 を先に実行してください。")
        return False

    dist_dir = os.path.join(base_dir, "dist")
    binary_dir = os.path.join(dist_dir, "binary")
    os.makedirs(binary_dir, exist_ok=True)

    import bundle_html
    bundle_html.bundle(binary_dir)

    # 0. アイコン/バージョン情報リソース
    resource_src = os.path.join(native_dir, "QuickMarkPDF.rc")
    resource_obj = os.path.join(native_dir, "QuickMarkPDF_res.o")
    windres = os.path.join(compiler_dir, "llvm-windres.exe")
    if not os.path.exists(windres):
        windres = os.path.join(compiler_dir, "windres.exe")
    if not os.path.exists(windres):
        windres = shutil.which("windres") or shutil.which("llvm-windres")
    if not windres:
        print("[エラー] Windows resource compiler (llvm-windres/windres) が見つかりませんでした。")
        return False
    if not run([windres, resource_src, "-O", "coff", "-o", resource_obj], label="0/3 アイコンリソース"):
        return False

    common_flags = [
        "-O2", "-std=c++17", "-static",
        f"-I{webview2_include}", f"-I{pdfium_include}", f"-I{native_dir}",
    ]
    gui_libs = [
        "-lkernel32", "-luser32", "-lgdi32", "-lole32", "-loleaut32", "-luuid",
        "-lcomctl32", "-lcomdlg32", "-lshell32", "-lcrypt32", "-lcredui", "-lwindowscodecs",
    ]

    # 1. GUI本体 (WebView2ホスト)
    out_gui_exe = os.path.join(binary_dir, "QuickMarkPDF.exe")
    cmd_gui = [
        compiler, *common_flags, "-mwindows", "-municode",
        os.path.join(native_dir, "engine.cpp"),
        os.path.join(native_dir, "pdf_backend.cpp"),
        os.path.join(native_dir, "image_io.cpp"),
        os.path.join(native_dir, "webview_main.cpp"),
        resource_obj,
        "-o", out_gui_exe,
        *gui_libs,
    ]
    if not run(cmd_gui, label="1/3 GUI (dist/binary/QuickMarkPDF.exe)"):
        return False
    print(f"[成功] QuickMarkPDF.exe を生成しました ({os.path.getsize(out_gui_exe)} bytes)")

    # 2. CLI版 (engine.cpp の PdfManager が PdfBackend/image_io に依存するため、
    # 「PDFエンジン非依存のページモデルのデモ」ではなくなったが、CLIとしては
    # 引き続き軽量なデモ/検証用途)
    out_cli_exe = os.path.join(binary_dir, "QuickMarkPDF_cli.exe")
    cmd_cli = [
        compiler, *common_flags,
        os.path.join(native_dir, "engine.cpp"),
        os.path.join(native_dir, "pdf_backend.cpp"),
        os.path.join(native_dir, "image_io.cpp"),
        os.path.join(native_dir, "main_cli.cpp"),
        "-o", out_cli_exe,
        "-lkernel32", "-lole32", "-loleaut32", "-lwindowscodecs",
    ]
    if not run(cmd_cli, label="2/3 CLI (dist/binary/QuickMarkPDF_cli.exe)"):
        return False
    print(f"[成功] QuickMarkPDF_cli.exe を生成しました ({os.path.getsize(out_cli_exe)} bytes)")

    # 3. third_partyのDLLを配布フォルダへコピー
    pdfium_dll = os.path.join(base_dir, "third_party", "pdfium", "bin", "pdfium.dll")
    webview2_loader = os.path.join(base_dir, "third_party", "webview2", "runtimes", "win-x64", "native",
                                    "WebView2Loader.dll")
    for dll in (pdfium_dll, webview2_loader):
        if os.path.exists(dll):
            shutil.copy2(dll, os.path.join(binary_dir, os.path.basename(dll)))
        else:
            print(f"[警告] DLLが見つかりませんでした: {dll}")

    print(f"\n[完成] 配布用バイナリを dist/binary フォルダに生成完了: {binary_dir}")
    return True


def build_tests():
    """core/native/engine_tests.cpp を直接コンパイルして実行する(dist/binaryには含めない)。"""
    compiler = find_compiler()
    if not compiler:
        return False

    base_dir = os.path.dirname(os.path.abspath(__file__))
    native_dir = os.path.join(base_dir, "core", "native")
    pdfium_include = os.environ.get(
        "PDFIUM_INCLUDE", os.path.join(base_dir, "third_party", "pdfium", "include"))
    pdfium_dll = os.path.join(base_dir, "third_party", "pdfium", "bin", "pdfium.dll")

    out_exe = os.path.join(native_dir, "QuickMarkPDF_native_tests.exe")
    cmd = [
        compiler, "-O2", "-std=c++17", f"-I{pdfium_include}", f"-I{native_dir}",
        os.path.join(native_dir, "engine.cpp"),
        os.path.join(native_dir, "pdf_backend.cpp"),
        os.path.join(native_dir, "image_io.cpp"),
        os.path.join(native_dir, "engine_tests.cpp"),
        "-o", out_exe,
        "-lole32", "-loleaut32", "-lwindowscodecs",
    ]
    if not run(cmd, label="test 1/2 ビルド"):
        return False

    test_dll = os.path.join(native_dir, "pdfium.dll")
    if os.path.exists(pdfium_dll):
        shutil.copy2(pdfium_dll, test_dll)

    print("\n[test 2/2] 実行中...")
    result = subprocess.run([out_exe], cwd=native_dir)
    if result.returncode != 0:
        print(f"[失敗] engine_tests がエラー終了しました (code={result.returncode})")
        return False
    print("[成功] engine_tests 全件PASS")
    return True


if __name__ == "__main__":
    ok = build()
    if ok and "--skip-tests" not in sys.argv:
        ok = build_tests() and ok
    sys.exit(0 if ok else 1)
