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
import actions as actions_mod  # scripts/actions.py — reuses its enums so validation never drifts from what the CLI accepts
import objectives as objectives_mod  # scripts/objectives.py — same reasoning, for data/objectives.csv (R1-T08)
import metric_results as metric_results_mod  # scripts/metric_results.py — same reasoning, for data/metric_results_history.csv (R2-T01)
import contacts as contacts_mod  # scripts/contacts.py — same reasoning, for the Contacts register (Phase 1 / R3-T01)

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
    return seen_ids


def validate_evidence_index(report, category_registry):
    path = os.path.join(DATA_DIR, "evidence_index.csv")
    label = "data/evidence_index.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, EVIDENCE_REQUIRED_COLUMNS)
    if fieldnames is None:
        return set()
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
    return seen_ids


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


VALID_VISIBILITY = {
    "personal_only", "communardo_internal", "communardo_management",
    "atlassian_shareable", "customer_approved", "anonymised", "public",
}
VALID_VALUE_STATUS = {"confirmed", "estimated", "protected", "potential"}
VALID_JOURNAL_STATUS = {"active", "archived"}
JOURNAL_REQUIRED_FIELDS = ["activity_id", "date", "type", "title", "outcome"]


def validate_journal(report, metric_ids, evidence_ids):
    path = os.path.join(DATA_DIR, "value_journal.jsonl")
    label = "data/value_journal.jsonl"
    if not os.path.exists(path):
        report.error(f"{label}: file is missing entirely")
        return set()

    activity_types_path = os.path.join(DATA_DIR, "activity_types.json")
    contribution_types_path = os.path.join(DATA_DIR, "contribution_types.json")
    activity_types = {}
    contribution_types = {}
    if os.path.exists(activity_types_path):
        with open(activity_types_path) as f:
            activity_types = json.load(f).get("types", {})
    if os.path.exists(contribution_types_path):
        with open(contribution_types_path) as f:
            contribution_types = json.load(f).get("types", {})

    seen_ids = set()
    with open(path) as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row_desc = f"line {i}"
            try:
                e = json.loads(line)
            except json.JSONDecodeError as err:
                report.error(f"{label}: {row_desc} is not valid JSON ({err})")
                continue

            for field in JOURNAL_REQUIRED_FIELDS:
                if not str(e.get(field, "")).strip():
                    report.error(f"{label}: {row_desc} is missing required field '{field}'")

            aid = (e.get("activity_id") or "").strip()
            if aid:
                if aid in seen_ids:
                    report.error(f"{label}: {row_desc} has duplicate activity_id '{aid}'")
                else:
                    seen_ids.add(aid)
                row_desc = f"{row_desc} ({aid})"

            check_date(report, label, e.get("date"), "date", row_desc)

            atype = (e.get("type") or "").strip()
            if atype and activity_types and atype not in activity_types:
                report.error(f"{label}: {row_desc} has type '{atype}' not in data/activity_types.json")

            ctype = (e.get("contribution_type") or "").strip()
            if ctype and contribution_types and ctype not in contribution_types:
                report.error(f"{label}: {row_desc} has contribution_type '{ctype}' not in data/contribution_types.json")

            visibility = (e.get("visibility") or "").strip()
            if visibility and visibility not in VALID_VISIBILITY:
                report.error(f"{label}: {row_desc} has an invalid visibility '{visibility}' (expected one of {sorted(VALID_VISIBILITY)})")

            status = (e.get("status") or "").strip()
            if status and status not in VALID_JOURNAL_STATUS:
                report.error(f"{label}: {row_desc} has an invalid status '{status}' (expected one of {sorted(VALID_JOURNAL_STATUS)})")

            # Confirmed (or any) financial value must carry a currency and a value status —
            # this is the acceptance criterion from R1-T03: never let a bare number imply
            # confirmed revenue without saying what it is and how sure we are.
            value = e.get("value") or {}
            amount = value.get("amount")
            if amount:
                if not value.get("currency"):
                    report.error(f"{label}: {row_desc} has value.amount {amount} but no value.currency")
                if not value.get("status"):
                    report.error(f"{label}: {row_desc} has value.amount {amount} but no value.status")
                elif value.get("status") not in VALID_VALUE_STATUS:
                    report.error(f"{label}: {row_desc} has an invalid value.status '{value.get('status')}' (expected one of {sorted(VALID_VALUE_STATUS)})")

            for mid in e.get("metric_links") or []:
                if mid not in metric_ids:
                    report.error(f"{label}: {row_desc} references unknown metric_links id '{mid}'")
            for eid in e.get("evidence_links") or []:
                if eid not in evidence_ids:
                    report.error(f"{label}: {row_desc} references unknown evidence_links id '{eid}'")
            # opportunity_links: no opportunities register exists yet (roadmap task R3-T03),
            # so there's nothing to check existence against — just note it's reserved.

    return seen_ids


