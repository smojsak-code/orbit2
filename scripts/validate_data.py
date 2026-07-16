#!/usr/bin/env python3
"""
Orbit2 data validator.

Checks every register in data/ against the schema described in
docs/data_dictionary.md: required columns are present, record IDs are
present and unique, enum fields use a controlled vocabulary, referenced
categories exist, dates parse, quarters parse, and numeric fields parse as
numbers.

This script never modifies data — it only reports problems. Use
scripts/migrations/run_migrations.py to change the schema itself.

Usage:
    python3 scripts/validate_data.py
    python3 scripts/validate_data.py --check-only

--check-only is accepted explicitly for workflow/documentation compatibility
with the release process (see docs 'release governance': "run the full
validation suite before and after each task"). This script has no write mode
yet, so --check-only and the default behave identically today; the flag is
kept so future write-capable modes (e.g. an --fix mode) have a clearly
opt-in-required counterpart.

Exit code is 0 if no errors were found, 1 otherwise. Warnings never affect
the exit code.
"""
import argparse
import csv
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as app_config  # scripts/config.py — validates data/app_config.json

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")

CATEGORY_FILES = [
    "sales_performance", "marketing", "market_visibility", "ai_adoption",
    "business_planning_qbr", "registrations", "third_party_coselling",
    "solutions", "services",
]
CATEGORY_REQUIRED_COLUMNS = [
    "record_id", "vendor", "quarter", "sub_metric", "weight_pct_in_category",
    "target", "actual", "unit", "score_method", "source", "notes", "description",
]
VALID_SCORE_METHODS = {"ratio", "inverse"}

EVIDENCE_REQUIRED_COLUMNS = [
    "evidence_id", "date_added", "vendor", "category", "sub_metric", "quarter",
    "filename", "description", "dedupe_key", "status", "superseded_by",
    "source_type", "removed_date", "removed_reason",
]
VALID_EVIDENCE_STATUS = {"active", "superseded", "removed"}

CHANGELOG_REQUIRED_COLUMNS = [
    "record_id", "date", "vendor", "category", "sub_metric", "change_type",
    "old_value", "new_value", "reason", "source",
]
VALID_CHANGE_TYPES = {"added", "amended", "deprecated"}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def read_csv(path):
    if not os.path.exists(path):
        return None, []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def check_columns(report, label, fieldnames, required):
    if fieldnames is None:
        report.error(f"{label}: file is missing entirely")
        return
    missing = [c for c in required if c not in fieldnames]
    if missing:
        report.error(f"{label}: missing required column(s): {', '.join(missing)}")


def check_number(report, label, value, field, row_desc):
    if value is None or str(value).strip() == "":
        report.error(f"{label}: {row_desc} has an empty '{field}' value")
        return
    try:
        float(value)
    except ValueError:
        report.error(f"{label}: {row_desc} has a non-numeric '{field}' value: {value!r}")


def check_date(report, label, value, field, row_desc, required=True):
    value = (value or "").strip()
    if not value:
        if required:
            report.error(f"{label}: {row_desc} is missing '{field}'")
        return
    if not DATE_RE.match(value):
        report.error(f"{label}: {row_desc} has a malformed '{field}' date: {value!r} (expected YYYY-MM-DD)")


def check_quarter(report, label, value, row_desc):
    value = (value or "").strip()
    if not value:
        report.error(f"{label}: {row_desc} is missing 'quarter'")
        return
    if not QUARTER_RE.match(value):
        report.error(f"{label}: {row_desc} has a malformed quarter: {value!r} (expected YYYY-QN)")


def validate_category_files(report, category_registry):
    seen_ids = {}
    for fname in CATEGORY_FILES:
        path = os.path.join(DATA_DIR, f"{fname}.csv")
        label = f"data/{fname}.csv"
        fieldnames, rows = read_csv(path)
        check_columns(report, label, fieldnames, CATEGORY_REQUIRED_COLUMNS)
        if fieldnames is None:
            continue
        if fname not in category_registry:
            report.warn(f"{label}: file exists but has no entry in data/categories.json")
        for i, r in enumerate(rows, start=2):  # header is row 1
            row_desc = f"row {i} ({r.get('vendor', '?')}/{r.get('sub_metric', '?')}/{r.get('quarter', '?')})"
            rid = (r.get("record_id") or "").strip()
            if not rid:
                report.error(f"{label}: {row_desc} has no record_id")
            elif rid in seen_ids:
                report.error(f"{label}: duplicate record_id '{rid}' (also used at {seen_ids[rid]})")
            else:
                seen_ids[rid] = f"{label} {row_desc}"
            check_number(report, label, r.get("target"), "target", row_desc)
            check_number(report, label, r.get("actual"), "actual", row_desc)
            check_number(report, label, r.get("weight_pct_in_category"), "weight_pct_in_category", row_desc)
            check_quarter(report, label, r.get("quarter"), row_desc)
            method = (r.get("score_method") or "").strip()
            if method and method not in VALID_SCORE_METHODS:
                report.error(f"{label}: {row_desc} has an invalid score_method '{method}' (expected one of {sorted(VALID_SCORE_METHODS)})")
            if not (r.get("vendor") or "").strip():
                report.error(f"{label}: {row_desc} is missing 'vendor'")
            if not (r.get("sub_metric") or "").strip():
                report.error(f"{label}: {row_desc} is missing 'sub_metric'")


