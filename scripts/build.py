import os
import sys
import subprocess
import shutil
import glob

# Ensure scripts directory is in sys.path for importing bundle_html
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
import bundle_html


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

    repo_root = os.path.dirname(script_dir)
    src_dir = os.path.join(repo_root, "src")
    app_dir = os.path.join(src_dir, "app")
    cli_dir = os.path.join(src_dir, "cli")
    engine_dir = os.path.join(src_dir, "engine")
    intermediate_dir = os.path.join(repo_root, "build", "intermediate")
    dist_dir = os.path.join(repo_root, "dist")

    os.makedirs(intermediate_dir, exist_ok=True)
    os.makedirs(dist_dir, exist_ok=True)

    webview2_include = os.environ.get(
        "WEBVIEW2_INCLUDE",
        os.path.join(repo_root, "third_party", "webview2", "build", "native", "include"))
    if not os.path.isdir(webview2_include):
        print(f"[エラー] WebView2 SDK headers not found: {webview2_include}")
        print("  scripts/fetch_webview2_sdk.ps1 を先に実行してください。")
        return False

    pdfium_include = os.environ.get(
        "PDFIUM_INCLUDE", os.path.join(repo_root, "third_party", "pdfium", "include"))
    if not os.path.isdir(pdfium_include):
        print(f"[エラー] PDFium headers not found: {pdfium_include}")
        print("  scripts/fetch_pdfium.ps1 を先に実行してください。")
        return False

    # 1. 自己完結HTMLを build/intermediate へバンドル生成
    bundle_html.bundle(intermediate_dir)
    bundled_index = os.path.join(intermediate_dir, "index.html")
    generated_index = os.path.join(intermediate_dir, "generated_index.html")
    if os.path.exists(bundled_index):
        if os.path.exists(generated_index):
            os.remove(generated_index)
        os.replace(bundled_index, generated_index)

    resource_assets = [
        (os.path.join(repo_root, "resources", "vendor", "mathjax", "tex-svg.js"),
         os.path.join(intermediate_dir, "generated_mathjax.js")),
        (os.path.join(repo_root, "resources", "vendor", "mermaid", "mermaid.min.js"),
         os.path.join(intermediate_dir, "generated_mermaid.js")),
    ]
    for src, dst in resource_assets:
        if not os.path.exists(src):
            print(f"[エラー] 埋め込み対象が見つかりません: {src}")
            return False
        shutil.copy2(src, dst)

    # 2. アイコン/バージョン情報/UI埋め込みリソースのコンパイル
    resource_src = os.path.join(app_dir, "QuickMarkPDF.rc")
    resource_obj = os.path.join(intermediate_dir, "QuickMarkPDF_res.o")
    windres = os.path.join(compiler_dir, "llvm-windres.exe")
    if not os.path.exists(windres):
        windres = os.path.join(compiler_dir, "windres.exe")
    if not os.path.exists(windres):
        windres = shutil.which("windres") or shutil.which("llvm-windres")
    if not windres:
        print("[エラー] Windows resource compiler (llvm-windres/windres) が見つかりませんでした。")
        return False

    cmd_windres = [
        windres,
        f"-I{app_dir}",
        f"-I{intermediate_dir}",
        resource_src,
        "-O", "coff",
        "-o", resource_obj,
    ]
    if not run(cmd_windres, cwd=app_dir, label="0/3 アイコン・UIリソース"):
        return False

    common_flags = [
        "-O2", "-std=c++17", "-static",
        f"-I{webview2_include}", f"-I{pdfium_include}", f"-I{engine_dir}", f"-I{app_dir}",
    ]
    gui_libs = [
        "-lkernel32", "-luser32", "-lgdi32", "-lole32", "-loleaut32", "-luuid",
        "-lcomctl32", "-lcomdlg32", "-lshell32", "-lcrypt32", "-lcredui", "-lwindowscodecs",
        "-lws2_32",
        "-lshlwapi",
    ]

    # 3. GUI本体 (QuickMarkPDF.exe)
    out_gui_exe = os.path.join(dist_dir, "QuickMarkPDF.exe")
    cmd_gui = [
        compiler, *common_flags, "-mwindows", "-municode",
        os.path.join(engine_dir, "engine.cpp"),
        os.path.join(engine_dir, "pdf_backend.cpp"),
        os.path.join(engine_dir, "image_io.cpp"),
        os.path.join(app_dir, "main_gui.cpp"),
        os.path.join(engine_dir, "test_api_server.cpp"),
        resource_obj,
        "-o", out_gui_exe,
        *gui_libs,
    ]
    if not run(cmd_gui, label="1/3 GUI (dist/QuickMarkPDF.exe)"):
        return False
    print(f"[成功] QuickMarkPDF.exe を生成しました ({os.path.getsize(out_gui_exe)} bytes)")

    # 4. CLI版 (QuickMarkPDF_cli.exe)
    out_cli_exe = os.path.join(dist_dir, "QuickMarkPDF_cli.exe")
    cmd_cli = [
        compiler, *common_flags,
        os.path.join(engine_dir, "engine.cpp"),
        os.path.join(engine_dir, "pdf_backend.cpp"),
        os.path.join(engine_dir, "image_io.cpp"),
        os.path.join(cli_dir, "main_cli.cpp"),
        "-o", out_cli_exe,
        "-lkernel32", "-lole32", "-loleaut32", "-lwindowscodecs",
    ]
    if not run(cmd_cli, label="2/3 CLI (dist/QuickMarkPDF_cli.exe)"):
        return False
    print(f"[成功] QuickMarkPDF_cli.exe を生成しました ({os.path.getsize(out_cli_exe)} bytes)")

    # 5. third_partyのDLLを dist へコピー
    pdfium_dll = os.environ.get("PDFIUM_DLL")
    if not pdfium_dll or not os.path.exists(pdfium_dll):
        pdfium_dll = os.path.join(repo_root, "third_party", "pdfium", "bin", "pdfium.dll")

    webview2_loader = os.environ.get("WEBVIEW2_LOADER")
    if not webview2_loader or not os.path.exists(webview2_loader):
        webview2_loader = os.path.join(repo_root, "third_party", "webview2", "runtimes", "win-x64", "native", "WebView2Loader.dll")

    for dll in (pdfium_dll, webview2_loader):
        if dll and os.path.exists(dll):
            shutil.copy2(dll, os.path.join(dist_dir, os.path.basename(dll)))
            print(f"[コピー] {os.path.basename(dll)} -> dist/")
        else:
            print(f"[警告] DLLが見つかりませんでした: {dll}")

    print(f"\n[完成] 配布用バイナリを dist/ フォルダに生成完了: {dist_dir}")
    return True