ACTIONS_REQUIRED_COLUMNS = actions_mod.FIELDNAMES


def validate_actions(report, activity_ids, metric_ids):
    path = os.path.join(DATA_DIR, "actions.csv")
    label = "data/actions.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, ACTIONS_REQUIRED_COLUMNS)
    if fieldnames is None:
        return

    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        aid = (r.get("action_id") or "").strip()
        row_desc = f"row {i} ({aid or '?'})"
        if not aid:
            report.error(f"{label}: {row_desc} has no action_id")
        elif aid in seen_ids:
            report.error(f"{label}: duplicate action_id '{aid}'")
        else:
            seen_ids.add(aid)

        if not (r.get("description") or "").strip():
            report.error(f"{label}: {row_desc} is missing 'description'")

        status = (r.get("status") or "").strip()
        if status and status not in actions_mod.VALID_STATUS:
            report.error(f"{label}: {row_desc} has an invalid status '{status}' (expected one of {sorted(actions_mod.VALID_STATUS)})")

        priority = (r.get("priority") or "").strip()
        if priority and priority not in actions_mod.VALID_PRIORITY:
            report.error(f"{label}: {row_desc} has an invalid priority '{priority}' (expected one of {sorted(actions_mod.VALID_PRIORITY)})")

        visibility = (r.get("visibility") or "").strip()
        if visibility and visibility not in VALID_VISIBILITY:
            report.error(f"{label}: {row_desc} has an invalid visibility '{visibility}' (expected one of {sorted(VALID_VISIBILITY)})")

        evidence_required_raw = (r.get("evidence_required") or "").strip().lower()
        if evidence_required_raw and evidence_required_raw not in {"true", "false"}:
            report.error(f"{label}: {row_desc} has a non-boolean evidence_required value '{r.get('evidence_required')}' (expected 'true' or 'false')")

        for field in ("due_date", "original_due_date"):
            check_date(report, label, r.get(field), field, row_desc, required=False)
        for field in ("completed_at", "cancelled_at", "deferred_at", "created_at", "updated_at"):
            value = (r.get(field) or "").strip()
            if value and not DATE_RE.match(value[:10]):
                report.error(f"{label}: {row_desc} has a malformed '{field}' timestamp: {value!r}")

        source_activity = (r.get("source_activity") or "").strip()
        if source_activity and source_activity not in activity_ids:
            report.error(f"{label}: {row_desc} references unknown source_activity '{source_activity}' (not in data/value_journal.jsonl)")

        related_metric = (r.get("related_metric") or "").strip()
        if related_metric and related_metric not in metric_ids:
            report.error(f"{label}: {row_desc} references unknown related_metric '{related_metric}'")

        # Status-consistency checks — mirror what scripts/actions.py's own
        # commands enforce at write time, so a hand-edited or migrated row
        # that bypassed the CLI still gets caught.
        if status == "completed":
            if not (r.get("completed_at") or "").strip():
                report.error(f"{label}: {row_desc} has status 'completed' but no completed_at timestamp")
            if evidence_required_raw == "true" and not (r.get("completion_note") or r.get("completion_evidence") or "").strip():
                report.error(f"{label}: {row_desc} has evidence_required=true and status 'completed' but no completion_note or completion_evidence")
        if status == "cancelled":
            if not (r.get("cancelled_reason") or "").strip():
                report.error(f"{label}: {row_desc} has status 'cancelled' but no cancelled_reason")
            if not (r.get("cancelled_at") or "").strip():
                report.error(f"{label}: {row_desc} has status 'cancelled' but no cancelled_at timestamp")
        if status == "deferred":
            if not (r.get("deferred_at") or "").strip():
                report.error(f"{label}: {row_desc} has status 'deferred' but no deferred_at timestamp")
            if not (r.get("original_due_date") or "").strip():
                report.error(f"{label}: {row_desc} has status 'deferred' but no original_due_date on file")


