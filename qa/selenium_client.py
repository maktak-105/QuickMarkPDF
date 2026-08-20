"""Drive the real, running C++/WebView2 QuickMarkPDF.exe via Selenium +
Microsoft Edge WebDriver (msedgedriver), attached to its
--remote-debugging-port -- Microsoft's officially supported way to automate
a WebView2 app:
https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/webdriver

Replaces an earlier hand-rolled raw-CDP-WebSocket client (qa/cdp_client.py,
removed): switching to Selenium's `webdriver.Edge` attach fixed the initial
connection instability, but Selenium's execute_script hits Chromium's
Runtime.evaluate the same way raw CDP did -- polling it with WebDriverWait
faster than ~1/s reproduces the exact same "renderer main thread starved,
postMessage delivery stalls" issue the raw client had (see
wait_bridge_alive's docstring). All waits here are therefore a single
time.sleep() or a sparse (>=1s interval) manual poll loop, never
WebDriverWait.

Requires qa/tools/msedgedriver.exe, matching the installed WebView2 Runtime
version exactly (see document/environment.md for how to fetch it).
"""
import json
import os
import subprocess
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service

REPO_ROOT = Path(__file__).resolve().parent.parent
DRIVER_PATH = REPO_ROOT / "qa" / "tools" / "msedgedriver.exe"
CDP_PORT = 9333


def kill_exe_by_name(name="QuickMarkPDF.exe"):
    subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)


def launch_exe(exe_path, extra_args=None, port=CDP_PORT):
    """Kill any leftover instance (stale process can hold the CDP port or the
    WebView2 user-data dir), then launch fresh with remote debugging enabled.

    Deliberately does NOT pass cwd=exe_path.parent: doing so was observed
    (with the old raw-CDP client, still true here since it's the same
    WebView2Loader startup path) to make WebView2's own startup silently
    drop the CLI-args auto-open. exe_path and extra_args are already
    absolute paths and don't need a cwd override.
    """
    kill_exe_by_name(exe_path.name)
    time.sleep(0.5)
    env = os.environ.copy()
    # --remote-allow-origins=* is required since Chromium started rejecting
    # WebSocket handshakes whose Origin header doesn't match an allow-list.
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port} --remote-allow-origins=*"
    env["QUICKMARKPDF_OFFSCREEN"] = "1"  # render off any real monitor, never on screen
    args = [str(exe_path)] + [str(a) for a in (extra_args or [])]
    return subprocess.Popen(args, env=env)


# Registers OUR OWN message listener alongside app.js's (same event, same
# window.chrome.webview bridge) so a Python-side caller can observe every
# C++->JS reply -- app.js's own post()/handlers are closed over its IIFE and
# not reachable from outside. Idempotent (checks _hooked) so re-running it
# mid-session is safe.
INSTALL_HOOK_JS = r"""
(() => {
  if (!window.__qa) window.__qa = { history: [], pages: [], canUndo: false, mode: 'pdf' };
  if (!window.__qa._hooked) {
    window.chrome.webview.addEventListener('message', (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      window.__qa.history.push(data);
      if (data.type === 'document_state' || data.type === 'pdf_opened') {
        window.__qa.pages = data.pages || [];
        window.__qa.canUndo = Boolean(data.can_undo);
      }
      if (data.type === 'markdown_opened') window.__qa.mode = 'markdown';
    });
    window.__qa._hooked = true;
  }
  return true;
})()
"""


def install_message_hook(driver):
    driver.execute_script(INSTALL_HOOK_JS)


def post_message(driver, payload):
    """Send the exact message shape app.js's own button handlers post
    (e.g. {"type": "rotate_pages", "indices": [0], "degrees": 90}) --
    exercises the real C++ message handler without simulating a DOM click.
    """
    driver.execute_script(f"window.chrome.webview.postMessage({json.dumps(json.dumps(payload))});")


def history_len(driver):
    return driver.execute_script("return window.__qa.history.length") or 0


