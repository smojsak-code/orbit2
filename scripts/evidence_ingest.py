#!/usr/bin/env python3
"""
Orbit2 Evidence Library ingest + dedupe helper.

Every piece of evidence (screenshot, CSV/Excel export, doc, article) that feeds
a metric gets one row in data/evidence_index.csv. When a NEW piece of evidence
is filed for the same vendor + category + sub_metric + quarter as an existing
ACTIVE entry, the old entry is marked "superseded" and the new one becomes
"active" — the scorecard always reflects the latest evidence, never a stale mix.

This script only manages the index + file location. Reading a screenshot or
spreadsheet and deciding *which* category/sub_metric/quarter it belongs to,
and what the extracted number is, is a judgment call Claude makes when you
hand it a file — this script is the bookkeeping step that runs after that.

Usage:
    python3 scripts/evidence_ingest.py file \
        --vendor Atlassian \
        --category sales_performance \
        --sub-metric "Bookings/revenue attainment vs quota" \
        --quarter 2026-Q3 \
        --file evidence_library/inbox/q3_finance_export.xlsx \
        --description "Q3 finance export, bookings vs quota" \
        --source-type spreadsheet

    python3 scripts/evidence_ingest.py search "marketplace"
    python3 scripts/evidence_ingest.py search "" --status active

Effect of `file`:
  - Moves the file from wherever it is into evidence_library/<category>/
    (prefixed with the new evidence_id to avoid name collisions).
  - Marks any existing ACTIVE row with the same dedupe key as "superseded".
  - Appends a new ACTIVE row to data/evidence_index.csv.

Effect of `search`:
  - Prints every evidence row (active or superseded) whose filename, category,
    sub-metric, quarter, status, description, source type, or vendor contains
    the query text — the same search the dashboard's Evidence Library box does.
"""
import argparse
import csv
import os
import shutil
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
EVIDENCE_DIR = os.path.join(BASE_DIR, "evidence_library")
INDEX_PATH = os.path.join(DATA_DIR, "evidence_index.csv")

FIELDS = ["evidence_id", "date_added", "vendor", "category", "sub_metric", "quarter",
          "filename", "description", "dedupe_key", "status", "superseded_by", "source_type"]


def read_index():
    if not os.path.exists(INDEX_PATH):
        return []
    with open(INDEX_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_index(rows):
    with open(INDEX_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def next_id(rows):
    nums = [int(r["evidence_id"].split("-")[1]) for r in rows if r["evidence_id"].startswith("EVD-")]
    n = (max(nums) + 1) if nums else 1
    return f"EVD-{n:04d}"


def cmd_file(args):
    rows = read_index()
    dedupe_key = f"{args.vendor}|{args.category}|{args.sub_metric}|{args.quarter}"
    new_id = next_id(rows)

    superseded_id = None
    for r in rows:
        if r["dedupe_key"] == dedupe_key and r["status"] == "active":
            r["status"] = "superseded"
            r["superseded_by"] = new_id
            superseded_id = r["evidence_id"]

    category_dir = os.path.join(EVIDENCE_DIR, args.category)
    os.makedirs(category_dir, exist_ok=True)
    src = args.file
    if not os.path.exists(src):
        print(f"ERROR: file not found: {src}", file=sys.stderr)
        sys.exit(1)
    filename = f"{new_id}_{os.path.basename(src)}"
    dest = os.path.join(category_dir, filename)
    shutil.move(src, dest) if os.path.dirname(os.path.abspath(src)) != os.path.abspath(category_dir) else None

    rows.append({
        "evidence_id": new_id,
        "date_added": date.today().isoformat(),
        "vendor": args.vendor,
        "category": args.category,
        "sub_metric": args.sub_metric,
        "quarter": args.quarter,
        "filename": filename,
        "description": args.description,
        "dedupe_key": dedupe_key,
        "status": "active",
        "superseded_by": "",
        "source_type": args.source_type,
    })
    write_index(rows)

    print(f"Filed {new_id} -> evidence_library/{args.category}/{filename}")
    if superseded_id:
        print(f"Superseded {superseded_id} (same vendor/category/sub-metric/quarter) — that evidence is now marked stale, not deleted.")
    print("Reminder: this only updates the evidence index. Update the actual value in "
          f"data/{args.category}.csv's 'actual' column yourself, then re-run scripts/scoring.py.")


def cmd_search(args):
    rows = read_index()
    q = (args.query or "").lower()
    matches = [r for r in rows if any(q in (r.get(f) or "").lower() for f in
               ("filename", "category", "sub_metric", "quarter", "status", "description", "source_type", "vendor"))]
    if args.status:
        matches = [r for r in matches if r["status"] == args.status]
    if not matches:
        print(f"No evidence matches '{args.query}'" + (f" (status={args.status})" if args.status else ""))
        return
    for r in sorted(matches, key=lambda r: r["date_added"], reverse=True):
        print(f"[{r['status']:>10}] {r['evidence_id']}  {r['date_added']}  {r['category']} / {r['sub_metric']}  "
              f"({r['quarter']})  {r['filename']}  — {r['description']}")
    print(f"\n{len(matches)} match(es).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("file", help="File a new piece of evidence (default action)")
    p.add_argument("--vendor", required=True)
    p.add_argument("--category", required=True, help="e.g. sales_performance, solutions, services, third_party_coselling ...")
    p.add_argument("--sub-metric", required=True, dest="sub_metric")
    p.add_argument("--quarter", required=True, help="e.g. 2026-Q3")
    p.add_argument("--file", required=True, dest="file", help="path to the evidence file (screenshot, spreadsheet, doc)")
    p.add_argument("--description", default="")
    p.add_argument("--source-type", default="document", dest="source_type", help="screenshot | spreadsheet | document | article | manual")
    p.set_defaults(func=cmd_file)

    p = sub.add_parser("search", help="Search past evidence (active + superseded)")
    p.add_argument("query", help="text to search for across filename/category/sub-metric/quarter/description/status")
    p.add_argument("--status", choices=["active", "superseded"], default=None, help="filter to only this status")
    p.set_defaults(func=cmd_search)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
