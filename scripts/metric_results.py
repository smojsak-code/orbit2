#!/usr/bin/env python3
"""
Orbit2 metric result history (R2-T01) — data/metric_results_history.csv.

Extends the existing category sub-metric CSVs (sales_performance.csv, etc.)
with a period-indexed, append-only result log that supports the fields
Release 2 needs: forecast, confidence, freshness, ownership, verification
level and evidence coverage — without changing how the 9 category CSVs
already work.

Why a separate file instead of adding columns to the 9 category CSVs:
scripts/scoring.py (R1) reads those CSVs directly and only the LATEST
quarter's row per vendor/category/sub_metric is scored — amending a row
in place is how "the current number" has always worked, and R1-T09's own
release gate depends on scoring.py's output staying byte-for-byte
reproducible until R2-T02 formally upgrades the scoring engine (see
roadmap instruction #62, "preserve existing category and weight behaviour
until enhanced scoring is accepted"). A separate, append-only history file
lets Release 2 add real historical tracking today without touching that
contract at all.

Each row in metric_results_history.csv is one *version* of one result for
one (vendor, category, sub_metric, period). Multiple periods for the same
metric coexist as separate rows (never overwritten). Amending the SAME
period's result (see scripts/metric_manager.py's amend-submetric, which
calls append_result_version() below) adds a new row with result_version
incremented rather than mutating the previous one — so "what did we think
the number was on date X" is always answerable later.

official_score and actual_attainment are never hand-entered — both are
always derived from target/actual/score_method (acceptance criterion:
"every calculated field can be regenerated from source fields"), reusing
scripts/scoring.py's own score_submetric() for official_score so the two
numbers can never drift apart:
  - official_score: scoring.py's existing capped figure (min 100), the
    "how much of this counted toward the scorecard" number.
  - actual_attainment: the SAME calculation with no cap — the "how much
    did we actually achieve, overachievement included" number. Mirrors the
    official_pct / overachievement_pct split scripts/objectives.py already
    established for R1-T08, for the same reason: overachievement should
    never be silently hidden by a capped figure.

confidence is defined as a field here (roadmap instruction #60) but is
deliberately left blank by everything in this module — R2-T02 ("Upgrade
the scoring and confidence engine") is what computes it, from freshness,
evidence coverage, completeness and verification_level together. Setting
it here would be inventing a number ahead of the engine that's supposed to
calculate it.
"""
import csv
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "metric_results_history.csv")
VERIFICATION_LEVELS_PATH = os.path.join(DATA_DIR, "verification_levels.json")

FIELDNAMES = [
    "record_id", "vendor", "category", "sub_metric", "period", "result_version",
    "source_record_id",
    "target", "actual", "unit", "score_method",
    "official_score", "actual_attainment", "forecast", "confidence",
    "freshness_date", "owner", "verification_level", "evidence_refs",
    "source", "notes",
    "recorded_date", "recorded_by",
]

RECORD_ID_PREFIX = "RES-"

DEFAULT_USER = "Steve Mojsak"
DEFAULT_VERIFICATION_LEVEL = "unverified"


def _app_config():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config as app_config
        return app_config.load_config()
    except Exception:
        return {}


def default_owner():
    return _app_config().get("user_display_name") or DEFAULT_USER


def today_iso():
    return date.today().isoformat()


def split_ids(value):
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def join_ids(values):
    return ";".join(values)


def load_verification_levels():
    """Reads data/verification_levels.json fresh every call (not cached at
    import time) so tests can monkeypatch VERIFICATION_LEVELS_PATH and so a
    hand-edit to the file takes effect without restarting anything — same
    pattern scripts/objectives.py uses for categories.json."""
    import json
    if not os.path.exists(VERIFICATION_LEVELS_PATH):
        return {}
    with open(VERIFICATION_LEVELS_PATH) as f:
        levels = json.load(f)
    levels.pop("_comment", None)
    return levels


def valid_verification_levels():
    levels = load_verification_levels()
    return set(levels.keys()) if levels else {
        "unverified", "self_reported", "manager_reviewed",
        "evidence_backed", "third_party_verified",
    }


