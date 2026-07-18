"""
scripts/metric_manager.py tests (new in R2-T01) — specifically the
add-submetric / amend-submetric integration with metric_results_history.csv
(scripts/metric_results.py). No tests existed for metric_manager.py before
R2-T01; this file is scoped to the new history-writing behaviour rather
than re-testing every pre-existing command, since that behaviour was
purely additive (see scripts/metric_manager.py's own module docstring).
"""
from types import SimpleNamespace

import metric_manager as metric_manager_mod
import metric_results as metric_results_mod


def _add_submetric_args(**overrides):
    defaults = dict(
        vendor="TestVendor", category="sales_performance", quarter="2026-Q4",
        sub_metric="Brand new metric", weight=25, target="100", actual="40",
        unit="count", score_method="ratio", source_field="fixture",
        notes="", description="", reason="test",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _amend_submetric_args(**overrides):
    defaults = dict(
        vendor="TestVendor", category="sales_performance", quarter="2026-Q4",
        sub_metric="Brand new metric", weight=None, target=None, actual=None,
        unit=None, notes=None, description=None, reason="test amend",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_add_submetric_appends_a_version_1_history_row(patched_metric_manager, patched_metric_results):
    metric_manager_mod.cmd_add_submetric(_add_submetric_args())

    rows = metric_results_mod.read_history()
    new_rows = [r for r in rows if r["sub_metric"] == "Brand new metric"]
    assert len(new_rows) == 1
    row = new_rows[0]
    assert row["result_version"] == "1"
    assert row["vendor"] == "TestVendor"
    assert row["period"] == "2026-Q4"
    assert float(row["official_score"]) == 40.0
    assert float(row["actual_attainment"]) == 40.0
    assert row["verification_level"] == "self_reported"
    assert row["source_record_id"], "must link back to the category CSV row's own MET- record_id"


def test_add_submetric_history_row_links_to_the_correct_category_csv_row(patched_metric_manager, patched_metric_results, fixture_data_dir):
    import os
    metric_manager_mod.cmd_add_submetric(_add_submetric_args())

    with open(os.path.join(fixture_data_dir, "sales_performance.csv"), newline="") as f:
        import csv
        category_rows = list(csv.DictReader(f))
    new_category_row = next(r for r in category_rows if r["sub_metric"] == "Brand new metric")

    history_row = next(r for r in metric_results_mod.read_history() if r["sub_metric"] == "Brand new metric")
    assert history_row["source_record_id"] == new_category_row["record_id"]


def test_amend_submetric_appends_version_2_without_touching_version_1(patched_metric_manager, patched_metric_results):
    metric_manager_mod.cmd_add_submetric(_add_submetric_args())
    metric_manager_mod.cmd_amend_submetric(_amend_submetric_args(actual="130"))

    rows = [r for r in metric_results_mod.read_history() if r["sub_metric"] == "Brand new metric"]
    assert len(rows) == 2
    v1 = next(r for r in rows if r["result_version"] == "1")
    v2 = next(r for r in rows if r["result_version"] == "2")
    assert float(v1["actual"]) == 40, "the first version must be untouched by the amendment"
    assert float(v2["actual"]) == 130
    assert float(v2["official_score"]) == 100.0, "official score caps at 100 even though actual exceeded target"
    assert float(v2["actual_attainment"]) == 130.0, "actual attainment must show the overachievement uncapped"
    assert v2["verification_level"] == "self_reported", "carries forward from version 1 since amend-submetric doesn't change verification state"


def test_amend_submetric_twice_produces_three_versions(patched_metric_manager, patched_metric_results):
    metric_manager_mod.cmd_add_submetric(_add_submetric_args())
    metric_manager_mod.cmd_amend_submetric(_amend_submetric_args(actual="60"))
    metric_manager_mod.cmd_amend_submetric(_amend_submetric_args(actual="80"))

    rows = [r for r in metric_results_mod.read_history() if r["sub_metric"] == "Brand new metric"]
    versions = sorted(int(r["result_version"]) for r in rows)
    assert versions == [1, 2, 3]


def test_add_submetric_does_not_write_history_when_submetric_already_exists(patched_metric_manager, patched_metric_results):
    """cmd_add_submetric() returns early (and prints a message instead of
    adding) when the sub-metric already exists for that vendor/quarter — the
    history append must not run in that case either."""
    metric_manager_mod.cmd_add_submetric(_add_submetric_args())
    before = len(metric_results_mod.read_history())

    metric_manager_mod.cmd_add_submetric(_add_submetric_args())  # duplicate call
    after = len(metric_results_mod.read_history())
    assert after == before, "a rejected duplicate add-submetric call must not append a history row"
