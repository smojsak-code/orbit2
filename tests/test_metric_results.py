"""
scripts/metric_results.py tests (R2-T01).

official_score()/actual_attainment() are plain functions (no filesystem),
so most of this is filesystem-free. The versioning/id-assignment tests
exercise the real read/write functions against the isolated fixture
history file via patched_metric_results.
"""
import metric_results as metric_results_mod


def test_official_score_ratio_is_capped_at_100():
    assert metric_results_mod.official_score(100, 40, "ratio") == 40.0
    assert metric_results_mod.official_score(100, 150, "ratio") == 100.0, "official score must never exceed 100"


def test_actual_attainment_ratio_is_uncapped():
    assert metric_results_mod.actual_attainment(100, 40, "ratio") == 40.0
    assert metric_results_mod.actual_attainment(100, 150, "ratio") == 150.0, "overachievement must be visible, not capped"


def test_official_score_and_actual_attainment_agree_below_100():
    """Below 100% attainment, the capped and uncapped figures are identical
    — the cap only matters once you exceed target."""
    assert metric_results_mod.official_score(100, 40, "ratio") == metric_results_mod.actual_attainment(100, 40, "ratio")


def test_inverse_method_zero_actual_is_perfect_and_matches_scoring():
    """actual == 0 for an inverse ("lower is better") metric is a perfect
    result — mirrors scripts/scoring.py's own score_submetric() special
    case, not a division-by-zero error."""
    assert metric_results_mod.official_score(10, 0, "inverse") == 100.0
    assert metric_results_mod.actual_attainment(10, 0, "inverse") == 100.0


def test_inverse_method_overachievement_uncapped():
    # target=10, actual=2 -> ratio 500%; official caps at 100, attainment doesn't.
    assert metric_results_mod.official_score(10, 2, "inverse") == 100.0
    assert metric_results_mod.actual_attainment(10, 2, "inverse") == 500.0


def test_zero_target_returns_none_for_both():
    assert metric_results_mod.official_score(0, 5, "ratio") is None
    assert metric_results_mod.actual_attainment(0, 5, "ratio") is None


def test_non_numeric_target_or_actual_returns_none():
    assert metric_results_mod.actual_attainment("n/a", 5, "ratio") is None
    assert metric_results_mod.actual_attainment(5, "n/a", "ratio") is None


def test_split_and_join_ids_use_semicolons():
    assert metric_results_mod.split_ids("EVD-0001;EVD-0002") == ["EVD-0001", "EVD-0002"]
    assert metric_results_mod.split_ids("") == []
    assert metric_results_mod.join_ids(["EVD-0001", "EVD-0002"]) == "EVD-0001;EVD-0002"


def test_evidence_refs_for_matches_active_evidence_only():
    evidence_rows = [
        {"evidence_id": "EVD-0001", "vendor": "TestVendor", "category": "sales_performance",
         "sub_metric": "Fixture pipeline generated", "quarter": "2026-Q3", "status": "active"},
        {"evidence_id": "EVD-0002", "vendor": "TestVendor", "category": "sales_performance",
         "sub_metric": "Fixture pipeline generated", "quarter": "2026-Q3", "status": "removed"},
        {"evidence_id": "EVD-0003", "vendor": "TestVendor", "category": "marketing",
         "sub_metric": "Other metric", "quarter": "2026-Q3", "status": "active"},
    ]
    refs = metric_results_mod.evidence_refs_for("TestVendor", "sales_performance", "Fixture pipeline generated", "2026-Q3", evidence_rows)
    assert refs == "EVD-0001", "only the active, matching evidence item should be linked"


def test_freshness_from_changelog_matches_category_or_all():
    changelog_rows = [
        {"vendor": "TestVendor", "category": "sales_performance", "date": "2026-06-01"},
        {"vendor": "TestVendor", "category": "sales_performance", "date": "2026-07-01"},
        {"vendor": "TestVendor", "category": "all", "date": "2026-07-10"},
        {"vendor": "OtherVendor", "category": "sales_performance", "date": "2026-07-15"},
    ]
    # Most recent matching date wins, including the category=='all' wildcard row,
    # but not a different vendor's entry.
    assert metric_results_mod.freshness_from_changelog("TestVendor", "sales_performance", changelog_rows) == "2026-07-10"


