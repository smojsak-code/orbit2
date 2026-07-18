#!/usr/bin/env python3
"""
Orbit2 Release 1 validation — the single command required by R1-T09.

Runs, in order, everything the roadmap's own instruction #55 asks for:
  1. Data validation      (scripts/validate_data.py against the REAL data/)
  2. Python unit tests    (pytest, entirely against tests/fixtures/ — never
                            touches the real data/ directory; see
                            tests/conftest.py)
  3. Scoring engine        (scripts/scoring.py — recomputes scores_snapshot.json
                            from the real data/, same as any normal rebuild)
  4. Web build + report
     generation smoke test (scripts/build_web.py — rebuilds
                            data/web_snapshot.json, index.html, and
                            generates a fresh Word/PDF/PowerPoint report per
                            vendor; this step *is* the "Word and PowerPoint
                            generators complete a smoke run" acceptance
                            criterion, verified below by checking the
                            resulting files exist and are non-empty)
  5. HTML structural checks (scripts/check_html.py — duplicate IDs, missing
                            navigation targets, on both dashboard.html and
                            web/index_template.html)

Exits non-zero if ANY step fails (acceptance criterion). Prints a per-step
PASS/FAIL summary at the end either way.

IMPORTANT — "tests do not modify production data" (acceptance criterion):
step 2 (pytest) is fully isolated from data/ (see tests/conftest.py's
fixture_data_dir). Steps 1, 3, 4, and 5 are read-mostly/rebuild operations
against the REAL data/ directory — exactly the same operations
scripts/build_dashboard.py, scripts/build_web.py, and scripts/validate_data.py
already perform on every normal task in this project (regenerating
scores_snapshot.json/web_snapshot.json/reports/* is not "modifying data",
it's rebuilding derived artifacts from data that's already there). No step
in this script ever writes a fabricated/test row into actions.csv,
value_journal.jsonl, objectives.csv, or any other register.

Release 1 must not be declared complete until this script exits 0 against a
FRESH CLONE of the repository (roadmap instruction #58) — running it only in
the long-lived working copy is not sufficient, since a fresh clone is the
only way to catch a file that works locally but was never actually
committed/pushed. See docs/testing.md for the exact clean-checkout procedure.

Usage:
    python3 scripts/validate_release.py
    python3 scripts/validate_release.py --skip-web-build   # faster local iteration; skips step 4
"""
import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")


class Step:
    def __init__(self, name):
        self.name = name
        self.ok = None
        self.detail = ""


def run_step(name, func):
    step = Step(name)
    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
    try:
        ok, detail = func()
        step.ok = ok
        step.detail = detail
    except Exception as e:  # noqa: BLE001 - a step raising is itself a failure to report, not a crash
        step.ok = False
        step.detail = f"raised {type(e).__name__}: {e}"
    status = "PASS" if step.ok else "FAIL"
    print(f"--- {status}: {name}" + (f" — {step.detail}" if step.detail else ""))
    return step


def _run(cmd, cwd=BASE_DIR):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result


def step_validate_data():
    result = _run(["python3", "scripts/validate_data.py"])
    return result.returncode == 0, f"exit code {result.returncode}"


def step_pytest():
    result = _run(["python3", "-m", "pytest", "tests/", "-q"])
    last_line = [l for l in result.stdout.strip().splitlines() if l.strip()][-1] if result.stdout.strip() else ""
    return result.returncode == 0, last_line


def step_scoring():
    result = _run(["python3", "scripts/scoring.py"])
    return result.returncode == 0, f"exit code {result.returncode}"


