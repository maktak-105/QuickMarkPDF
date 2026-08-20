"""Thin client for QuickMarkPDF.exe's test-only TCP control API (see
core/native/test_api_server.h / .cpp and dispatch_test_command() in
webview_main.cpp) -- calls the real PdfManager methods directly, the exact
same instance and methods app.js's message handlers call, bypassing
WebView2/JS/the postMessage bridge entirely.

Why this exists: qa/cdp_client.py (raw CDP) and qa/selenium_client.py
(Selenium + Microsoft Edge WebDriver) both hit the same wall -- WebView2's
WebMessageReceived delivery is asynchronous and (per Microsoft's own docs)
"not guaranteed to be sequenced" with other events, which made the
postMessage bridge intermittently silent for 10s+ after a fresh launch,
even with sparse polling and a startup grace period. See git history on
qa/*.py for the full trail. This sidesteps the browser layer for anything
that's really a PdfManager-level check (open/rotate/delete/reorder/undo/
save/export) -- the C++ analog of how qa/check_behaviors_python.py drives
window.pdf_manager directly rather than through Qt's UI event system.

selenium_client.py + extract_cpp.py are still used for DOM-level UI
measurement (position/color) -- this client has no equivalent for that.

Run: only usable against a QuickMarkPDF.exe launched with
QUICKMARKPDF_TEST_PORT set (see connect() below); a normal user launch
never opens this port.
"""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

TEST_PORT = 9444


def kill_exe_by_name(name="QuickMarkPDF.exe"):
    subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)


def launch_exe(exe_path, port=TEST_PORT):
    kill_exe_by_name(exe_path.name)
    time.sleep(0.5)
    env = os.environ.copy()
    env["QUICKMARKPDF_TEST_PORT"] = str(port)
    env["QUICKMARKPDF_OFFSCREEN"] = "1"  # render off any real monitor, never on screen
    return subprocess.Popen([str(exe_path)], env=env)


class TestApiClient:
    def __init__(self, port=TEST_PORT, timeout=10.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self._buf = b""

    def send(self, payload):
        # separators=(",", ":") is required: the C++-side parser
        # (extract_type et al. in webview_main.cpp) matches the exact
        # `"key":` substring with no space, which is what both
        # JSON.stringify (the real JS bridge) and this client need to
        # produce -- json.dumps's default separators insert a space after
        # ':' and silently produce {"error":"unknown command"}.
        self.sock.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        while b"\n" not in self._buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("QuickMarkPDF.exeとのテストAPI接続が切れました")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        result = json.loads(line.decode("utf-8"))
        if isinstance(result, dict) and "error" in result and set(result.keys()) == {"error"}:
            raise RuntimeError(f"{payload.get('type')}: {result['error']}")
        return result

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def wait_for_port(port=TEST_PORT, timeout=10.0):
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            s.close()
            return True
        except OSError as e:
            last_err = e
            time.sleep(0.1)
    raise RuntimeError(f"テストAPIポート{port}に{timeout}秒以内に接続できませんでした(最後のエラー: {last_err})")


def connect(exe_path, port=TEST_PORT):
    proc = launch_exe(exe_path, port)
    wait_for_port(port)
    client = TestApiClient(port)
    return proc, client


def disconnect(proc, client):
    if client is not None:
        client.close()
    if proc is not None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