OBJECTIVES_REQUIRED_COLUMNS = objectives_mod.FIELDNAMES


def validate_objectives(report, activity_ids, evidence_ids):
    path = os.path.join(DATA_DIR, "objectives.csv")
    label = "data/objectives.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, OBJECTIVES_REQUIRED_COLUMNS)
    if fieldnames is None:
        return

    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        oid = (r.get("objective_id") or "").strip()
        row_desc = f"row {i} ({oid or '?'})"
        if not oid:
            report.error(f"{label}: {row_desc} has no objective_id")
        elif oid in seen_ids:
            report.error(f"{label}: duplicate objective_id '{oid}'")
        else:
            seen_ids.add(oid)

        if not (r.get("objective") or "").strip():
            report.error(f"{label}: {row_desc} is missing 'objective'")

        period = (r.get("period") or "").strip()
        if not period:
            report.error(f"{label}: {row_desc} is missing 'period'")
        elif objectives_mod.period_type(period) is None:
            report.error(f"{label}: {row_desc} has a period '{period}' that is neither a quarter (YYYY-QN) nor a year (YYYY)")

        status = (r.get("status") or "").strip()
        if status and status not in objectives_mod.VALID_STATUS:
            report.error(f"{label}: {row_desc} has an invalid status '{status}' (expected one of {sorted(objectives_mod.VALID_STATUS)})")

        method = (r.get("progress_method") or "").strip()
        if method and method not in objectives_mod.VALID_PROGRESS_METHOD:
            report.error(f"{label}: {row_desc} has an invalid progress_method '{method}' (expected one of {sorted(objectives_mod.VALID_PROGRESS_METHOD)})")
        if method in ("count_linked", "sum_linked_value"):
            check_number(report, label, r.get("target"), "target", row_desc)

        for field in ("communardo_priority", "atlassian_priority"):
            value = (r.get(field) or "").strip()
            if value and value not in {"low", "medium", "high"}:
                report.error(f"{label}: {row_desc} has an invalid {field} '{value}' (expected one of low/medium/high, or blank)")

        visibility = (r.get("visibility") or "").strip()
        if visibility and visibility not in VALID_VISIBILITY:
            report.error(f"{label}: {row_desc} has an invalid visibility '{visibility}' (expected one of {sorted(VALID_VISIBILITY)})")

        check_date(report, label, r.get("target_date"), "target_date", row_desc, required=False)
        for field in ("completed_at", "missed_at", "created_at", "updated_at"):
            value = (r.get(field) or "").strip()
            if value and not DATE_RE.match(value[:10]):
                report.error(f"{label}: {row_desc} has a malformed '{field}' timestamp: {value!r}")

        for aid in objectives_mod.split_ids(r.get("linked_activities")):
            if aid not in activity_ids:
                report.error(f"{label}: {row_desc} references unknown linked_activities id '{aid}' (not in data/value_journal.jsonl)")
        for eid in objectives_mod.split_ids(r.get("linked_evidence")):
            if eid not in evidence_ids:
                report.error(f"{label}: {row_desc} references unknown linked_evidence id '{eid}'")

        # Status-consistency checks — mirror what scripts/objectives.py's own
        # commands enforce at write time, so a hand-edited row that bypassed
        # the CLI still gets caught (same discipline as validate_actions()).
        if status == "at_risk":
            if not (r.get("at_risk_reason") or "").strip():
                report.error(f"{label}: {row_desc} has status 'at_risk' but no at_risk_reason")
            if not (r.get("recovery_action") or "").strip():
                report.error(f"{label}: {row_desc} has status 'at_risk' but no recovery_action")
        if status == "completed" and not (r.get("completed_at") or "").strip():
            report.error(f"{label}: {row_desc} has status 'completed' but no completed_at timestamp")
        if status == "missed":
            if not (r.get("missed_at") or "").strip():
                report.error(f"{label}: {row_desc} has status 'missed' but no missed_at timestamp")
            if not (r.get("missed_reason") or "").strip():
                report.error(f"{label}: {row_desc} has status 'missed' but no missed_reason")


