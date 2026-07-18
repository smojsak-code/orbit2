"""
Migration idempotency tests (R1-T09 instruction #53).

scripts/migrations/migration_001_add_record_ids.py's apply(data_dir) takes a
plain directory path, which makes it directly testable against an isolated
tmp copy without needing to monkeypatch the migration runner's own module
constants at all.
"""
import csv
import json
import os

import pytest

from conftest import read_csv_rows


@pytest.fixture
def pre_migration_data_dir(tmp_path):
    """A tiny data/ directory shaped like it looked BEFORE migration 001 —
    category CSVs with no record_id column at all — so apply() has
    something real to backfill. Entirely fabricated content."""
    d = tmp_path / "data"
    d.mkdir()
    header = "vendor,quarter,sub_metric,weight_pct_in_category,target,actual,unit,score_method,source,notes,description"
    row = "TestVendor,2026-Q3,Fixture sub-metric,100,10,5,count,ratio,fixture,,Fixture row for migration test"
    for fname in ["sales_performance", "marketing"]:
        with open(d / f"{fname}.csv", "w") as f:
            f.write(header + "\n" + row + "\n")
    with open(d / "metric_changelog.csv", "w") as f:
        f.write("date,vendor,category,sub_metric,change_type,old_value,new_value,reason,source\n")
        f.write("2026-07-01,TestVendor,sales_performance,Fixture sub-metric,added,,5,fixture,fixture\n")
    with open(d / "solution_verticals.csv", "w") as f:
        f.write("vendor,quarter,vertical,solutions_count,solutions_sold,revenue,source,notes\n")
    with open(d / "news_log.csv", "w") as f:
        f.write("date_found,vendor_context,headline,source_url,sentiment,sentiment_confidence,summary\n")
    return str(d)


def test_migration_001_backfills_missing_record_ids(pre_migration_data_dir):
    import migration_001_add_record_ids as migration

    summary = migration.apply(pre_migration_data_dir)
    assert "record_id" in summary.lower() or "added" in summary.lower()

    rows = read_csv_rows(os.path.join(pre_migration_data_dir, "sales_performance.csv"))
    assert len(rows) == 1
    assert rows[0]["record_id"].startswith("MET-")

    changelog_rows = read_csv_rows(os.path.join(pre_migration_data_dir, "metric_changelog.csv"))
    assert changelog_rows[0]["record_id"].startswith("CHG-")


def test_migration_001_is_idempotent(pre_migration_data_dir):
    """Core acceptance requirement: running the migration twice must not
    reassign, duplicate, or renumber any record_id."""
    import migration_001_add_record_ids as migration

    migration.apply(pre_migration_data_dir)
    first_pass_ids = [
        r["record_id"] for r in read_csv_rows(os.path.join(pre_migration_data_dir, "sales_performance.csv"))
    ]

    second_summary = migration.apply(pre_migration_data_dir)
    second_pass_ids = [
        r["record_id"] for r in read_csv_rows(os.path.join(pre_migration_data_dir, "sales_performance.csv"))
    ]

    assert first_pass_ids == second_pass_ids, "record_ids changed on a second run — not idempotent"
    assert "no rows needed" in second_summary.lower() or "already backfilled" in second_summary.lower()


def test_migration_001_shared_namespace_never_collides_across_files(pre_migration_data_dir):
    """sales_performance.csv and marketing.csv share one MET- counter —
    prove the two fixture rows (one per file) get distinct IDs, not the
    same number reused independently per file."""
    import migration_001_add_record_ids as migration

    migration.apply(pre_migration_data_dir)
    sales_id = read_csv_rows(os.path.join(pre_migration_data_dir, "sales_performance.csv"))[0]["record_id"]
    marketing_id = read_csv_rows(os.path.join(pre_migration_data_dir, "marketing.csv"))[0]["record_id"]
    assert sales_id != marketing_id


def test_migration_001_intentional_failure_detects_missing_file_gracefully(tmp_path):
    """Intentional-failure case: apply() must not crash when a registered
    category file is simply absent (e.g. a partial/corrupted checkout) —
    proves the migration degrades gracefully rather than raising, which
    would otherwise abort scripts/migrations/run_migrations.py mid-way
    through and leave schema_version.json out of sync with the data."""
    import migration_001_add_record_ids as migration

    empty_data_dir = tmp_path / "data"
    empty_data_dir.mkdir()
    # No CSVs created at all.
    summary = migration.apply(str(empty_data_dir))
    assert isinstance(summary, str)  # did not raise


# ---------------------------------------------------------------------------
# Migration 002: metric_results_history.csv (R2-T01)
# ---------------------------------------------------------------------------
# Unlike migration 001's tests above, these need category CSVs that already
# HAVE record_ids (migration 002 keys migrated rows off the category CSV's
# own record_id via source_record_id) — tests/fixtures/data/ is already in
# that post-001 shape, so fixture_data_dir (from conftest.py) is reused
# directly rather than building another bespoke pre-migration directory.

