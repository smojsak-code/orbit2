"""
Tests for scripts/scoring.py's has_data signal (Improvement Roadmap IR-B1,
2026-07-22) — the missing-vs-zero distinction that stops an unmeasured
sub-metric (actual=0, no evidence) from displaying identically to a
genuinely-measured zero.

submetric_has_data() is a pure function (plain dict/set args, no file I/O),
so most of these tests exercise it directly with synthetic rows — no
fixture data or DATA_DIR patching needed. A smaller integration test at the
bottom confirms score_category()/score_vendor() actually wire has_data
through end-to-end using the real fixture data (patched_scoring).
"""
import scoring as scoring_mod


# --- submetric_has_data(): pure unit tests -------------------------------

def test_has_data_true_for_nonzero_actual_no_evidence():
    row = {"actual": "6", "sub_metric": "Deals closed"}
    assert scoring_mod.submetric_has_data(row, "sales_performance", set()) is True


def test_has_data_false_for_zero_actual_no_evidence():
    row = {"actual": "0", "sub_metric": "Deals closed"}
    assert scoring_mod.submetric_has_data(row, "sales_performance", set()) is False


def test_has_data_false_for_blank_actual_no_evidence():
    row = {"actual": "", "sub_metric": "Deals closed"}
    assert scoring_mod.submetric_has_data(row, "sales_performance", set()) is False


def test_has_data_true_for_zero_actual_with_matching_active_evidence():
    row = {"actual": "0", "sub_metric": "Deals closed"}
    active_pairs = {("sales_performance", "Deals closed")}
    assert scoring_mod.submetric_has_data(row, "sales_performance", active_pairs) is True


def test_has_data_false_for_zero_actual_with_non_matching_evidence():
    """Evidence exists, but for a different sub_metric — must not false-positive."""
    row = {"actual": "0", "sub_metric": "Deals closed"}
    active_pairs = {("sales_performance", "Renewal rate")}
    assert scoring_mod.submetric_has_data(row, "sales_performance", active_pairs) is False


def test_has_data_false_for_zero_actual_with_evidence_in_different_category():
    """Same sub_metric name, but evidence filed against a different category
    — active_pairs is scoped per-category, so this must not match either."""
    row = {"actual": "0", "sub_metric": "Deals closed"}
    active_pairs = {("market_visibility", "Deals closed")}
    assert scoring_mod.submetric_has_data(row, "sales_performance", active_pairs) is False


def test_has_data_nonzero_actual_wins_even_without_evidence():
    """A real measured non-zero actual is sufficient on its own — evidence
    is only needed to justify a zero, never required to justify a non-zero."""
    row = {"actual": "3.5", "sub_metric": "Renewal rate"}
    assert scoring_mod.submetric_has_data(row, "sales_performance", set()) is True


def test_has_data_handles_non_numeric_actual_gracefully():
    """Malformed/non-numeric actual should not raise — treated as 0 (no data)
    unless evidence backs it."""
    row = {"actual": "n/a", "sub_metric": "Deals closed"}
    assert scoring_mod.submetric_has_data(row, "sales_performance", set()) is False
    active_pairs = {("sales_performance", "Deals closed")}
    assert scoring_mod.submetric_has_data(row, "sales_performance", active_pairs) is True


# --- score_category()/score_vendor(): has_data wiring, using real fixture data ---

def test_score_category_propagates_has_data_per_submetric_and_aggregate(patched_scoring):
    result = scoring_mod.score_category("sales_performance", "TestVendor", "sales_performance", evidence_rows=[])
    assert result["sub_metrics"], "fixture sales_performance.csv should have at least one row"
    for sm in result["sub_metrics"]:
        assert "has_data" in sm
    # Fixture row has actual=6 (non-zero) -> has_data True via the actual!=0
    # path alone, independent of evidence.
    assert result["sub_metrics"][0]["has_data"] is True
    assert result["has_data"] is True


def test_score_category_has_data_uses_active_evidence_from_index(patched_scoring):
    """The fixture's evidence_index.csv has one ACTIVE row for exactly
    TestVendor/sales_performance/'Fixture sub-metric for tests only'/2026-Q3
    — pass it through and confirm it's consulted (even though this
    particular fixture row's actual is already non-zero, so has_data would
    be True either way; this checks the evidence plumbing doesn't error and
    active_pairs gets built from real evidence_index.csv rows)."""
    evidence_rows = scoring_mod.read_evidence_index()
    result = scoring_mod.score_category("sales_performance", "TestVendor", "sales_performance", evidence_rows=evidence_rows)
    assert result["has_data"] is True


def test_score_vendor_passes_evidence_rows_through_to_categories(patched_scoring):
    categories = scoring_mod.load_categories()
    weights = scoring_mod.load_weights()
    weights.pop("_comment", None)
    evidence_rows = scoring_mod.read_evidence_index()
    result = scoring_mod.score_vendor("TestVendor", weights.get("TestVendor", {}), categories, evidence_rows)
    for cat in result["categories"].values():
        assert "has_data" in cat