def build_tests():
    """tests/engine_tests.cpp を直接コンパイルして実行する。"""
    compiler = find_compiler()
    if not compiler:
        return False

    repo_root = os.path.dirname(script_dir)
    engine_dir = os.path.join(repo_root, "src", "engine")
    tests_dir = os.path.join(repo_root, "tests")
    intermediate_dir = os.path.join(repo_root, "build", "intermediate")
    os.makedirs(intermediate_dir, exist_ok=True)

    pdfium_include = os.environ.get(
        "PDFIUM_INCLUDE", os.path.join(repo_root, "third_party", "pdfium", "include"))
    pdfium_dll = os.environ.get(
        "PDFIUM_DLL", os.path.join(repo_root, "third_party", "pdfium", "bin", "pdfium.dll"))

    out_exe = os.path.join(intermediate_dir, "QuickMarkPDF_native_tests.exe")
    cmd = [
        compiler, "-O2", "-std=c++17", f"-I{pdfium_include}", f"-I{engine_dir}",
        os.path.join(engine_dir, "engine.cpp"),
        os.path.join(engine_dir, "pdf_backend.cpp"),
        os.path.join(engine_dir, "image_io.cpp"),
        os.path.join(tests_dir, "engine_tests.cpp"),
        "-o", out_exe,
        "-lkernel32", "-lole32", "-loleaut32", "-lwindowscodecs",
    ]
    if not run(cmd, label="C++ engine_tests"):
        return False

    if os.path.exists(pdfium_dll):
        shutil.copy2(pdfium_dll, os.path.join(intermediate_dir, "pdfium.dll"))

    print(f"\n[テスト実行] {out_exe}")
    res = subprocess.run([out_exe], cwd=intermediate_dir)
    return res.returncode == 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "app"
    if mode == "test":
        ok = build_tests()
    else:
        ok = build()
    sys.exit(0 if ok else 1)