def wait_history_grew(driver, before_len, timeout=10.0):
    # 1s minimum interval -- see wait_bridge_alive's docstring on why
    # polling execute_script faster than that stalls postMessage delivery.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        if history_len(driver) > before_len:
            return True
    return False


def send_and_wait(driver, payload, timeout=10.0):
    before = history_len(driver)
    post_message(driver, payload)
    if not wait_history_grew(driver, before, timeout):
        raise TimeoutError(f"{payload['type']} を送っても{timeout}秒以内に応答が来ませんでした")


def get_pages(driver):
    return driver.execute_script("return window.__qa.pages") or []


def get_can_undo(driver):
    return bool(driver.execute_script("return window.__qa.canUndo"))


def get_mode(driver):
    return driver.execute_script("return window.__qa.mode")


def wait_bridge_alive(driver, timeout=15.0):
    """Confirm the C++<->JS message bus is actually flowing end-to-end, not
    just that WebDriver attached. Sends the read-only `get_state` message
    (webview_main.cpp's dispatch_message; re-sends document_state, no side
    effects) and waits for a reply.

    Deliberately a SINGLE time.sleep(), not a WebDriverWait poll loop: this
    exact function polling execute_script every 0.5s reproduced the same
    "renderer main thread starved, postMessage delivery stalls" issue
    qa/cdp_client.py's docstring documented for raw CDP polling every
    0.3s -- confirmed by isolated testing, where sending get_state once and
    sleeping a flat 3s reliably saw the reply land, while polling for it
    (this function's previous implementation) failed 3/3 attempts in a row.
    Selenium's execute_script apparently hits Chromium's Runtime.evaluate
    the same way raw CDP did, so the same anti-pattern applies here too.
    """
    post_message(driver, {"type": "get_state"})
    time.sleep(min(timeout, 3.0))
    return history_len(driver) > 0


def connect(exe_path, extra_args=None, port=CDP_PORT, retries=3):
    """Launch the exe and return (proc, driver) once WebDriver has attached,
    our message hook is installed, and the C++<->JS message bus is
    confirmed live. Caller must call disconnect(proc, driver) in a finally
    block once this returns successfully.
    """
    if not DRIVER_PATH.exists():
        raise SystemExit(
            f"{DRIVER_PATH} が見つかりません。インストール済みWebView2 Runtimeのバージョンに"
            "一致するmsedgedriver.exeを取得して配置してください(document/environment.md参照)。"
        )
    last_err = None
    for attempt in range(retries):
        proc = launch_exe(exe_path, extra_args, port)
        # Root cause isolated: attaching (and sending get_state) too soon
        # after the process starts is unreliable -- the C++<->JS message
        # bus doesn't answer even though the app is not blocked on anything
        # (verified via Win32 EnumWindows: no hidden dialog, main window
        # Responding=True the whole time). Attaching 2.5s+ after launch was
        # 3/3 reliable in isolated testing versus frequent failures when
        # attaching immediately; this is a fixed grace period, not a poll.
        time.sleep(2.5)
        driver = None
        try:
            options = Options()
            options.use_webview = True
            options.debugger_address = f"localhost:{port}"
            service = Service(executable_path=str(DRIVER_PATH))
            driver = webdriver.Edge(service=service, options=options)
            install_message_hook(driver)
            if not wait_bridge_alive(driver):
                raise RuntimeError("C++<->JSメッセージバスが応答しませんでした(get_stateがタイムアウト)")
            return proc, driver
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            disconnect(proc, driver)
    raise RuntimeError(f"{retries}回試行しましたが起動できませんでした。最後のエラー: {last_err!r}")


def disconnect(proc, driver):
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
    if proc is not None:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    # driver.quit() above can fail to reap msedgedriver.exe itself (e.g. if
    # the session was already unhealthy when we tried to close it) --
    # leaving it running was observed to make the NEXT connect() attempt
    # fail immediately with SessionNotCreatedException (it tries to reuse
    # the same debugger port). Not a blanket-kill risk the way
    # msedgedriver.exe's name might suggest: nothing else in this project
    # runs a process by that name.
    subprocess.run(["taskkill", "/F", "/IM", "msedgedriver.exe"], capture_output=True)