def validate_evidence_index(report, category_registry):
    path = os.path.join(DATA_DIR, "evidence_index.csv")
    label = "data/evidence_index.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, EVIDENCE_REQUIRED_COLUMNS)
    if fieldnames is None:
        return
    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        row_desc = f"row {i} ({r.get('evidence_id', '?')})"
        eid = (r.get("evidence_id") or "").strip()
        if not eid:
            report.error(f"{label}: {row_desc} has no evidence_id")
        elif eid in seen_ids:
            report.error(f"{label}: duplicate evidence_id '{eid}'")
        else:
            seen_ids.add(eid)
        status = (r.get("status") or "").strip()
        if status and status not in VALID_EVIDENCE_STATUS:
            report.error(f"{label}: {row_desc} has an invalid status '{status}' (expected one of {sorted(VALID_EVIDENCE_STATUS)})")
        check_date(report, label, r.get("date_added"), "date_added", row_desc)
        if status == "removed":
            check_date(report, label, r.get("removed_date"), "removed_date", row_desc)
        category = (r.get("category") or "").strip()
        if category and category not in category_registry:
            report.error(f"{label}: {row_desc} references unknown category '{category}' (not in data/categories.json)")


def validate_changelog(report):
    path = os.path.join(DATA_DIR, "metric_changelog.csv")
    label = "data/metric_changelog.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, CHANGELOG_REQUIRED_COLUMNS)
    if fieldnames is None:
        return
    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        row_desc = f"row {i}"
        rid = (r.get("record_id") or "").strip()
        if not rid:
            report.error(f"{label}: {row_desc} has no record_id")
        elif rid in seen_ids:
            report.error(f"{label}: duplicate record_id '{rid}'")
        else:
            seen_ids.add(rid)
        check_date(report, label, r.get("date"), "date", row_desc)
        change_type = (r.get("change_type") or "").strip()
        if change_type and change_type not in VALID_CHANGE_TYPES:
            report.warn(f"{label}: {row_desc} has an unrecognised change_type '{change_type}'")


def validate_weights_and_categories(report):
    cat_path = os.path.join(DATA_DIR, "categories.json")
    weights_path = os.path.join(DATA_DIR, "weights.json")
    if not os.path.exists(cat_path):
        report.error("data/categories.json: file is missing")
        return {}
    with open(cat_path) as f:
        categories = json.load(f)
    categories.pop("_comment", None)

    if not os.path.exists(weights_path):
        report.error("data/weights.json: file is missing")
        return categories
    with open(weights_path) as f:
        weights = json.load(f)
    weights.pop("_comment", None)

    for vendor, cat_weights in weights.items():
        total = sum(float(v) for v in cat_weights.values())
        if round(total, 1) != 100.0:
            report.error(f"data/weights.json: {vendor}'s category weights sum to {total}, not 100")
        for key in cat_weights:
            if key not in categories:
                report.error(f"data/weights.json: {vendor} has a weight for unknown category '{key}' (not in categories.json)")
    return categories


def validate_app_config(report):
    label = "data/app_config.json"
    config = app_config.load_config()
    for err in app_config.validate(config):
        report.error(f"{label}: {err}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--check-only", action="store_true",
        help="Validate only, report issues, change nothing (this script never writes data).",
    )
    args = ap.parse_args()
    _ = args.check_only  # no-op today; see module docstring

    report = Report()
    categories = validate_weights_and_categories(report)
    validate_category_files(report, categories)
    validate_evidence_index(report, categories)
    validate_changelog(report)
    validate_app_config(report)

    print(f"Orbit2 data validation — {len(report.errors)} error(s), {len(report.warnings)} warning(s)\n")
    if report.errors:
        print("ERRORS:")
        for e in report.errors:
            print(f"  [ERROR] {e}")
    if report.warnings:
        print("WARNINGS:")
        for w in report.warnings:
            print(f"  [WARN]  {w}")
    if not report.errors and not report.warnings:
        print("All checks passed.")

    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
