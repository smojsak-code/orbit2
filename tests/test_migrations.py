"""
Migration idempotency tests (R1-T09 instruction #53).

scripts/migrations/migration_001_add_record_ids.py's apply(data_dir) takes a
plain directory path, which makes it directly testable against an isolated
tmp copy without needing to monkeypatch the migration runner's own module
constants at all.
"""
import csv
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
