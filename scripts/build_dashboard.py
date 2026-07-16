#!/usr/bin/env python3
"""
Orbit2 full build pipeline — the ONE command to run after any data change.

What it does, in order:
1. Re-runs scripts/scoring.py so data/scores_snapshot.json reflects the current CSVs.
2. For every vendor in the snapshot: generates a fresh Word report (scripts_node/generate_report.js),
   converts it to PDF (LibreOffice headless, via the docx skill's soffice.py), and generates a fresh
   PowerPoint deck (scripts_node/generate_pptx.js).
3. Base64-embeds all three files per vendor directly into the dashboard HTML (alongside the existing
   SNAPSHOT data), so the dashboard's Reports tab can offer instant, fully client-side downloads —
   no chat round-trip, no "click and wait" — the moment this build has run.
4. Writes the result to dashboard_rendered.html.

Why this exists: the dashboard is a sandboxed HTML artifact with no ability to execute code on its own
(no filesystem access, no shell) — it can only render what's already embedded in it. So "generate on
click, no confirmation" is implemented by generating ahead of time, every time this build runs, and
making the click itself a zero-latency local download of what's already there. Run this after every
data change (evidence filed, metric amended, manual CSV edit) to keep the embedded reports current.

Usage:
    python3 scripts/build_dashboard.py [vendor ...]

    With no arguments, builds report files for every vendor in data/weights.json.
    Pass one or more vendor names to build only those (faster if you only touched one vendor's data).

Requires: node + scripts_node/node_modules (docx, pptxgenjs) already installed;
LibreOffice available via the docx skill's scripts/office/soffice.py (path auto-detected below,
override with ORBIT2_DOCX_SKILL_DIR env var if it moves).
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
SCRIPTS_NODE_DIR = os.path.join(BASE_DIR, "scripts_node")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as app_config  # scripts/config.py

MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def find_soffice_script():
    env_override = os.environ.get("ORBIT2_DOCX_SKILL_DIR")
    candidates = []
    if env_override:
        candidates.append(os.path.join(env_override, "scripts", "office", "soffice.py"))
    candidates += [
        "/sessions/fervent-great-lovelace/mnt/.claude/skills/docx/scripts/office/soffice.py",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "Could not find the docx skill's soffice.py for PDF conversion. "
        "Set ORBIT2_DOCX_SKILL_DIR to the docx skill's base directory."
    )


def run(cmd, **kwargs):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")
    return result


def b64_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def build_vendor_reports(vendor):
    print(f"Building report files for {vendor}...")

    # 1. Word doc
    run(["node", os.path.join(SCRIPTS_NODE_DIR, "generate_report.js"), vendor])
    docx_candidates = [
        f for f in os.listdir(REPORTS_DIR)
        if f.startswith(f"Orbit2_Report_{vendor}_") and f.endswith(".docx")
    ]
    if not docx_candidates:
        raise RuntimeError(f"generate_report.js did not produce a .docx for {vendor}")
    docx_candidates.sort()
    docx_path = os.path.join(REPORTS_DIR, docx_candidates[-1])

    # 2. PDF (from the docx)
    #
    # Convert into a throwaway temp directory rather than straight into
    # REPORTS_DIR, then copy the bytes into place with a plain read+write.
    # Some sandbox sessions leave a prior run's output file at this exact
    # path in a state where LibreOffice's own overwrite (which does an
    # internal rename/replace) fails with "Operation not permitted"
    # (Io Class:Abort Code:27), even though a plain in-place byte write to
    # the same path succeeds. Converting elsewhere and copying in sidesteps
    # that without weakening anything — the final bytes on disk are
    # identical to a direct conversion.
    soffice_script = find_soffice_script()
    pdf_path = os.path.splitext(docx_path)[0] + ".pdf"
    with tempfile.TemporaryDirectory() as tmp_pdf_dir:
        run([
            "python3", soffice_script, "--headless", "--convert-to", "pdf",
            "--outdir", tmp_pdf_dir, docx_path,
        ])
        tmp_pdf_path = os.path.join(tmp_pdf_dir, os.path.basename(pdf_path))
        if not os.path.exists(tmp_pdf_path):
            raise RuntimeError(f"PDF conversion did not produce {tmp_pdf_path}")
        with open(tmp_pdf_path, "rb") as src:
            pdf_bytes = src.read()
        try:
            with open(pdf_path, "wb") as dst:
                dst.write(pdf_bytes)
        except OSError:
            # Last resort: if even an in-place write is blocked, fall back
            # to shutil.copyfile with fresh file handles before giving up.
            shutil.copyfile(tmp_pdf_path, pdf_path)
    if not os.path.exists(pdf_path):
        raise RuntimeError(f"PDF conversion did not produce {pdf_path}")

    # 3. PowerPoint deck
    run(["node", os.path.join(SCRIPTS_NODE_DIR, "generate_pptx.js"), vendor])
    pptx_candidates = [
        f for f in os.listdir(REPORTS_DIR)
        if f.startswith(f"Orbit2_Deck_{vendor}_") and f.endswith(".pptx")
    ]
    if not pptx_candidates:
        raise RuntimeError(f"generate_pptx.js did not produce a .pptx for {vendor}")
    pptx_candidates.sort()
    pptx_path = os.path.join(REPORTS_DIR, pptx_candidates[-1])

    return {
        "docx": {"filename": os.path.basename(docx_path), "data": b64_file(docx_path)},
        "pdf": {"filename": os.path.basename(pdf_path), "data": b64_file(pdf_path)},
        "pptx": {"filename": os.path.basename(pptx_path), "data": b64_file(pptx_path)},
    }


def main():
    # 1. Rescore
    print("Re-running scoring engine...")
    run(["python3", os.path.join(BASE_DIR, "scripts", "scoring.py")])

    with open(os.path.join(DATA_DIR, "scores_snapshot.json")) as f:
        snapshot = json.load(f)

    with open(os.path.join(DATA_DIR, "weights.json")) as f:
        weights = json.load(f)
    weights.pop("_comment", None)
    all_vendors = list(weights.keys())

    target_vendors = sys.argv[1:] if len(sys.argv) > 1 else all_vendors

    # 2 + 3. Build report files per vendor
    report_files = {}
    for vendor in target_vendors:
        if vendor not in all_vendors:
            print(f"Skipping unknown vendor: {vendor}")
            continue
        report_files[vendor] = build_vendor_reports(vendor)

    # merge news log (same as prior manual render step)
    import csv
    news_path = os.path.join(DATA_DIR, "news_log.csv")
    news = []
    if os.path.exists(news_path):
        with open(news_path, newline="") as f:
            news = list(csv.DictReader(f))
    snapshot["news"] = news

    # app_config.json (R1-T02) — lets generated headings read the configured
    # company/user/vendor instead of the dashboard template hard-coding them.
    config = app_config.load_config()
    config_errors = app_config.validate(config)
    if config_errors:
        print("WARNING: data/app_config.json has validation errors (using it anyway, with defaults where possible):")
        for e in config_errors:
            print(f"  [ERROR] {e}")
    snapshot["app_config"] = config

    # 4. Render dashboard.html -> dashboard_rendered.html
    template_path = os.path.join(BASE_DIR, "dashboard.html")
    with open(template_path) as f:
        html = f.read()
    html = html.replace("__SNAPSHOT_JSON__", json.dumps(snapshot, indent=2))
    html = html.replace("__REPORT_FILES_JSON__", json.dumps(report_files))

    out_path = os.path.join(BASE_DIR, "dashboard_rendered.html")
    with open(out_path, "w") as f:
        f.write(html)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"\nWrote {out_path} ({size_kb:.0f} KB) with report files embedded for: {', '.join(report_files.keys())}")


if __name__ == "__main__":
    main()