def test_freshness_from_changelog_returns_none_when_no_match():
    assert metric_results_mod.freshness_from_changelog("TestVendor", "services", []) is None


def test_next_record_id_starts_at_0001_and_increments(patched_metric_results):
    assert metric_results_mod.next_record_id([]) == "RES-0001"
    assert metric_results_mod.next_record_id([{"record_id": "RES-0007"}]) == "RES-0008"


def test_build_result_row_always_computes_official_score_and_actual_attainment(patched_metric_results):
    row = metric_results_mod.build_result_row(
        vendor="TestVendor", category="sales_performance", sub_metric="Fixture pipeline generated",
        period="2026-Q3", target=10, actual=6, unit="count", score_method="ratio",
        history_rows=[],
    )
    assert row["record_id"] == "RES-0001"
    assert row["official_score"] == 60.0
    assert row["actual_attainment"] == 60.0
    assert row["forecast"] == "" and row["confidence"] == "", "confidence is defined but left for R2-T02's engine to compute, not invented here"
    assert row["owner"] == "Test User", "falls back to app_config.json's user_display_name via default_owner()"


def test_append_result_version_first_call_is_version_1(patched_metric_results):
    row = metric_results_mod.append_result_version(
        vendor="TestVendor", category="sales_performance", sub_metric="New metric",
        period="2026-Q3", target=100, actual=50, unit="count", score_method="ratio",
    )
    assert row["result_version"] == 1
    # read_history() round-trips through CSV, so every value comes back as a
    # string — compare the persisted row field-by-field against the
    # in-memory row's string form rather than asserting exact dict equality.
    # The fixture file already ships with one baseline row (RES-0001, for
    # "Fixture pipeline generated") so this new row must be found alongside
    # it, not alone.
    persisted = [r for r in metric_results_mod.read_history() if r["sub_metric"] == "New metric"]
    assert len(persisted) == 1
    assert persisted[0]["record_id"] == row["record_id"]
    assert persisted[0]["result_version"] == "1"
    assert float(persisted[0]["actual"]) == 50


def test_append_result_version_amendment_increments_without_overwriting(patched_metric_results):
    first = metric_results_mod.append_result_version(
        vendor="TestVendor", category="sales_performance", sub_metric="New metric",
        period="2026-Q3", target=100, actual=50, unit="count", score_method="ratio",
        verification_level="self_reported",
    )
    second = metric_results_mod.append_result_version(
        vendor="TestVendor", category="sales_performance", sub_metric="New metric",
        period="2026-Q3", target=100, actual=90, unit="count", score_method="ratio",
    )
    rows = [r for r in metric_results_mod.read_history() if r["sub_metric"] == "New metric"]
    assert len(rows) == 2, "amending must append a new row, never overwrite the previous one"
    assert first["result_version"] == 1
    assert second["result_version"] == 2
    assert second["actual"] == 90
    assert float(rows[0]["actual"]) == 50, "the version-1 row must be untouched"
    assert second["verification_level"] == "self_reported", "verification_level carries forward from the previous version when not given explicitly"


def test_append_result_version_different_periods_both_get_version_1(patched_metric_results):
    q3 = metric_results_mod.append_result_version(
        vendor="TestVendor", category="sales_performance", sub_metric="New metric",
        period="2026-Q3", target=100, actual=50, unit="count", score_method="ratio",
    )
    q4 = metric_results_mod.append_result_version(
        vendor="TestVendor", category="sales_performance", sub_metric="New metric",
        period="2026-Q4", target=100, actual=60, unit="count", score_method="ratio",
    )
    assert q3["result_version"] == 1
    assert q4["result_version"] == 1, "a different period is a new history, not a version bump of Q3's"