def validate_app_config(report):
    label = "data/app_config.json"
    config = app_config.load_config()
    for err in app_config.validate(config):
        report.error(f"{label}: {err}")


def validate_metric_results_history(report, category_registry, metric_ids, evidence_ids):
    """data/metric_results_history.csv (R2-T01). Beyond the usual required
    columns / unique record_id / referenced-id checks, this validator
    enforces the two acceptance criteria specific to this register:
      - "Duplicate period results are rejected or explicitly versioned" —
        two rows sharing (vendor, category, sub_metric, period,
        result_version) is an error; different result_version values for
        the same period are fine (that's the versioning escape hatch).
      - "Every calculated field can be regenerated from source fields" —
        official_score and actual_attainment are recomputed from each row's
        own target/actual/score_method and compared to the stored value;
        a mismatch means the row was hand-edited out of sync with its
        source fields (or a future writer skipped the compute step)."""
    path = os.path.join(DATA_DIR, "metric_results_history.csv")
    label = "data/metric_results_history.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, metric_results_mod.FIELDNAMES)
    if fieldnames is None:
        return

    valid_levels = metric_results_mod.valid_verification_levels()
    seen_ids = set()
    seen_version_keys = {}
    for i, r in enumerate(rows, start=2):
        rid = (r.get("record_id") or "").strip()
        row_desc = f"row {i} ({rid or '?'})"
        if not rid:
            report.error(f"{label}: {row_desc} has no record_id")
        elif rid in seen_ids:
            report.error(f"{label}: duplicate record_id '{rid}'")
        else:
            seen_ids.add(rid)

        vendor = (r.get("vendor") or "").strip()
        category = (r.get("category") or "").strip()
        sub_metric = (r.get("sub_metric") or "").strip()
        period = (r.get("period") or "").strip()
        if not vendor:
            report.error(f"{label}: {row_desc} is missing 'vendor'")
        if not category:
            report.error(f"{label}: {row_desc} is missing 'category'")
        elif category not in category_registry:
            report.error(f"{label}: {row_desc} references unknown category '{category}' (not in data/categories.json)")
        if not sub_metric:
            report.error(f"{label}: {row_desc} is missing 'sub_metric'")
        check_quarter(report, label, period, row_desc)

        check_number(report, label, r.get("target"), "target", row_desc)
        check_number(report, label, r.get("actual"), "actual", row_desc)
        method = (r.get("score_method") or "").strip()
        if method and method not in VALID_SCORE_METHODS:
            report.error(f"{label}: {row_desc} has an invalid score_method '{method}' (expected one of {sorted(VALID_SCORE_METHODS)})")

        version_raw = (r.get("result_version") or "").strip()
        version = None
        if not version_raw:
            report.error(f"{label}: {row_desc} is missing 'result_version'")
        else:
            try:
                version = int(version_raw)
                if version < 1:
                    report.error(f"{label}: {row_desc} has a non-positive result_version {version}")
            except ValueError:
                report.error(f"{label}: {row_desc} has a non-integer result_version {version_raw!r}")

        if vendor and category and sub_metric and period and version is not None:
            key = (vendor, category, sub_metric, period, version)
            if key in seen_version_keys:
                report.error(
                    f"{label}: {row_desc} duplicates {seen_version_keys[key]} — same vendor/category/sub_metric/"
                    f"period/result_version ({vendor}/{category}/{sub_metric}/{period} v{version}). "
                    f"Amendments to an existing period must increment result_version, not repeat it."
                )
            else:
                seen_version_keys[key] = row_desc

        # official_score / actual_attainment must always be regenerable from
        # target/actual/score_method — recompute and compare rather than
        # trusting the stored value.
        recomputed_official = metric_results_mod.official_score(r.get("target"), r.get("actual"), method)
        recomputed_attainment = metric_results_mod.actual_attainment(r.get("target"), r.get("actual"), method)
        for field, recomputed in (("official_score", recomputed_official), ("actual_attainment", recomputed_attainment)):
            stored_raw = (r.get(field) or "").strip()
            if not stored_raw:
                if recomputed is not None:
                    report.error(f"{label}: {row_desc} has no '{field}' but one could be computed from target/actual/score_method ({recomputed})")
                continue
            try:
                stored = float(stored_raw)
            except ValueError:
                report.error(f"{label}: {row_desc} has a non-numeric '{field}' value: {stored_raw!r}")
                continue
            if recomputed is None:
                report.error(f"{label}: {row_desc} has a '{field}' value ({stored}) but target/actual/score_method can't produce one — check for a zero target or unknown score_method")
            elif abs(stored - recomputed) > 0.05:
                report.error(f"{label}: {row_desc} has {field}={stored} but recomputing from target/actual/score_method gives {recomputed} — value has drifted from its source fields")

        verification_level = (r.get("verification_level") or "").strip()
        if verification_level and verification_level not in valid_levels:
            report.error(f"{label}: {row_desc} has an invalid verification_level '{verification_level}' (expected one of {sorted(valid_levels)})")

        for eid in metric_results_mod.split_ids(r.get("evidence_refs")):
            if eid not in evidence_ids:
                report.error(f"{label}: {row_desc} references unknown evidence_refs id '{eid}'")

        source_record_id = (r.get("source_record_id") or "").strip()
        if source_record_id and source_record_id not in metric_ids:
            report.error(f"{label}: {row_desc} references unknown source_record_id '{source_record_id}' (not in a category sub-metric CSV)")

        check_date(report, label, r.get("freshness_date"), "freshness_date", row_desc, required=False)
        check_date(report, label, r.get("recorded_date"), "recorded_date", row_desc, required=False)


