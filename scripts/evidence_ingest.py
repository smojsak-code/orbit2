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

    python3 scripts/evidence_ingest.py remove --evidence-id EVD-0003 --reason "Wrong file uploaded — was Q2 data mislabeled as Q3"

Effect of `file`:
  - Moves the file from wherever it is into evidence_library/<category>/
    (prefixed with the new evidence_id to avoid name collisions).
  - Marks any existing ACTIVE row with the same dedupe key as "superseded".
  - Appends a new ACTIVE row to data/evidence_index.csv.

Effect of `search`:
  - Prints every evidence row (active, superseded, or removed) whose filename,
    category, sub-metric, quarter, status, description, source type, or vendor
    contains the query text — the same search the dashboard's Evidence Library
    box does.

Effect of `remove`:
  - For evidence that turns out to be wrong (bad file, mis-typed number, wrong
    metric entirely) rather than just outdated. Marks the row "removed" with a
    reason and date — never deletes it, so there's still a record that it was
    filed and then retracted, and why.
  - If the removed evidence was the ACTIVE source for its metric, the
    corresponding row in data/<category>.csv has its actual value reset to 0
    (the pre-evidence value was never stored anywhere, so it can't be restored
    automatically — this flags the metric as needing correct data rather than
    guessing) and the correction is logged to data/metric_changelog.csv.
  - If it was already "superseded", removing it is just a record correction —
    it wasn't feeding the scorecard, so nothing else changes.
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
          "filename", "description", "dedupe_key", "status", "superseded_by", "source_type",
          "removed_date", "removed_reason"]


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


def cmd_remove(args):
    rows = read_index()
    target = next((r for r in rows if r["evidence_id"] == args.evidence_id), None)
    if target is None:
        print(f"ERROR: no evidence found with id {args.evidence_id}", file=sys.stderr)
        sys.exit(1)
    if target["status"] == "removed":
        print(f"{args.evidence_id} is already marked removed (on {target.get('removed_date') or 'unknown date'}). Nothing to do.")
        return

    was_active = target["status"] == "active"
    old_status = target["status"]
    target["status"] = "removed"
    target["removed_date"] = date.today().isoformat()
    target["removed_reason"] = args.reason
    write_index(rows)

    old_actual = None
    if was_active:
        category_csv = os.path.join(DATA_DIR, f"{target['category']}.csv")
        if os.path.exists(category_csv):
            with open(category_csv, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                cat_rows = list(reader)
            for cr in cat_rows:
                if (cr["vendor"] == target["vendor"] and cr["quarter"] == target["quarter"]
                        and cr["sub_metric"] == target["sub_metric"]):
                    old_actual = cr["actual"]
                    cr["actual"] = "0"
                    cr["notes"] = (f"RESET {date.today().isoformat()} — evidence {args.evidence_id} "
                                    f"removed ({args.reason}); awaiting correct data")
                    cr["source"] = ""
            with open(category_csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                for cr in cat_rows:
                    w.writerow(cr)

        changelog_path = os.path.join(DATA_DIR, "metric_changelog.csv")
        if os.path.exists(changelog_path):
            with open(changelog_path, newline="") as f:
                cl_fields = csv.DictReader(f).fieldnames
            with open(changelog_path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=cl_fields)
                w.writerow({
                    "date": date.today().isoformat(),
                    "vendor": target["vendor"],
                    "category": target["category"],
                    "sub_metric": target["sub_metric"],
                    "change_type": "amended",
                    "old_value": f"actual={old_actual}" if old_actual is not None else "",
                    "new_value": "actual=0 (reset)",
                    "reason": f"Evidence {args.evidence_id} removed as incorrect: {args.reason}",
                    "source": "evidence_ingest.py remove",
                })

    print(f"Marked {args.evidence_id} as removed (was {old_status}).")
    if was_active:
        print(f"That evidence was ACTIVE — reset data/{target['category']}.csv's "
              f"'{target['sub_metric']}' ({target['vendor']}, {target['quarter']}) actual to 0 "
              f"and logged the correction to metric_changelog.csv. Re-file correct evidence when available.")
    else:
        print("That evidence was not active (already superseded), so no metric value or changelog entry changed — "
              "this only corrects the evidence record itself.")
    print("Reminder: re-run scripts/scoring.py, then rebuild/push the dashboard.")


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

    p = sub.add_parser("search", help="Search past evidence (active + superseded + removed)")
    p.add_argument("query", help="text to search for across filename/category/sub-metric/quarter/description/status")
    p.add_argument("--status", choices=["active", "superseded", "removed"], default=None, help="filter to only this status")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("remove", help="Mark a piece of evidence as removed (incorrect, not just outdated)")
    p.add_argument("--evidence-id", required=True, dest="evidence_id", help="e.g. EVD-0003")
    p.add_argument("--reason", required=True, help="why this is being removed, e.g. 'wrong file uploaded'")
    p.set_defaults(func=cmd_remove)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
