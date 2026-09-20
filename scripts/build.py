import glob
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
APP = os.path.join(ROOT, "src", "app")
CLI = os.path.join(ROOT, "src", "cli")
ENGINE = os.path.join(ROOT, "src", "engine")
TESTS = os.path.join(ROOT, "tests")
INTERMEDIATE = os.path.join(ROOT, "build", "intermediate")
DIST = os.path.join(ROOT, "dist")
sys.path.insert(0, SCRIPT_DIR)
import bundle_html


def find_compiler():
    for name in ("g++", "clang++"):
        path = shutil.which(name)
        if path:
            return path
    app_data = os.environ.get("LOCALAPPDATA")
    if app_data:
        matches = glob.glob(os.path.join(app_data, "Microsoft", "WinGet", "Packages",
                            "BrechtSanders.WinLibs.MCF.UCRT_*", "mingw64", "bin", "g++.exe"))
        if matches:
            return matches[0]
    for path in (r"C:\tools\llvm-mingw\bin\clang++.exe", r"C:\Program Files\LLVM\bin\clang++.exe",
                 r"C:\msys64\ucrt64\bin\g++.exe", r"C:\msys64\mingw64\bin\g++.exe"):
        if os.path.isfile(path):
            return path
    return None


def run(command, label, cwd=None):
    print(f"\n[{label}] {' '.join(command)}")
    return subprocess.run(command, cwd=cwd).returncode == 0


def require_file(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Required build input not found: {path}")


def build():
    compiler = find_compiler()
    if not compiler:
        print("[エラー] C++ コンパイラ (g++ または clang++) が見つかりません。")
        return False
    webview_include = os.environ.get("WEBVIEW2_INCLUDE", os.path.join(ROOT, "third_party", "webview2", "build", "native", "include"))
    pdfium_include = os.environ.get("PDFIUM_INCLUDE", os.path.join(ROOT, "third_party", "pdfium", "include"))
    pdfium_dll = os.environ.get("PDFIUM_DLL", os.path.join(ROOT, "third_party", "pdfium", "bin", "pdfium.dll"))
    webview_loader = os.environ.get("WEBVIEW2_LOADER", os.path.join(ROOT, "third_party", "webview2", "runtimes", "win-x64", "native", "WebView2Loader.dll"))
    for path in (webview_include, pdfium_include):
        if not os.path.isdir(path):
            print(f"[エラー] SDK headers not found: {path}")
            return False
    for path in (pdfium_dll, webview_loader):
        require_file(path)

    os.makedirs(INTERMEDIATE, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)
    html = bundle_html.bundle(INTERMEDIATE)
    os.replace(html, os.path.join(INTERMEDIATE, "generated_index.html"))
    for source, target in ((os.path.join(ROOT, "resources", "vendor", "mathjax", "tex-svg.js"), "generated_mathjax.js"),
                           (os.path.join(ROOT, "resources", "vendor", "mermaid", "mermaid.min.js"), "generated_mermaid.js")):
        require_file(source)
        shutil.copy2(source, os.path.join(INTERMEDIATE, target))

    compiler_dir = os.path.dirname(compiler)
    windres = next((os.path.join(compiler_dir, n) for n in ("windres.exe", "llvm-windres.exe")
                    if os.path.isfile(os.path.join(compiler_dir, n))), None)
    windres = windres or shutil.which("windres") or shutil.which("llvm-windres")
    if not windres:
        print("[エラー] windres が見つかりません。")
        return False
    resource_obj = os.path.join(INTERMEDIATE, "QuickMarkPDF_res.o")
    if not run([windres, f"-I{INTERMEDIATE}", os.path.join(APP, "QuickMarkPDF.rc"), "-O", "coff", "-o", resource_obj],
               "Windows resources", cwd=APP):
        return False

    common = ["-O2", "-std=c++17", "-static", f"-I{webview_include}", f"-I{pdfium_include}", f"-I{ENGINE}", f"-I{APP}"]
    shared = [os.path.join(ENGINE, name) for name in ("engine.cpp", "pdf_backend.cpp", "image_io.cpp")]
    gui = [compiler, *common, "-mwindows", "-municode", *shared, os.path.join(APP, "main_gui.cpp"),
           os.path.join(ENGINE, "test_api_server.cpp"), resource_obj, "-o", os.path.join(DIST, "QuickMarkPDF.exe"),
           "-lkernel32", "-luser32", "-lgdi32", "-lole32", "-loleaut32", "-luuid", "-lcomctl32",
           "-lcomdlg32", "-lshell32", "-lcrypt32", "-lcredui", "-lwindowscodecs", "-lws2_32", "-lshlwapi"]
    if not run(gui, "GUI build"):
        return False
    cli = [compiler, *common, *shared, os.path.join(CLI, "main_cli.cpp"), "-o", os.path.join(DIST, "QuickMarkPDF_cli.exe"),
           "-lkernel32", "-lole32", "-loleaut32", "-lwindowscodecs"]
    if not run(cli, "CLI build"):
        return False
    shutil.copy2(pdfium_dll, DIST)
    shutil.copy2(webview_loader, DIST)
    print(f"[成功] 配布物を {DIST} に生成しました。")
    return True


def build_tests():
    compiler = find_compiler()
    if not compiler:
        print("[エラー] C++ コンパイラが見つかりません。")
        return False
    os.makedirs(INTERMEDIATE, exist_ok=True)
    pdfium_include = os.environ.get("PDFIUM_INCLUDE", os.path.join(ROOT, "third_party", "pdfium", "include"))
    pdfium_dll = os.environ.get("PDFIUM_DLL", os.path.join(ROOT, "third_party", "pdfium", "bin", "pdfium.dll"))
    exe = os.path.join(INTERMEDIATE, "engine_tests.exe")
    command = [compiler, "-O2", "-std=c++17", f"-I{pdfium_include}", f"-I{ENGINE}",
               *[os.path.join(ENGINE, name) for name in ("engine.cpp", "pdf_backend.cpp", "image_io.cpp")],
               os.path.join(TESTS, "engine_tests.cpp"), "-o", exe, "-lkernel32", "-lole32", "-loleaut32", "-lwindowscodecs"]
    if not run(command, "C++ tests build"):
        return False
    if os.path.isfile(pdfium_dll):
        shutil.copy2(pdfium_dll, INTERMEDIATE)
    for name in ("libgcc_s_seh-1.dll", "libstdc++-6.dll", "libwinpthread-1.dll"):
        path = os.path.join(os.path.dirname(compiler), name)
        if os.path.isfile(path):
            shutil.copy2(path, INTERMEDIATE)
    return run([exe], "C++ tests", cwd=INTERMEDIATE)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode not in ("all", "build", "test"):
        raise SystemExit("Usage: python scripts/build.py [all|build|test]")
    success = build_tests() if mode == "test" else build()
    if success and mode == "all":
        success = build_tests()
    raise SystemExit(0 if success else 1)