def validate_contacts(report):
    """data/contacts.csv (Contacts Phase 1 / R3-T01). Returns the set of
    valid contact_ids for validate_contact_aliases()/validate_contact_evidence()
    to check references against."""
    path = os.path.join(DATA_DIR, "contacts.csv")
    label = "data/contacts.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, contacts_mod.FIELDNAMES)
    if fieldnames is None:
        return set()

    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        cid = (r.get("contact_id") or "").strip()
        row_desc = f"row {i} ({cid or '?'})"
        if not cid:
            report.error(f"{label}: {row_desc} has no contact_id")
        elif cid in seen_ids:
            report.error(f"{label}: duplicate contact_id '{cid}'")
        else:
            seen_ids.add(cid)

        if not (r.get("canonical_name") or "").strip():
            report.error(f"{label}: {row_desc} is missing 'canonical_name'")

        status = (r.get("status") or "").strip()
        if status and status not in contacts_mod.VALID_STATUS:
            report.error(f"{label}: {row_desc} has an invalid status '{status}' (expected one of {sorted(contacts_mod.VALID_STATUS)})")

        affiliation = (r.get("affiliation") or "").strip()
        if affiliation and affiliation not in contacts_mod.VALID_AFFILIATION:
            report.error(f"{label}: {row_desc} has an invalid affiliation '{affiliation}' (expected one of {sorted(contacts_mod.VALID_AFFILIATION)})")

        influence = (r.get("influence_level") or "").strip()
        if influence and influence not in contacts_mod.VALID_INFLUENCE:
            report.error(f"{label}: {row_desc} has an invalid influence_level '{influence}' (expected one of {sorted(contacts_mod.VALID_INFLUENCE)})")

        strength = (r.get("relationship_strength") or "").strip()
        if strength and strength not in contacts_mod.VALID_RELATIONSHIP_STRENGTH:
            report.error(f"{label}: {row_desc} has an invalid relationship_strength '{strength}' (expected one of {sorted(contacts_mod.VALID_RELATIONSHIP_STRENGTH)})")

        visibility = (r.get("visibility") or "").strip()
        if visibility and visibility not in VALID_VISIBILITY:
            report.error(f"{label}: {row_desc} has an invalid visibility '{visibility}' (expected one of {sorted(VALID_VISIBILITY)})")

        # Status-consistency: mirrors the discipline validate_actions()/
        # validate_objectives() already apply — a hand-edited row that
        # bypassed the CLI still gets caught.
        if status == "merged" and not (r.get("merged_into") or "").strip():
            report.error(f"{label}: {row_desc} has status 'merged' but no merged_into contact_id")

        for field in ("first_seen_at", "last_interaction_at", "summary_updated_at", "created_at", "updated_at"):
            value = (r.get(field) or "").strip()
            if value and not DATE_RE.match(value[:10]):
                report.error(f"{label}: {row_desc} has a malformed '{field}' timestamp: {value!r}")

    # Second pass: merged_into must point at a real (and ideally non-merged)
    # contact_id — checked after the full id set is known.
    for i, r in enumerate(rows, start=2):
        merged_into = (r.get("merged_into") or "").strip()
        if not merged_into:
            continue
        row_desc = f"row {i} ({r.get('contact_id', '?')})"
        if merged_into not in seen_ids:
            report.error(f"{label}: {row_desc} has merged_into '{merged_into}' which does not exist")
        elif merged_into == r.get("contact_id"):
            report.error(f"{label}: {row_desc} has merged_into pointing at itself")

    return seen_ids


