"""
Migration 002: Introduce data/metric_results_history.csv (R2-T01).

Why: Release 2 requires metric records that support history, forecasts,
confidence and evidence coverage (roadmap R2-T01) without disturbing the
existing scorecard (roadmap instruction #62: "preserve existing category
and weight behaviour until enhanced scoring is accepted" in R2-T02). This
migration does not touch the 9 category CSVs, categories.json, or
weights.json at all — scripts/scoring.py's output is unaffected, which is
also the acceptance criterion "existing current scores reproduce the
pre-migration values."

What it does:
  1. Creates data/verification_levels.json if it doesn't already exist
     (controlled vocabulary for the new verification_level field).
  2. Creates data/metric_results_history.csv if it doesn't already exist
     (see scripts/metric_results.py for the full column list and design
     rationale).
  3. Migrates every row currently in the 9 category sub-metric CSVs into
     metric_results_history.csv as a result_version=1 row, computing
     official_score/actual_attainment from each row's own
     target/actual/score_method (scripts/metric_results.py's
     official_score()/actual_attainment(), which reuse scoring.py's own
     formula so the migrated numbers can never drift from what the
     scorecard already shows), looking up freshness_date from the most
     recent matching data/metric_changelog.csv entry, looking up
     evidence_refs from data/evidence_index.csv, and defaulting owner from
     data/app_config.json.

Idempotent: a category-CSV row is only migrated if no existing history row
already carries its record_id as source_record_id — running this (or the
whole runner) twice never creates duplicate history rows, even if new
category-CSV rows or new manually-entered history rows were added in
between runs.
"""
import csv
import json
import os
import sys

MIGRATION_ID = "002_metric_results_history"

CATEGORY_FILES = [
    "sales_performance", "marketing", "market_visibility", "ai_adoption",
    "business_planning_qbr", "registrations", "third_party_coselling",
    "solutions", "services",
]

DEFAULT_VERIFICATION_LEVELS = {
    "unverified": {
        "label": "Unverified",
        "description": "Entered with no supporting check — a placeholder, a rough estimate, or reset/default data. The default for any result that hasn't been reviewed.",
    },
    "self_reported": {
        "label": "Self-reported",
        "description": "Entered by the account owner from their own knowledge of the number, without a second source or attached evidence yet.",
    },
    "manager_reviewed": {
        "label": "Manager-reviewed",
        "description": "Reviewed and confirmed accurate by a manager or second person, but without a standalone evidence artifact on file.",
    },
    "evidence_backed": {
        "label": "Evidence-backed",
        "description": "At least one active item in the Evidence Library (data/evidence_index.csv) is linked to this specific vendor/category/sub_metric/period.",
    },
    "third_party_verified": {
        "label": "Third-party verified",
        "description": "Confirmed by an external source outside Communardo/Atlassian (e.g. a partner portal export, an auditable CRM report, a vendor-issued statement).",
    },
}


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def apply(data_dir):
    """Apply the migration. Returns a short human-readable summary string.
    Safe to call more than once."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    # Point the metric_results module at THIS data_dir (the migration
    # runner's DATA_DIR, or a test's tmp_path copy) rather than trusting
    # its own default path constants, so this migration is safe to run
    # against fixture data in tests too.
    import metric_results as mr

    mr.DATA_DIR = data_dir
    mr.HISTORY_PATH = os.path.join(data_dir, "metric_results_history.csv")
    mr.VERIFICATION_LEVELS_PATH = os.path.join(data_dir, "verification_levels.json")

    summary_parts = []

    verification_levels_path = os.path.join(data_dir, "verification_levels.json")
    if not os.path.exists(verification_levels_path):
        with open(verification_levels_path, "w") as f:
            json.dump(DEFAULT_VERIFICATION_LEVELS, f, indent=2)
        summary_parts.append("created data/verification_levels.json")

    history_existed = os.path.exists(mr.HISTORY_PATH)
    history_rows = mr.read_history()  # [] if the file doesn't exist yet
    if not history_existed:
        summary_parts.append("created data/metric_results_history.csv")

    already_migrated_source_ids = {
        r.get("source_record_id") for r in history_rows if r.get("source_record_id")
    }

    changelog_rows = _read_csv(os.path.join(data_dir, "metric_changelog.csv"))
    evidence_rows = _read_csv(os.path.join(data_dir, "evidence_index.csv"))

    # Read owner straight from THIS data_dir's app_config.json rather than
    # calling mr.default_owner() (which goes through scripts/config.py's
    # own hardcoded CONFIG_PATH, always the real production file) — this is
    # what actually makes apply() safe to run against a tmp_path fixture
    # copy in tests without ever touching the real app_config.json.
    owner = "Steve Mojsak"
    app_config_path = os.path.join(data_dir, "app_config.json")
    if os.path.exists(app_config_path):
        with open(app_config_path) as f:
            app_config = json.load(f)
        owner = app_config.get("user_display_name") or owner

    migrated_count = 0
    for fname in CATEGORY_FILES:
        rows = _read_csv(os.path.join(data_dir, f"{fname}.csv"))
        for r in rows:
            source_record_id = (r.get("record_id") or "").strip()
            if not source_record_id or source_record_id in already_migrated_source_ids:
                continue  # already migrated in a previous run, or has no id to key off of

            vendor = r.get("vendor", "")
            sub_metric = r.get("sub_metric", "")
            period = r.get("quarter", "")

            evidence_refs = mr.evidence_refs_for(vendor, fname, sub_metric, period, evidence_rows)
            verification_level = "evidence_backed" if evidence_refs else "unverified"
            freshness_date = mr.freshness_from_changelog(vendor, fname, changelog_rows)

            row = mr.build_result_row(
                vendor=vendor, category=fname, sub_metric=sub_metric, period=period,
                target=r.get("target", ""), actual=r.get("actual", ""),
                unit=r.get("unit", ""), score_method=r.get("score_method", "ratio"),
                source_record_id=source_record_id, result_version=1,
                verification_level=verification_level, evidence_refs=evidence_refs,
                freshness_date=freshness_date, owner=owner, source=r.get("source", ""),
                notes=r.get("notes", ""), recorded_by="migration_002",
                history_rows=history_rows,
            )
            history_rows.append(row)
            already_migrated_source_ids.add(source_record_id)
            migrated_count += 1

    if migrated_count or not history_existed:
        # Always write the file once it needs to exist — even a 0-row run
        # should leave a proper header-only CSV on disk (matching how every
        # other fresh Orbit2 register starts out), not just a promise in
        # the summary string that nothing then acts on.
        mr.write_history(history_rows)
    if migrated_count:
        summary_parts.append(f"migrated {migrated_count} category sub-metric row(s) into metric_results_history.csv")

    if not summary_parts:
        return "No rows needed migrating (already up to date)."
    return "; ".join(summary_parts) + "."
