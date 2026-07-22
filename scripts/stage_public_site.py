#!/usr/bin/env python3
"""
Build public_site/ — the ONLY folder the Cloudflare Worker is configured
to serve (2026-07-22, Steve's request to lock the platform behind a
login).

Why this exists: while setting up the Cloudflare move, we found that
GitHub Pages had always served the ENTIRE repo as static files — raw
data/*.csv (bypassing every visibility filter build_web.py applies, which
only curates data/web_snapshot.json), old superseded report files, and
the Cowork dashboard artifacts (dashboard.html/dashboard_rendered.html,
which embed full private detail unconditionally, by design, for the
private surface). Moving to Cloudflare is also the fix for this — but
only if the Worker's static-asset directory is a curated allowlist, not
the repo root.

This script builds that allowlist explicitly: only files copied into
public_site/ by name, below, are ever reachable through the new Worker,
regardless of the login gate. A new file added anywhere else in the repo
in the future (a new CSV, a new private report, a new dashboard artifact)
is automatically NOT public unless someone deliberately adds it to this
script too — allowlist, not blocklist, so nothing leaks by default.

Run after scripts/build_web.py (needs its output — index.html,
data/web_snapshot.json, reports/* — to already exist and be current).

Usage:
    python3 scripts/build_web.py
    python3 scripts/stage_public_site.py
"""
import json
import os
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, "public_site")

# The only web/assets/*.js files index.html actually references (checked
# via grep against index.html's own <script src="..."> tags) — everything
# else under web/ (index_template.html, any future asset not yet wired
# in) is deliberately NOT copied unless added here.
WEB_ASSET_FILES = ["home.js", "impact.js"]


def _clean(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)


def stage_reports(snapshot):
    """Only the CURRENT report files referenced by web_snapshot.json's own
    manifests (report_files per vendor, objectives_report_files) — NOT
    every file that happens to be sitting in reports/. This is what stops
    an old, superseded report (generated before a later privacy fix) from
    staying published forever just because GitHub/Cloudflare never delete
    old files on their own."""
    os.makedirs(os.path.join(PUBLIC_DIR, "reports"), exist_ok=True)
    wanted = set()
    for vendor_files in (snapshot.get("report_files") or {}).values():
        wanted.update(vendor_files.values())
    obj_files = snapshot.get("objectives_report_files") or {}
    for k in ("docx", "pdf"):
        if obj_files.get(k):
            wanted.add(obj_files[k])
    copied, missing = [], []
    for fname in sorted(wanted):
        src = os.path.join(BASE_DIR, "reports", fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(PUBLIC_DIR, "reports", fname))
            copied.append(fname)
        else:
            missing.append(fname)
    return copied, missing


def main():
    _clean(PUBLIC_DIR)

    shutil.copy2(os.path.join(BASE_DIR, "index.html"), os.path.join(PUBLIC_DIR, "index.html"))

    os.makedirs(os.path.join(PUBLIC_DIR, "web", "assets"), exist_ok=True)
    for fname in WEB_ASSET_FILES:
        shutil.copy2(
            os.path.join(BASE_DIR, "web", "assets", fname),
            os.path.join(PUBLIC_DIR, "web", "assets", fname),
        )

    os.makedirs(os.path.join(PUBLIC_DIR, "data"), exist_ok=True)
    snapshot_path = os.path.join(BASE_DIR, "data", "web_snapshot.json")
    shutil.copy2(snapshot_path, os.path.join(PUBLIC_DIR, "data", "web_snapshot.json"))
    with open(snapshot_path) as f:
        snapshot = json.load(f)

    copied, missing = stage_reports(snapshot)

    print(f"Staged {PUBLIC_DIR}")
    print(f"  index.html, web/assets/{{{', '.join(WEB_ASSET_FILES)}}}, data/web_snapshot.json")
    print(f"  reports/: {len(copied)} file(s) copied")
    if missing:
        print(f"  WARNING — referenced in web_snapshot.json but not found on disk: {missing}")


if __name__ == "__main__":
    main()
