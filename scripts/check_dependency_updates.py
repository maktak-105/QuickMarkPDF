"""Compares the third-party versions this repository uses with the latest upstream releases.

    python scripts/check_dependency_updates.py                 # table; exit 1 if something is behind
    python scripts/check_dependency_updates.py --verify-vendor # also check resources/vendor/SHA256SUMS
    python scripts/check_dependency_updates.py --update-vendor-manifest   # rewrite SHA256SUMS after replacing a vendored file

Why this exists: versions are pinned (reproducible builds), and a pin never updates itself. Without a check
the bundled PDF engine silently falls behind. The hash checks in scripts/fetch_*.ps1 prove a download is the
file that was pinned; they say nothing about how old it is. This script does, and .github/workflows/
dependency-freshness.yml runs it every week.

Where each used version comes from:
  pdfium        $pinnedRelease in scripts/fetch_pdfium.ps1          (GitHub: bblanchon/pdfium-binaries)
  WebView2 SDK  $pinnedVersion in scripts/fetch_webview2_sdk.ps1    (NuGet: Microsoft.Web.WebView2)
  Mermaid       the version string inside resources/vendor/mermaid/mermaid.min.js   (npm)
  MathJax       the VERSION string inside resources/vendor/mathjax/tex-svg.js       (npm)

Exit codes: 0 = nothing behind, 1 = something behind (or a vendored file does not match SHA256SUMS),
2 = upstream could not be queried (never reported as "up to date").
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "resources", "vendor")
MANIFEST = os.path.join(VENDOR, "SHA256SUMS")

# Dependencies that are deliberately not on the newest release. They are reported but never fail the check.
HELD = {
    "MathJax": "4.x needs its own evaluation: fully offline rendering under the CSP "
               "(see docs/investigations/2026-11-23-security-audit.md, B-4)",
}
# Dependencies tracked on one major line; a newer major is reported for information only.
TRACKED_MAJOR = {"Mermaid": 11}


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as stream:
        return stream.read()


def fetch_json(url):
    headers = {"User-Agent": "QuickMarkPDF-dependency-check", "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def version_tuple(text):
    return tuple(int(part) for part in text.split("."))


def stable_versions(names):
    return [name for name in names if re.fullmatch(r"\d+(\.\d+)+", name)]


# ---- versions in use -------------------------------------------------------
def used_pdfium():
    match = re.search(r'\$pinnedRelease\s*=\s*"chromium/(\d+)"', read_text(os.path.join(ROOT, "scripts", "fetch_pdfium.ps1")))
    if not match:
        raise RuntimeError("could not read $pinnedRelease from scripts/fetch_pdfium.ps1")
    return match.group(1)


def used_webview2():
    match = re.search(r'\$pinnedVersion\s*=\s*"([\d.]+)"', read_text(os.path.join(ROOT, "scripts", "fetch_webview2_sdk.ps1")))
    if not match:
        raise RuntimeError("could not read $pinnedVersion from scripts/fetch_webview2_sdk.ps1")
    return match.group(1)


def used_mermaid():
    text = read_text(os.path.join(VENDOR, "mermaid", "mermaid.min.js"))
    found = [v for v in re.findall(r'version:"(\d+\.\d+\.\d+)"', text) if v != "0.0.0"]
    if not found:
        raise RuntimeError("could not find the version string in mermaid.min.js")
    return found[0]


def used_mathjax():
    match = re.search(r'VERSION="(\d+\.\d+\.\d+)"', read_text(os.path.join(VENDOR, "mathjax", "tex-svg.js")))
    if not match:
        raise RuntimeError("could not find the VERSION string in tex-svg.js")
    return match.group(1)


# ---- latest upstream -------------------------------------------------------
def latest_pdfium():
    tag = fetch_json("https://api.github.com/repos/bblanchon/pdfium-binaries/releases/latest")["tag_name"]
    return tag.split("/")[-1]


def latest_webview2():
    versions = stable_versions(fetch_json("https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/index.json")["versions"])
    return max(versions, key=version_tuple)


def npm_versions(package):
    return stable_versions(fetch_json("https://registry.npmjs.org/" + package)["versions"].keys())


def latest_npm(package, major=None):
    versions = npm_versions(package)
    newest_overall = max(versions, key=version_tuple)
    if major is None:
        return newest_overall, None
    on_line = [v for v in versions if version_tuple(v)[0] == major]
    newest_on_line = max(on_line, key=version_tuple)
    return newest_on_line, (newest_overall if version_tuple(newest_overall)[0] > major else None)


def check_versions():
    rows = []  # (name, used, latest, status, note)

    def add(name, used_fn, latest_fn, numeric=False):
        used = used_fn()
        latest, newer_major = latest_fn()
        behind = (int(used) < int(latest)) if numeric else (version_tuple(used) < version_tuple(latest))
        note = ""
        if name in HELD:
            status = "held" if behind else "up to date"
            note = HELD[name] if behind else ""
        else:
            status = "BEHIND" if behind else "up to date"
        if newer_major:
            note = (note + "; " if note else "") + "newer major line available: " + newer_major + " (information only)"
        rows.append((name, used, latest, status, note))

    add("pdfium", used_pdfium, lambda: (latest_pdfium(), None), numeric=True)
    add("WebView2 SDK", used_webview2, lambda: (latest_webview2(), None))
    add("Mermaid", used_mermaid, lambda: latest_npm("mermaid", TRACKED_MAJOR["Mermaid"]))
    add("MathJax", used_mathjax, lambda: latest_npm("mathjax"))
    return rows


# ---- vendored file hashes --------------------------------------------------
def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def vendored_files():
    found = []
    for folder, _, names in os.walk(VENDOR):
        for name in names:
            if name.endswith(".js"):
                found.append(os.path.relpath(os.path.join(folder, name), VENDOR).replace(os.sep, "/"))
    return sorted(found)


def update_manifest():
    lines = ["%s  %s" % (sha256_of(os.path.join(VENDOR, rel)), rel) for rel in vendored_files()]
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines) + "\n")
    print("wrote %s (%d files)" % (os.path.relpath(MANIFEST, ROOT), len(lines)))


def verify_manifest():
    ok = True
    if not os.path.isfile(MANIFEST):
        print("vendor hashes: SHA256SUMS is missing")
        return False
    recorded = {}
    for line in read_text(MANIFEST).splitlines():
        if line.strip():
            digest, rel = line.split(None, 1)
            recorded[rel.strip()] = digest.lower()
    for rel in vendored_files():
        actual = sha256_of(os.path.join(VENDOR, rel))
        if rel not in recorded:
            print("vendor hashes: %s is not listed in SHA256SUMS" % rel)
            ok = False
        elif recorded[rel] != actual:
            print("vendor hashes: %s does not match SHA256SUMS (recorded %s..., actual %s...)" % (rel, recorded[rel][:12], actual[:12]))
            ok = False
    for rel in recorded:
        if not os.path.isfile(os.path.join(VENDOR, rel)):
            print("vendor hashes: %s is listed but missing" % rel)
            ok = False
    if ok:
        print("vendor hashes: %d file(s) match resources/vendor/SHA256SUMS" % len(recorded))
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--verify-vendor", action="store_true", help="also check resources/vendor against SHA256SUMS")
    parser.add_argument("--update-vendor-manifest", action="store_true", help="rewrite resources/vendor/SHA256SUMS and exit")
    args = parser.parse_args()

    if args.update_vendor_manifest:
        update_manifest()
        return 0

    try:
        rows = check_versions()
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as error:
        print("could not check upstream versions: %s" % error)
        return 2

    width = max(len(row[0]) for row in rows)
    print("%-*s  %-12s  %-12s  %s" % (width, "component", "in use", "latest", "status"))
    for name, used, latest, status, note in rows:
        print("%-*s  %-12s  %-12s  %s" % (width, name, used, latest, status))
        if note:
            print("%-*s    note: %s" % (width, "", note))

    failed = any(row[3] == "BEHIND" for row in rows)
    if args.verify_vendor and not verify_manifest():
        failed = True
    if failed:
        print("\nSomething is out of date or does not match. Update it (see docs/environment.md, 'Updating bundled libraries').")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