def check_report_files_exist(reports_dir, vendors):
    """Pure check, no subprocess/build involved — given a reports/ directory
    and an iterable of vendor names, confirm each has a non-empty Word
    report and PowerPoint deck already on disk. Naming convention matches
    scripts/build_dashboard.py's own build_vendor_reports(): Word reports
    are "Orbit2_Report_<vendor>_*", PowerPoint decks are
    "Orbit2_Deck_<vendor>_*" — deliberately different prefixes, not just a
    different extension. Returns (ok, detail_string). Separated out from
    step_web_build() so it's unit-testable without needing a real build
    (see tests/test_validate_release.py)."""
    if not vendors:
        return False, "no vendors configured — nothing to smoke-test reports against"

    missing = []
    for vendor in vendors:
        docx_candidates = [
            f for f in os.listdir(reports_dir)
            if f.startswith(f"Orbit2_Report_{vendor}_") and f.endswith(".docx")
        ] if os.path.isdir(reports_dir) else []
        pptx_candidates = [
            f for f in os.listdir(reports_dir)
            if f.startswith(f"Orbit2_Deck_{vendor}_") and f.endswith(".pptx")
        ] if os.path.isdir(reports_dir) else []
        if not docx_candidates:
            missing.append(f"{vendor}: no .docx report found")
        elif os.path.getsize(os.path.join(reports_dir, sorted(docx_candidates)[-1])) == 0:
            missing.append(f"{vendor}: .docx report is empty")
        if not pptx_candidates:
            missing.append(f"{vendor}: no .pptx report found")
        elif os.path.getsize(os.path.join(reports_dir, sorted(pptx_candidates)[-1])) == 0:
            missing.append(f"{vendor}: .pptx report is empty")

    if missing:
        return False, "; ".join(missing)
    return True, f"report smoke test OK for {len(vendors)} vendor(s)"


def step_web_build():
    result = _run(["python3", "scripts/build_web.py"])
    if result.returncode != 0:
        return False, f"exit code {result.returncode}"

    snapshot_path = os.path.join(BASE_DIR, "data", "web_snapshot.json")
    if not os.path.exists(snapshot_path) or os.path.getsize(snapshot_path) == 0:
        return False, "data/web_snapshot.json missing or empty after build"

    # "Current Word and PowerPoint generators complete a smoke run" —
    # verified here by confirming build_web.py's call to
    # build_dashboard.build_vendor_reports() actually produced non-empty
    # .docx/.pptx files for at least one vendor, not just that the build
    # script exited 0.
    import json
    with open(os.path.join(BASE_DIR, "data", "weights.json")) as f:
        weights = json.load(f)
    weights.pop("_comment", None)

    return check_report_files_exist(REPORTS_DIR, list(weights.keys()))


def step_html_checks():
    result = _run(["python3", "scripts/check_html.py", "dashboard.html", os.path.join("web", "index_template.html")])
    return result.returncode == 0, f"exit code {result.returncode}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-web-build", action="store_true",
                     help="Skip step 4 (web build + report smoke test) — faster for local iteration, "
                          "but a full validate_release.py run (no skips) is required before declaring "
                          "Release 1 complete.")
    args = ap.parse_args()

    steps = []
    steps.append(run_step("1. Data validation (scripts/validate_data.py)", step_validate_data))
    steps.append(run_step("2. Python unit tests (pytest tests/)", step_pytest))
    steps.append(run_step("3. Scoring engine (scripts/scoring.py)", step_scoring))
    if args.skip_web_build:
        print("\n--- SKIPPED: 4. Web build + report smoke test (--skip-web-build)")
    else:
        steps.append(run_step("4. Web build + report smoke test (scripts/build_web.py)", step_web_build))
    steps.append(run_step("5. HTML structural checks (scripts/check_html.py)", step_html_checks))

    print(f"\n{'=' * 70}\nRelease 1 validation summary\n{'=' * 70}")
    for s in steps:
        print(f"  [{'PASS' if s.ok else 'FAIL'}] {s.name}" + (f" — {s.detail}" if s.detail else ""))

    all_ok = all(s.ok for s in steps)
    if all_ok:
        print("\nAll checks passed." +
              (" (--skip-web-build was used — run once WITHOUT it before declaring Release 1 complete.)"
               if args.skip_web_build else ""))
    else:
        print("\nOne or more checks FAILED. Release 1 is not ready.")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
