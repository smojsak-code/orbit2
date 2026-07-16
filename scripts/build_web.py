#!/usr/bin/env python3
"""
Orbit2 web build — produces the static bundle served live by GitHub Pages at the repo root:

  index.html               copied from web/index_template.html (rarely changes; fetches its data
                            fresh on every page load, so this almost never needs to be re-pushed)
  data/web_snapshot.json   vendors, news, evidence, changelog, category registry, and a manifest
                            of which report files exist per vendor (filenames only — the files
                            themselves are plain static downloads, not embedded)
  reports/*.docx/.pdf/.pptx  same report files build_dashboard.py produces, reused here

Why this is a separate build from build_dashboard.py: the Cowork artifact (build_dashboard.py)
has no filesystem of its own, so it must embed everything (data + report bytes) directly into the
HTML it pushes. A GitHub Pages site IS a filesystem — index.html can just fetch data/web_snapshot.json
and link straight to reports/*.docx, so nothing needs to be base64-embedded or republished except
when the page's own code changes (rare) or the data/reports actually change (routine).

Run this after any data change, then commit + push data/, reports/, and (if it changed) index.html
to GitHub. That's the one manual/automatable step that makes the live site reflect the change.

Usage:
    python3 scripts/build_web.py [vendor ...]
"""
import csv
import json
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, SCRIPTS_DIR)
import build_dashboard as bd  # reuses run() + build_vendor_reports() — same generation logic


def main():
    print("Re-running scoring engine...")
    bd.run(["python3", os.path.join(BASE_DIR, "scripts", "scoring.py")])

    with open(os.path.join(DATA_DIR, "scores_snapshot.json")) as f:
        snapshot = json.load(f)
    with open(os.path.join(DATA_DIR, "weights.json")) as f:
        weights = json.load(f)
    weights.pop("_comment", None)
    all_vendors = list(weights.keys())
    target_vendors = sys.argv[1:] if len(sys.argv) > 1 else all_vendors

    report_manifest = {}
    for vendor in target_vendors:
        if vendor not in all_vendors:
            print(f"Skipping unknown vendor: {vendor}")
            continue
        files = bd.build_vendor_reports(vendor)  # generates docx/pdf/pptx on disk in reports/
        report_manifest[vendor] = {fmt: info["filename"] for fmt, info in files.items()}

    news_path = os.path.join(DATA_DIR, "news_log.csv")
    news = []
    if os.path.exists(news_path):
        with open(news_path, newline="") as f:
            news = list(csv.DictReader(f))
    snapshot["news"] = news
    snapshot["report_files"] = report_manifest

    # app_config.json (R1-T02) — same config the Cowork dashboard embeds, so
    # generated headings on the public site read the configured company/user
    # instead of a hard-coded string.
    config = bd.app_config.load_config()
    config_errors = bd.app_config.validate(config)
    if config_errors:
        print("WARNING: data/app_config.json has validation errors (using it anyway, with defaults where possible):")
        for e in config_errors:
            print(f"  [ERROR] {e}")
    snapshot["app_config"] = config

    out_path = os.path.join(DATA_DIR, "web_snapshot.json")
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Wrote {out_path}")

    template_path = os.path.join(BASE_DIR, "web", "index_template.html")
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(template_path):
        shutil.copyfile(template_path, index_path)
        print(f"Copied {template_path} -> {index_path}")
    else:
        print(f"WARNING: {template_path} not found — index.html was not updated.")


if __name__ == "__main__":
    main()
