#!/usr/bin/env python
"""Single entry point for QuickMarkPDF's (Python/PySide6 version) automated
test program: runs the whole suite via pytest and writes a report to
tests/reports/ summarizing pass rate, failures, appearance-diff hits, and
timing.

    python python/tests/run_tests.py                        # default suite
    python python/tests/run_tests.py --real-screen
    python python/tests/run_tests.py --update-visual-baselines
    python python/tests/run_tests.py -- python/tests/test_pdf_manager.py

See document/environment.md for what each tier covers and why the dialog
guard exists.
"""
import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "python" / "tests" / "reports"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--real-screen", action="store_true",
        help="run the real_screen tier instead of the default suite (needs a visible desktop session)",
    )
    parser.add_argument(
        "--update-visual-baselines", action="store_true",
        help="overwrite visual baselines with the current render instead of comparing against them",
    )
    parser.add_argument("pytest_args", nargs="*", help="extra arguments passed straight through to pytest")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    junit_path = REPORTS_DIR / "results.xml"
    (REPORTS_DIR / "perf.json").unlink(missing_ok=True)  # start each run's timing table fresh

    env = os.environ.copy()
    if args.update_visual_baselines:
        env["QUICKMARKPDF_UPDATE_VISUAL_BASELINES"] = "1"

    cmd = [
        sys.executable, "-m", "pytest", f"--junitxml={junit_path}", "-v",
        "--cov=src", "--cov-report=term-missing",
        f"--cov-report=html:{REPORTS_DIR / 'htmlcov'}",
        f"--cov-report=json:{REPORTS_DIR / 'coverage.json'}",
    ]
    if args.real_screen:
        env["QUICKMARKPDF_REAL_SCREEN"] = "1"
        cmd += ["-m", "real_screen", "tests/real_screen"]
    cmd += args.pytest_args

    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env)

    summary = _summarize(junit_path)
    _write_markdown_report(summary)
    dashboard_path = _write_dashboard_html(summary)
    print()
    print(summary["headline"])
    print(f"Report written to {REPORTS_DIR / 'summary.md'}")
    print(f"Dashboard: {dashboard_path}")

    return result.returncode


def _summarize(junit_path: Path) -> dict:
    if not junit_path.exists():
        return {
            "headline": "No JUnit report was produced — pytest likely failed before running any tests.",
            "failed_names": [],
        }

    root = ET.parse(junit_path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")

    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    passed = total - failures - errors - skipped
    pass_rate = (passed / total * 100) if total else 0.0

    failed_names = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in suite.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]

    headline = (
        f"{passed}/{total} passed ({pass_rate:.1f}%) | {failures} failed | "
        f"{errors} errored | {skipped} skipped"
    )
    return {
        "headline": headline,
        "total": total, "passed": passed, "failed": failures,
        "errored": errors, "skipped": skipped, "pass_rate": pass_rate,
        "failed_names": failed_names,
    }


def _write_markdown_report(summary: dict):
    lines = [
        "# QuickMarkPDF Python test run",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z",
        "",
        f"**{summary['headline']}**",
        "",
    ]

    if summary.get("failed_names"):
        lines.append("## Failed")
        lines.extend(f"- `{name}`" for name in summary["failed_names"])
        lines.append("")

    perf_path = REPORTS_DIR / "perf.json"
    if perf_path.exists():
        lines.append("## Timing (tests/perf/)")
        data = json.loads(perf_path.read_text(encoding="utf-8"))
        for name, seconds in sorted(data.items()):
            lines.append(f"- `{name}`: {seconds:.3f}s")
        lines.append("")

    visual_failures_dir = REPORTS_DIR / "visual_failures"
    if visual_failures_dir.exists() and any(visual_failures_dir.iterdir()):
        lines.append("## Visual regressions")
        lines.append(f"See `{visual_failures_dir.relative_to(REPO_ROOT)}/` for actual/diff images.")
        lines.append("")

    (REPORTS_DIR / "summary.md").write_text("\n".join(lines), encoding="utf-8")