def official_score(target, actual, method):
    """The existing R1 capped figure — delegates to scoring.py's own
    score_submetric() so this can never drift from what scripts/scoring.py
    actually scores. Returns None if target/actual aren't usable numbers or
    target is 0, matching scoring.py's own behaviour."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import scoring as scoring_mod
    return scoring_mod.score_submetric({
        "target": target, "actual": actual, "score_method": method,
    })


def actual_attainment(target, actual, method):
    """The new, uncapped figure — same underlying ratio as official_score
    but never clamped to 100, so overachievement is always visible instead
    of silently hidden behind the official capped number."""
    try:
        target_f = float(target)
        actual_f = float(actual)
    except (TypeError, ValueError):
        return None
    if target_f == 0:
        return None
    method = (method or "ratio").strip() or "ratio"
    if method == "inverse":
        # Mirrors scoring.py's inverse handling: actual == 0 is treated as a
        # perfect (100) result rather than a division by zero, since 0 is
        # the best possible value for a "lower is better" metric.
        return round((target_f / actual_f) * 100, 1) if actual_f else 100.0
    if method == "ratio":
        return round((actual_f / target_f) * 100, 1)
    return None


def read_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_history(rows):
    with open(HISTORY_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def next_record_id(rows=None):
    """RES- ids have their own single-file namespace (unlike the shared
    MET- namespace across the 9 category CSVs) since this file didn't exist
    before R2-T01 and every row lives in it."""
    if rows is None:
        rows = read_history()
    max_num = 0
    for r in rows:
        rid = (r.get("record_id") or "").strip()
        if rid.startswith(RECORD_ID_PREFIX):
            try:
                max_num = max(max_num, int(rid[len(RECORD_ID_PREFIX):]))
            except ValueError:
                pass
    return f"{RECORD_ID_PREFIX}{max_num + 1:04d}"


def latest_version_row(rows, vendor, category, sub_metric, period):
    """The highest-result_version row already on file for this exact
    (vendor, category, sub_metric, period), or None if this is the first
    time a result is being recorded for it."""
    matches = [
        r for r in rows
        if r.get("vendor") == vendor and r.get("category") == category
        and r.get("sub_metric") == sub_metric and r.get("period") == period
    ]
    if not matches:
        return None
    return max(matches, key=lambda r: int(r.get("result_version") or 0))


def evidence_refs_for(vendor, category, sub_metric, period, evidence_rows):
    """Semicolon-joined evidence_id list for active Evidence Library items
    linked to this exact (vendor, category, sub_metric, quarter) — matches
    scripts/evidence_ingest.py's own linking key. quarter is the
    evidence_index.csv column name for what this module calls 'period'."""
    ids = [
        r["evidence_id"] for r in evidence_rows
        if r.get("vendor") == vendor and r.get("category") == category
        and r.get("sub_metric") == sub_metric and r.get("quarter") == period
        and r.get("status") == "active"
    ]
    return join_ids(ids)


def freshness_from_changelog(vendor, category, changelog_rows):
    """Most recent metric_changelog.csv date touching this vendor/category
    (including category=='all' full-reset entries, which legitimately
    affect every category's freshness), or None if nothing matches. Used
    as the freshness_date default when a result is first recorded without
    an explicit date — a reasonable proxy for 'when was this last touched'
    when no finer-grained record exists yet."""
    dates = [
        r["date"] for r in changelog_rows
        if r.get("vendor") == vendor and r.get("category") in (category, "all")
        and (r.get("date") or "").strip()
    ]
    return max(dates) if dates else None


def build_result_row(*, vendor, category, sub_metric, period, target, actual,
                      unit, score_method, source_record_id="", result_version=1,
                      verification_level=DEFAULT_VERIFICATION_LEVEL, evidence_refs="",
                      freshness_date=None, owner=None, source="", notes="",
                      recorded_by="Claude", history_rows=None):
    """Construct one metric_results_history.csv row dict with official_score
    and actual_attainment always computed from target/actual/score_method —
    never accepted as caller-supplied values, so they can never drift from
    what scripts/scoring.py itself would compute."""
    rows = history_rows if history_rows is not None else read_history()
    return {
        "record_id": next_record_id(rows),
        "vendor": vendor,
        "category": category,
        "sub_metric": sub_metric,
        "period": period,
        "result_version": result_version,
        "source_record_id": source_record_id,
        "target": target,
        "actual": actual,
        "unit": unit,
        "score_method": score_method,
        "official_score": official_score(target, actual, score_method),
        "actual_attainment": actual_attainment(target, actual, score_method),
        "forecast": "",
        "confidence": "",
        "freshness_date": freshness_date or today_iso(),
        "owner": owner or default_owner(),
        "verification_level": verification_level,
        "evidence_refs": evidence_refs,
        "source": source,
        "notes": notes,
        "recorded_date": today_iso(),
        "recorded_by": recorded_by,
    }


def append_result_version(*, vendor, category, sub_metric, period, target, actual,
                           unit, score_method, source_record_id="", source="", notes="",
                           verification_level=None, evidence_refs=None, recorded_by="Claude"):
    """Append a new result row for (vendor, category, sub_metric, period).
    If a row already exists for that exact period, this is an amendment —
    the new row gets result_version = previous max + 1 and the previous
    row(s) are left untouched (append-only: 'duplicate period results are
    rejected or explicitly versioned'). verification_level/evidence_refs
    default to carrying forward from the most recent existing version if
    not given, since an amendment to target/actual doesn't necessarily mean
    the verification state changed. Returns the new row dict. Idempotent
    callers (like the migration) should check latest_version_row() /
    source_record_id themselves before calling this — this function always
    appends."""
    rows = read_history()
    previous = latest_version_row(rows, vendor, category, sub_metric, period)
    version = int(previous["result_version"]) + 1 if previous else 1
    if verification_level is None:
        verification_level = previous["verification_level"] if previous else DEFAULT_VERIFICATION_LEVEL
    if evidence_refs is None:
        evidence_refs = previous["evidence_refs"] if previous else ""
    row = build_result_row(
        vendor=vendor, category=category, sub_metric=sub_metric, period=period,
        target=target, actual=actual, unit=unit, score_method=score_method,
        source_record_id=source_record_id, result_version=version,
        verification_level=verification_level, evidence_refs=evidence_refs,
        source=source, notes=notes, recorded_by=recorded_by, history_rows=rows,
    )
    rows.append(row)
    write_history(rows)
    return row