def test_migration_002_creates_verification_levels_and_history_file(tmp_path):
    """Uses a bespoke minimal data dir (rather than fixture_data_dir) so it
    can start from a true pre-migration state — tests/fixtures/data/ itself
    keeps its own already-created header-only metric_results_history.csv
    and verification_levels.json checked in (same convention as
    objectives.csv being committed as a header-only fresh register)."""
    import migration_002_metric_results_history as migration

    d = tmp_path / "data"
    d.mkdir()
    with open(d / "app_config.json", "w") as f:
        json.dump({"user_display_name": "Nobody"}, f)
    for fname in migration.CATEGORY_FILES:
        with open(d / f"{fname}.csv", "w") as f:
            f.write("record_id,vendor,quarter,sub_metric,weight_pct_in_category,target,actual,unit,score_method,source,notes,description\n")

    assert not os.path.exists(d / "metric_results_history.csv")
    assert not os.path.exists(d / "verification_levels.json")
    summary = migration.apply(str(d))
    assert "created" in summary.lower()
    assert os.path.exists(d / "verification_levels.json")
    assert os.path.exists(d / "metric_results_history.csv")
    # Header-only is fine (no category rows in this bespoke dir) — the file
    # existing with the right columns is what's being proven here.
    assert read_csv_rows(str(d / "metric_results_history.csv")) == []


def test_migration_002_migrates_every_category_csv_row(fixture_data_dir):
    """tests/fixtures/data/sales_performance.csv has exactly one row
    (MET-0001) and every other category CSV is header-only — confirm
    exactly one history row comes out, correctly linked back to it."""
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    rows = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))
    assert len(rows) == 1
    r = rows[0]
    assert r["source_record_id"] == "MET-0001"
    assert r["vendor"] == "TestVendor"
    assert r["category"] == "sales_performance"
    assert r["period"] == "2026-Q3"
    assert r["result_version"] == "1"
    assert r["record_id"].startswith("RES-")


def test_migration_002_official_score_and_actual_attainment_computed_from_source(fixture_data_dir):
    """Fixture row is target=10, actual=6, ratio -> both figures are 60,
    computed (not copied) from the category CSV's own target/actual."""
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    row = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))[0]
    assert float(row["official_score"]) == 60.0
    assert float(row["actual_attainment"]) == 60.0


def test_migration_002_verification_level_evidence_backed_when_evidence_linked(fixture_data_dir):
    """tests/fixtures/data/evidence_index.csv links an active evidence item
    to exactly this (vendor, category, sub_metric, quarter) — the migrated
    row should come out evidence_backed, not the unverified default, and
    should carry the evidence_id in evidence_refs."""
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    row = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))[0]
    assert row["verification_level"] == "evidence_backed"
    assert row["evidence_refs"] == "EVD-0001"


def test_migration_002_freshness_date_from_changelog(fixture_data_dir):
    """tests/fixtures/data/metric_changelog.csv has a matching CHG-0001
    dated 2026-07-01 for this exact vendor/category — that date should
    become the migrated row's freshness_date rather than today's date."""
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    row = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))[0]
    assert row["freshness_date"] == "2026-07-01"


def test_migration_002_owner_defaults_from_fixture_app_config(fixture_data_dir):
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    row = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))[0]
    assert row["owner"] == "Test User", "must read the fixture's own app_config.json, never the real project's"


def test_migration_002_is_idempotent(fixture_data_dir):
    import migration_002_metric_results_history as migration

    migration.apply(fixture_data_dir)
    first_pass = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))

    second_summary = migration.apply(fixture_data_dir)
    second_pass = read_csv_rows(os.path.join(fixture_data_dir, "metric_results_history.csv"))

    assert first_pass == second_pass, "a second run must not duplicate or alter any history row"
    assert "no rows needed migrating" in second_summary.lower()


def test_migration_002_does_not_touch_category_csvs_or_scoring_inputs(fixture_data_dir):
    """Core R2-T01 acceptance criterion: 'existing current scores reproduce
    the pre-migration values' — confirm the migration never writes to the
    files scripts/scoring.py actually reads."""
    import migration_002_metric_results_history as migration

    before = read_csv_rows(os.path.join(fixture_data_dir, "sales_performance.csv"))
    before_mtime = os.path.getmtime(os.path.join(fixture_data_dir, "sales_performance.csv"))
    migration.apply(fixture_data_dir)
    after = read_csv_rows(os.path.join(fixture_data_dir, "sales_performance.csv"))
    after_mtime = os.path.getmtime(os.path.join(fixture_data_dir, "sales_performance.csv"))

    assert before == after
    assert before_mtime == after_mtime, "the category CSV file must not even be rewritten, not just unchanged in content"


def test_migration_002_intentional_failure_skips_rows_with_no_record_id(tmp_path):
    """Intentional-failure case: a category-CSV row with a blank record_id
    (e.g. a hand-edited or partially-migrated file) must be skipped rather
    than migrated with an empty source_record_id, which would make it
    indistinguishable from every other blank-sourced row on a later run and
    silently break the idempotency check."""
    import migration_002_metric_results_history as migration

    d = tmp_path / "data"
    d.mkdir()
    with open(d / "sales_performance.csv", "w") as f:
        f.write("record_id,vendor,quarter,sub_metric,weight_pct_in_category,target,actual,unit,score_method,source,notes,description\n")
        f.write(",TestVendor,2026-Q3,No id yet,100,10,5,count,ratio,fixture,,Row missing a record_id\n")
    for fname in ["marketing", "market_visibility", "ai_adoption", "business_planning_qbr",
                  "registrations", "third_party_coselling", "solutions", "services"]:
        with open(d / f"{fname}.csv", "w") as f:
            f.write("record_id,vendor,quarter,sub_metric,weight_pct_in_category,target,actual,unit,score_method,source,notes,description\n")

    summary = migration.apply(str(d))
    assert "migrated" not in summary.lower(), f"no row should have been reported as migrated: {summary}"
    rows = read_csv_rows(os.path.join(str(d), "metric_results_history.csv"))
    assert rows == [], "a row with no record_id must never be migrated"