def validate_contact_aliases(report, contact_ids):
    path = os.path.join(DATA_DIR, "contact_aliases.csv")
    label = "data/contact_aliases.csv"
    fieldnames, rows = read_csv(path)
    check_columns(report, label, fieldnames, contacts_mod.ALIAS_FIELDNAMES)
    if fieldnames is None:
        return

    seen_ids = set()
    for i, r in enumerate(rows, start=2):
        aid = (r.get("alias_id") or "").strip()
        row_desc = f"row {i} ({aid or '?'})"
        if not aid:
            report.error(f"{label}: {row_desc} has no alias_id")
        elif aid in seen_ids:
            report.error(f"{label}: duplicate alias_id '{aid}'")
        else:
            seen_ids.add(aid)

        cid = (r.get("contact_id") or "").strip()
        if not cid:
            report.error(f"{label}: {row_desc} is missing 'contact_id'")
        elif cid not in contact_ids:
            report.error(f"{label}: {row_desc} references unknown contact_id '{cid}'")

        if not (r.get("alias") or "").strip():
            report.error(f"{label}: {row_desc} is missing 'alias'")

        alias_type = (r.get("alias_type") or "").strip()
        if alias_type and alias_type not in contacts_mod.VALID_ALIAS_TYPE:
            report.error(f"{label}: {row_desc} has an invalid alias_type '{alias_type}' (expected one of {sorted(contacts_mod.VALID_ALIAS_TYPE)})")

        check_date(report, label, r.get("added_at"), "added_at", row_desc, required=False)