_TIER_LABELS = {
    "unit": "Unit",
    "dialog_guard": "Dialog guard",
    "integration": "Integration",
    "visual": "Visual",
    "perf": "Perf",
    "real_screen": "Real screen",
}


def _categorize(classname: str) -> str:
    if classname.startswith("tests.perf"):
        return "perf"
    if classname.startswith("tests.visual"):
        return "visual"
    if classname.startswith("tests.real_screen"):
        return "real_screen"
    if classname.startswith("tests.test_dialog_guard"):
        return "dialog_guard"
    if classname.startswith("tests.test_main_window_flows"):
        return "integration"
    return "unit"


def _write_dashboard_html(summary: dict) -> Path:
    junit_path = REPORTS_DIR / "results.xml"
    tiers: dict[str, dict] = {}
    if junit_path.exists():
        root = ET.parse(junit_path).getroot()
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        for case in suite.iter("testcase"):
            tier = _categorize(case.get("classname", ""))
            bucket = tiers.setdefault(tier, {"total": 0, "failed": 0, "skipped": 0})
            bucket["total"] += 1
            if case.find("failure") is not None or case.find("error") is not None:
                bucket["failed"] += 1
            elif case.find("skipped") is not None:
                bucket["skipped"] += 1

    perf_path = REPORTS_DIR / "perf.json"
    perf = json.loads(perf_path.read_text(encoding="utf-8")) if perf_path.exists() else {}
    max_perf = max(perf.values()) if perf else 0.0

    cov_path = REPORTS_DIR / "coverage.json"
    cov_total = None
    cov_files = []
    if cov_path.exists():
        cov_data = json.loads(cov_path.read_text(encoding="utf-8"))
        cov_total = cov_data.get("totals", {}).get("percent_covered")
        for path, info in cov_data.get("files", {}).items():
            name = Path(path).relative_to("python").as_posix() if path.startswith("python") else path
            cov_files.append((name, info["summary"]["percent_covered"]))
        cov_files.sort(key=lambda item: item[1])

    baselines_dir = REPO_ROOT / "python" / "tests" / "visual_baselines"
    visual_images = sorted(p.name for p in baselines_dir.glob("*.png")) if baselines_dir.exists() else []

    real_screen_dir = REPORTS_DIR / "real_screen"
    real_screen_images = sorted(p.name for p in real_screen_dir.glob("*.png")) if real_screen_dir.exists() else []

    pass_rate = summary.get("pass_rate", 0.0)
    status_word = "PASS" if not summary.get("failed_names") else "FAIL"

    tier_cards = "\n".join(
        f'''<div class="tier-card">
          <span class="tier-name">{_TIER_LABELS.get(tier, tier)}</span>
          <span class="tier-count">{b['total'] - b['failed'] - b['skipped']}<span class="tier-count-total">/{b['total']}</span></span>
          {f'<span class="tier-chip tier-chip-fail">{b["failed"]} failed</span>' if b['failed'] else ''}
          {f'<span class="tier-chip tier-chip-skip">{b["skipped"]} skipped</span>' if b['skipped'] else ''}
        </div>'''
        for tier, b in sorted(tiers.items(), key=lambda kv: list(_TIER_LABELS).index(kv[0]) if kv[0] in _TIER_LABELS else 99)
    )

    perf_rows = "\n".join(
        f'''<div class="perf-row">
          <span class="perf-label">{name}</span>
          <span class="perf-bar-track"><span class="perf-bar" style="width:{(seconds / max_perf * 100) if max_perf else 0:.1f}%"></span></span>
          <span class="perf-value">{seconds:.3f}s</span>
        </div>'''
        for name, seconds in sorted(perf.items(), key=lambda kv: -kv[1])
    )

    cov_rows = "\n".join(
        f'''<tr><td>{name}</td><td class="num">{pct:.0f}%</td>
          <td><span class="cov-bar-track"><span class="cov-bar" style="width:{pct:.0f}%"></span></span></td></tr>'''
        for name, pct in cov_files
    )

    visual_gallery = "\n".join(
        f'<figure><img src="../visual_baselines/{name}" loading="lazy"><figcaption>{name}</figcaption></figure>'
        for name in visual_images
    )

    real_screen_gallery = "\n".join(
        f'<figure><img src="real_screen/{name}" loading="lazy"><figcaption>{name}</figcaption></figure>'
        for name in real_screen_images
    )
    real_screen_section = f'''
        <section>
          <h2>Real-screen captures</h2>
          <div class="gallery">{real_screen_gallery}</div>
        </section>''' if real_screen_images else '''
        <section>
          <h2>Real-screen captures</h2>
          <p class="muted">Not run in this session. Run <code>python run_tests.py --real-screen</code> on a live desktop session to capture these.</p>
        </section>'''

    failed_section = ""
    if summary.get("failed_names"):
        items = "\n".join(f"<li><code>{name}</code></li>" for name in summary["failed_names"])
        failed_section = f'<section><h2>Failed tests</h2><ul class="failed-list">{items}</ul></section>'

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QuickMarkPDF test dashboard</title>
<style>
  :root {{
    --bg: #eef0ec; --surface: #ffffff; --ink: #1b2321; --ink-muted: #5b665f;
    --accent: #2a5c8a; --accent-soft: #dce8f0; --pass: #2f7d4f; --fail: #b23a2e;
    --warn: #b8842a; --border: #d8dad3;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #14181a; --surface: #1d2226; --ink: #e7eae5; --ink-muted: #98a29b;
      --accent: #6fb2e8; --accent-soft: #1e3140; --pass: #4fbe7c; --fail: #e06456;
      --warn: #e0a94f; --border: #2b3236;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #14181a; --surface: #1d2226; --ink: #e7eae5; --ink-muted: #98a29b;
    --accent: #6fb2e8; --accent-soft: #1e3140; --pass: #4fbe7c; --fail: #e06456;
    --warn: #e0a94f; --border: #2b3236;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.5 -apple-system, "Segoe UI", "Yu Gothic UI", system-ui, sans-serif;
    padding: 2.5rem 1.5rem 4rem;
  }}
  main {{ max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 2rem; }}
  header {{ display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 1rem; }}
  h1 {{ font-size: 1.4rem; margin: 0; }}
  h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-muted); margin: 0 0 .9rem; }}
  .meta {{ color: var(--ink-muted); font-size: .85rem; }}
  .headline {{ display: flex; align-items: center; gap: 1rem; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1.4rem 1.6rem; }}
  .status-pill {{ font-weight: 700; letter-spacing: .04em; padding: .35rem .8rem; border-radius: 999px; font-size: .8rem; }}
  .status-pill.pass {{ background: var(--pass); color: #fff; }}
  .status-pill.fail {{ background: var(--fail); color: #fff; }}
  .rate {{ font-size: 2.2rem; font-variant-numeric: tabular-nums; font-weight: 700; }}
  .rate-sub {{ color: var(--ink-muted); }}
  .tiers {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .8rem; }}
  .tier-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: .9rem 1rem; display: flex; flex-direction: column; gap: .3rem; }}
  .tier-name {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; color: var(--ink-muted); }}
  .tier-count {{ font-variant-numeric: tabular-nums; font-size: 1.5rem; font-weight: 700; }}
  .tier-count-total {{ font-size: 1rem; color: var(--ink-muted); font-weight: 400; }}
  .tier-chip {{ align-self: flex-start; font-size: .72rem; padding: .1rem .5rem; border-radius: 999px; }}
  .tier-chip-fail {{ background: color-mix(in srgb, var(--fail) 20%, transparent); color: var(--fail); }}
  .tier-chip-skip {{ background: color-mix(in srgb, var(--warn) 20%, transparent); color: var(--warn); }}
  .perf-row {{ display: grid; grid-template-columns: 15rem 1fr 4.5rem; align-items: center; gap: .7rem; padding: .35rem 0; }}
  .perf-label {{ font-size: .85rem; color: var(--ink-muted); }}
  .perf-bar-track {{ background: var(--accent-soft); border-radius: 4px; height: 8px; overflow: hidden; }}
  .perf-bar {{ display: block; height: 100%; background: var(--accent); border-radius: 4px; }}
  .perf-value {{ font-variant-numeric: tabular-nums; text-align: right; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  td, th {{ padding: .4rem .5rem; border-bottom: 1px solid var(--border); text-align: left; }}
  td.num {{ font-variant-numeric: tabular-nums; text-align: right; width: 3.5rem; }}
  .cov-bar-track {{ display: block; background: var(--accent-soft); border-radius: 4px; height: 6px; width: 6rem; overflow: hidden; }}
  .cov-bar {{ display: block; height: 100%; background: var(--accent); border-radius: 4px; }}
  .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: .9rem; }}
  .gallery figure {{ margin: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
  .gallery img {{ width: 100%; display: block; background: var(--bg); }}
  .gallery figcaption {{ font-size: .72rem; color: var(--ink-muted); padding: .4rem .6rem; }}
  .muted {{ color: var(--ink-muted); }}
  .failed-list {{ margin: 0; padding-left: 1.2rem; color: var(--fail); }}
  a {{ color: var(--accent); }}
  code {{ font-family: ui-monospace, "Cascadia Mono", monospace; font-size: .85em; }}
  footer {{ color: var(--ink-muted); font-size: .8rem; }}
</style>
</head>
<body>
<main>
  <header>
    <h1>QuickMarkPDF — test dashboard</h1>
    <span class="meta">Generated {datetime.now(timezone.utc).isoformat(timespec="seconds")}Z</span>
  </header>

  <section class="headline">
    <span class="status-pill {'pass' if status_word == 'PASS' else 'fail'}">{status_word}</span>
    <span class="rate">{pass_rate:.1f}%</span>
    <span class="rate-sub">{summary.get('passed', 0)}/{summary.get('total', 0)} passed
      {f"&middot; {summary.get('failed', 0)} failed" if summary.get('failed') else ''}
      {f"&middot; {summary.get('skipped', 0)} skipped" if summary.get('skipped') else ''}
      {f"&middot; coverage {cov_total:.0f}%" if cov_total is not None else ''}
    </span>
  </section>

  {failed_section}

  <section>
    <h2>Tiers</h2>
    <div class="tiers">{tier_cards}</div>
  </section>

  <section>
    <h2>Timing (tests/perf/)</h2>
    <div class="perf-table">{perf_rows if perf_rows else '<p class="muted">No perf data.</p>'}</div>
  </section>

  <section>
    <h2>Coverage by file{f' — {cov_total:.0f}% overall' if cov_total is not None else ''}</h2>
    <table>{cov_rows if cov_rows else '<tr><td class="muted">No coverage data.</td></tr>'}</table>
    <p class="meta"><a href="htmlcov/index.html">Full line-by-line coverage report &rarr;</a></p>
  </section>

  <section>
    <h2>Visual baselines</h2>
    <p class="meta">Offscreen-rendered; Japanese UI text shows as tofu boxes in this environment (no CJK font) — see document/environment.md.</p>
    <div class="gallery">{visual_gallery if visual_gallery else '<p class="muted">No baselines yet.</p>'}</div>
  </section>

  {real_screen_section}

  <footer>tests/reports/dashboard.html — regenerated by <code>python run_tests.py</code>. Not tracked in git.</footer>
</main>
</body>
</html>"""

    dashboard_path = REPORTS_DIR / "dashboard.html"
    dashboard_path.write_text(html, encoding="utf-8")
    return dashboard_path


if __name__ == "__main__":
    sys.exit(main())
