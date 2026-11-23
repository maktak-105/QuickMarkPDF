"""Security regression checks against a QuickMarkPDF *test-API build*.

These cover what the unit tests cannot: the real WebView2 page, the native message
handlers, and process-level behaviour. They guard the fixes for the findings of
docs/investigations/2026-11-23-security-audit.md.

Build the test-API variant first (it is never shipped):

    python scripts/build.py testapi        # -> build/intermediate/QuickMarkPDF_testapi.exe

Run (needs the WebView2 Runtime; local only, not part of CI):

    python tests/e2e/security_regression.py build/intermediate/QuickMarkPDF_testapi.exe
    python tests/e2e/security_regression.py <new exe> --old-exe <exe from before the fixes>

With --old-exe, the checks whose result changed are also run against that build as a
positive control (they must show the old behaviour), and the DLL-search comparison is made.

Everything runs offscreen in a temporary folder with its own WebView2 profile; only the
processes started here are stopped (by PID).
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))
from build import find_compiler  # noqa: E402  (scripts/ is not a package)

FAILURES = []


def report(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (("  -- " + detail) if detail else ""))
    if not ok:
        FAILURES.append(name)


def note(name, value):
    print("INFO  " + name + ": " + str(value))


def fwd(path):
    return path.replace("\\", "/")


class App:
    """One launched test-API build, driven through its TCP command channel."""

    def __init__(self, exe, work, port, extra_env=None, cwd=None, keep_profile_env=False):
        env = dict(os.environ)
        env["QUICKMARKPDF_OFFSCREEN"] = "1"
        env["QUICKMARKPDF_TEST_PORT"] = str(port)
        if not keep_profile_env:
            env["WEBVIEW2_USER_DATA_FOLDER"] = os.path.join(work, "profile_%d" % port)
        env.update(extra_env or {})
        self.proc = subprocess.Popen([exe], cwd=cwd or os.path.dirname(exe), env=env)
        self.sock = None
        self.buf = b""
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=60)
                break
            except OSError:
                time.sleep(0.5)
        if not self.sock:
            self.stop()
            raise RuntimeError("test API did not come up")
        time.sleep(4)  # let WebView2 finish loading index.html

    def cmd(self, obj):
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        self.sock.sendall(line.encode("utf-8"))
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self.buf += chunk
        response, self.buf = self.buf.split(b"\n", 1)
        return json.loads(response.decode("utf-8"))

    def ui_message(self, message):
        """Runs a page message through the real native handler, as the page would send it."""
        return self.cmd({"type": "ui_message", "message": json.dumps(message, separators=(",", ":"))})

    def eval_js(self, script, timeout=8):
        started = self.cmd({"type": "eval_js", "script": script})
        if "error" in started:
            raise RuntimeError(started["error"])
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self.cmd({"type": "get_eval_result"})
            if state["state"] == 2:
                return json.loads(state["result"]) if state["result"] else None
            time.sleep(0.2)
        raise RuntimeError("eval_js timed out")

    def stop(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            time.sleep(1)


def write_min_pdf(path, size=200):
    """A structurally valid one-page PDF (the repository ignores *.pdf, so no fixture file is committed)."""
    buf = "%PDF-1.7\n"
    offsets = {}

    def add(number, body):
        nonlocal buf
        offsets[number] = len(buf)
        buf += "%d 0 obj\n%s\nendobj\n" % (number, body)

    add(1, "<< /Type /Catalog /Pages 2 0 R >>")
    add(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    add(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] >>" % (size, size))
    xref = len(buf)
    buf += "xref\n0 4\n0000000000 65535 f \n"
    buf += "".join("%010d 00000 n \n" % offsets[n] for n in (1, 2, 3))
    buf += "trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n%d\n" % xref + "%%EOF\n"
    with open(path, "w", encoding="latin-1", newline="\n") as f:
        f.write(buf)


def make_fixtures(work):
    plain = os.path.join(work, "plain.pdf")
    write_min_pdf(plain)
    payload = (
        "$<img src=x onerror=\"setInterval(()=>window.chrome.webview.postMessage(JSON.stringify("
        "{type:'export_images',indices:[],dpi:72,fmt:'png',jpeg_quality:90,"
        "output_dir:'" + fwd(work) + "/out_xss',prefix:'../xss_escaped'})),500)\">$"
    )
    evil = os.path.join(work, "evil.md")
    with open(evil, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Harmless README\n\nSome text " + payload + "\n\n"
                "![x\" onerror=\"window.chrome.webview.postMessage('{}')](a.png)\n")
    benign = os.path.join(work, "benign.md")
    with open(benign, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Doc\n\nInline $E=mc^2$ and display:\n\n$$\\int_0^1 x^2 dx$$\n\n"
                "```mermaid\nflowchart TD\n  A[Start] --> B{Choice}\n  B -->|yes| C[Done]\n```\n\n"
                "```mermaid\nsequenceDiagram\n  Alice->>Bob: Hello\n```\n\n"
                "[link](https://example.com/x) **bold** `code`\n")
    return plain, evil, benign


# ---------------------------------------------------------------------------
def check_malicious_markdown(app, work, plain, evil, expect_vulnerable):
    """V-1 end to end: a hostile .md must not be able to write files once a PDF is opened."""
    target = os.path.join(work, "xss_escaped_0001.png")
    opened = app.cmd({"type": "load_documents", "paths": [evil]})
    time.sleep(2.5)
    before = os.path.isfile(target)
    app.cmd({"type": "load_pdfs", "paths": [plain]})  # stands in for the user opening a PDF later
    time.sleep(3)
    after = os.path.isfile(target)
    detail = "outcome=%s, file before PDF=%s, after PDF=%s" % (opened.get("outcome"), before, after)
    if expect_vulnerable:
        report("[control] old build: hostile .md writes a file outside the chosen folder", after, detail)
    else:
        report("V-1: hostile .md cannot write a file once a PDF is open", not after, detail)
    app.cmd({"type": "close_all"})


def check_export_validation(app, work, plain):
    """V-2: the real export_images handler refuses unsafe prefixes / folders / dpi, and still works."""
    app.cmd({"type": "load_pdfs", "paths": [plain]})
    out = fwd(os.path.join(work, "out_v2"))

    def export(**overrides):
        message = {"type": "export_images", "indices": [], "dpi": 72, "fmt": "png", "jpeg_quality": 90,
                   "output_dir": out, "prefix": "page"}
        message.update(overrides)
        app.ui_message(message)
        time.sleep(0.4)

    export(prefix="../escaped")
    export(prefix="..\\escaped")
    export(prefix=fwd(work) + "/abs_target")
    export(prefix="a:b")
    report("V-2: '../' and absolute prefixes write nothing",
           not os.path.exists(os.path.join(work, "escaped_0001.png"))
           and not os.path.exists(os.path.join(work, "abs_target_0001.png"))
           and not os.path.exists(out))

    rel_dir = "qmpdf_relative_dir_must_not_exist"
    export(output_dir=rel_dir)
    export(output_dir="//?/C:/qmpdf_device_path_must_not_exist")
    exe_dir = os.path.dirname(app.proc.args[0])
    report("V-2: relative and device-path output folders are refused",
           not os.path.exists(os.path.join(exe_dir, rel_dir)) and not os.path.exists("C:/qmpdf_device_path_must_not_exist"))

    export(dpi=2000)
    report("V-2: dpi above the limit is refused", not os.path.exists(out))

    export()  # positive control: a valid export (test mode answers the confirmation with yes)
    report("V-2: a valid export still works", os.path.isfile(os.path.join(work, "out_v2", "page_0001.png")))
    app.cmd({"type": "close_all"})


def check_webview(app, work, benign):
    """V-1 defences and V-4 in the real WebView2."""
    settings = app.cmd({"type": "get_webview_settings"})
    report("V-4: DevTools and browser shortcut keys are disabled",
           settings.get("dev_tools") is False and settings.get("browser_accelerator_keys") is False, str(settings))
    report("V-4: status bar and standard context menu are left on",
           settings.get("status_bar") is True and settings.get("default_context_menus") is True)

    # CSP in the real page: markup injected straight into the DOM must not run.
    app.eval_js("window.__csp = 0; document.body.insertAdjacentHTML('beforeend', "
                "'<img src=\"x\" onerror=\"window.__csp=1\">'); 'inserted'")
    time.sleep(1.2)
    ran = app.eval_js("String(window.__csp)")
    report("V-1: CSP blocks an inline event handler injected into the page", ran == "0", "window.__csp=%s" % ran)

    # Navigation away from the embedded UI is cancelled.
    app.eval_js("location.href = 'https://example.com/'; 'started'")
    time.sleep(2)
    href = app.eval_js("location.href")
    report("V-1: navigating the page to another site is cancelled", str(href).startswith("https://appassets.quickmarkpdf.local/"), str(href))

    # New windows never open inside WebView2; http(s) links go to the system browser (recorded here instead).
    app.eval_js("window.open('https://example.com/ok?x=1'); 'opened'")
    time.sleep(1.5)
    first = app.cmd({"type": "get_last_external_uri"}).get("uri")
    app.eval_js("window.open('file:///C:/Windows/win.ini'); window.open('javascript:void(0)'); 'opened'")
    time.sleep(1.5)
    second = app.cmd({"type": "get_last_external_uri"}).get("uri")
    report("V-1: window.open(https) is handed to the system browser", first == "https://example.com/ok?x=1", str(first))
    report("V-1: window.open(file: / javascript:) is dropped", second == first, str(second))

    # Normal Markdown still renders under the real CSP (MathJax, Mermaid, native resource serving).
    app.eval_js("window.__v = []; document.addEventListener('securitypolicyviolation', "
                "function (e) { window.__v.push(e.violatedDirective); }); 'listening'")
    app.cmd({"type": "load_documents", "paths": [benign]})
    time.sleep(6)
    stats = json.loads(app.eval_js(
        "JSON.stringify({math: document.querySelectorAll('mjx-container').length, "
        "diagrams: document.querySelectorAll('.mermaid svg').length, violations: window.__v})"))
    report("V-1: MathJax and Mermaid render with the CSP in place",
           stats["math"] >= 2 and stats["diagrams"] == 2 and stats["violations"] == [], str(stats))
    app.cmd({"type": "close_all"})


# ---------------------------------------------------------------------------
def build_marker_dll(work):
    compiler = find_compiler()
    if not compiler:
        raise RuntimeError("no C++ compiler found for the marker DLL")
    marker = fwd(os.path.join(work, "dll_loaded.marker"))
    source = os.path.join(work, "marker.cpp")
    with open(source, "w") as f:
        f.write("#include <windows.h>\n"
                "BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {\n"
                "  if (reason == DLL_PROCESS_ATTACH) {\n"
                "    HANDLE h = CreateFileA(MARKER_PATH, GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);\n"
                "    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);\n"
                "  }\n  return TRUE;\n}\n")
    cwd_dir = os.path.join(work, "cwd_with_marker_dll")
    os.makedirs(cwd_dir, exist_ok=True)
    subprocess.run([compiler, "-shared", "-static", '-DMARKER_PATH="%s"' % marker, source, "-o",
                    os.path.join(cwd_dir, "pdfium.dll")], check=True)
    return cwd_dir, marker


def dll_search_marker_created(exe, work, plain, label, port):
    """Runs `exe` from a folder WITHOUT pdfium.dll, with a harmless marker DLL named pdfium.dll in the
    current directory, then opens a PDF. True when that planted DLL got loaded."""
    cwd_dir, marker = build_marker_dll(work)
    if os.path.exists(marker):
        os.remove(marker)
    app_dir = os.path.join(work, "app_without_pdfium_" + label)
    os.makedirs(app_dir, exist_ok=True)
    shutil.copy(exe, os.path.join(app_dir, "QuickMarkPDF.exe"))
    shutil.copy(os.path.join(os.path.dirname(exe), "WebView2Loader.dll"), app_dir)
    app = App(os.path.join(app_dir, "QuickMarkPDF.exe"), work, port, cwd=cwd_dir)
    try:
        app.cmd({"type": "load_pdfs", "paths": [plain]})
        time.sleep(1)
    finally:
        app.stop()
    return os.path.exists(marker)


def check_user_data_folder(exe, work, port):
    """S-6: the WebView2 profile goes to %LOCALAPPDATA%\\QuickMarkPDF\\WebView2, and localStorage is migrated."""
    fake_local = os.path.join(work, "fake_localappdata")
    fake_temp = os.path.join(work, "fake_temp")
    legacy_ls = os.path.join(fake_temp, "QuickMarkPDF_WVData", "EBWebView", "Default", "Local Storage")
    os.makedirs(os.path.join(legacy_ls, "leveldb"), exist_ok=True)
    os.makedirs(fake_local, exist_ok=True)
    # A name LevelDB does not recognize, so the browser leaves the file alone once it is running.
    with open(os.path.join(legacy_ls, "qmpdf_migration_marker.txt"), "w") as f:
        f.write("migration-marker")
    new_profile = os.path.join(fake_local, "QuickMarkPDF", "WebView2")
    app = App(exe, work, port, keep_profile_env=True,
              extra_env={"LOCALAPPDATA": fake_local, "TEMP": fake_temp, "TMP": fake_temp})
    try:
        time.sleep(1)
    finally:
        app.stop()
    migrated = os.path.join(new_profile, "EBWebView", "Default", "Local Storage", "qmpdf_migration_marker.txt")
    report("S-6: WebView2 profile is created under %LOCALAPPDATA%\\QuickMarkPDF\\WebView2",
           os.path.isdir(os.path.join(new_profile, "EBWebView")))
    migrated_ok = False
    if os.path.isfile(migrated):
        with open(migrated, "rb") as f:
            migrated_ok = f.read() == b"migration-marker"
    report("S-6: localStorage is copied over from the old %TEMP% profile", migrated_ok)


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", help="the test-API build to check")
    parser.add_argument("--old-exe", help="a test-API build from before the fixes, used as a positive control")
    parser.add_argument("--port", type=int, default=47140)
    parser.add_argument("--keep", action="store_true", help="keep the temporary work folder")
    args = parser.parse_args()

    exe = os.path.abspath(args.exe)
    work = tempfile.mkdtemp(prefix="qmpdf_sec_")
    note("work folder", work)
    plain, evil, benign = make_fixtures(work)
    try:
        app = App(exe, work, args.port)
        try:
            check_malicious_markdown(app, work, plain, evil, expect_vulnerable=False)
            check_export_validation(app, work, plain)
            check_webview(app, work, benign)
        finally:
            app.stop()

        check_user_data_folder(exe, work, args.port + 1)
        new_loaded = dll_search_marker_created(exe, work, plain, "new", args.port + 2)
        report("S-3: a pdfium.dll planted in the current directory is not loaded", not new_loaded)

        if args.old_exe:
            old_exe = os.path.abspath(args.old_exe)
            old_work = tempfile.mkdtemp(prefix="qmpdf_sec_old_")
            old_plain, old_evil, _ = make_fixtures(old_work)
            old_app = App(old_exe, old_work, args.port + 3)
            try:
                check_malicious_markdown(old_app, old_work, old_plain, old_evil, expect_vulnerable=True)
            finally:
                old_app.stop()
            old_loaded = dll_search_marker_created(old_exe, old_work, old_plain, "old", args.port + 4)
            report("[control] old build: the planted pdfium.dll in the current directory IS loaded", old_loaded)
            if not args.keep:
                shutil.rmtree(old_work, ignore_errors=True)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)

    print()
    if FAILURES:
        print("%d check(s) FAILED: %s" % (len(FAILURES), "; ".join(FAILURES)))
        return 1
    print("All security regression checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