def validate_contact_evidence(report, contact_ids, activity_ids):
    path = os.path.join(DATA_DIR, "contact_evidence.jsonl")
    label = "data/contact_evidence.jsonl"
    if not os.path.exists(path):
        report.error(f"{label}: file is missing entirely")
        return

    evidence_fields = contacts_mod.load_evidence_fields()

    # Pre-scan once to collect every evidence_id in the file up front, so
    # superseded_by (which legitimately points from an older line to a
    # newer one further down the file) can be checked against the complete
    # set in a single pass below, instead of a forward-reference false
    # positive followed by a second corrective pass.
    all_ids = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            eid = (e.get("evidence_id") or "").strip()
            if eid:
                all_ids.add(eid)

    seen_ids = set()
    with open(path) as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row_desc = f"line {i}"
            try:
                e = json.loads(line)
            except json.JSONDecodeError as err:
                report.error(f"{label}: {row_desc} is not valid JSON ({err})")
                continue

            eid = (e.get("evidence_id") or "").strip()
            if eid:
                row_desc = f"{row_desc} ({eid})"
            if not eid:
                report.error(f"{label}: {row_desc} has no evidence_id")
            elif eid in seen_ids:
                report.error(f"{label}: {row_desc} has duplicate evidence_id '{eid}'")
            else:
                seen_ids.add(eid)

            cid = (e.get("contact_id") or "").strip()
            if not cid:
                report.error(f"{label}: {row_desc} is missing 'contact_id'")
            elif cid not in contact_ids:
                report.error(f"{label}: {row_desc} references unknown contact_id '{cid}'")

            field = (e.get("field") or "").strip()
            if not field:
                report.error(f"{label}: {row_desc} is missing 'field'")
            elif evidence_fields and field not in evidence_fields:
                report.warn(f"{label}: {row_desc} has field '{field}' not in data/contact_evidence_fields.json")

            if not str(e.get("value", "")).strip():
                report.error(f"{label}: {row_desc} is missing 'value'")

            source_type = (e.get("source_type") or "").strip()
            if source_type and source_type not in contacts_mod.VALID_SOURCE_TYPE:
                report.error(f"{label}: {row_desc} has an invalid source_type '{source_type}' (expected one of {sorted(contacts_mod.VALID_SOURCE_TYPE)})")

            confidence = (e.get("confidence") or "").strip()
            if confidence and confidence not in contacts_mod.VALID_CONFIDENCE:
                report.error(f"{label}: {row_desc} has an invalid confidence '{confidence}' (expected one of {sorted(contacts_mod.VALID_CONFIDENCE)})")

            sensitivity = (e.get("sensitivity") or "").strip()
            if sensitivity and sensitivity not in contacts_mod.VALID_SENSITIVITY:
                report.error(f"{label}: {row_desc} has an invalid sensitivity '{sensitivity}' (expected one of {sorted(contacts_mod.VALID_SENSITIVITY)})")

            reviewer_status = (e.get("reviewer_status") or "").strip()
            if reviewer_status and reviewer_status not in contacts_mod.VALID_REVIEWER_STATUS:
                report.error(f"{label}: {row_desc} has an invalid reviewer_status '{reviewer_status}' (expected one of {sorted(contacts_mod.VALID_REVIEWER_STATUS)})")

            superseded_by = (e.get("superseded_by") or "").strip()
            if superseded_by and superseded_by not in all_ids:
                report.error(f"{label}: {row_desc} has superseded_by '{superseded_by}' which does not exist anywhere in the file")

            check_date(report, label, e.get("extracted_at"), "extracted_at", row_desc, required=False)

            meeting_ref = (e.get("meeting_ref") or "").strip()
            if meeting_ref and activity_ids and meeting_ref not in activity_ids:
                report.warn(f"{label}: {row_desc} has meeting_ref '{meeting_ref}' not found in data/value_journal.jsonl")


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
    metric_ids = validate_category_files(report, categories) or set()
    evidence_ids = validate_evidence_index(report, categories) or set()
    validate_changelog(report)
    validate_app_config(report)
    activity_ids = validate_journal(report, set(metric_ids), evidence_ids) or set()
    validate_actions(report, activity_ids, set(metric_ids))
    validate_objectives(report, activity_ids, evidence_ids)
    validate_metric_results_history(report, categories, set(metric_ids), evidence_ids)
    contact_ids = validate_contacts(report) or set()
    validate_contact_aliases(report, contact_ids)
    validate_contact_evidence(report, contact_ids, activity_ids)

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
