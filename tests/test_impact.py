"""
My Impact aggregation tests (R1-T09 instruction #53).

scripts/impact.py's compute_impact_aggregates() takes a plain list of
journal-entry dicts and returns a pure data structure — no filesystem
dependency at all, so these tests construct fabricated entries directly
rather than needing the fixture data/ directory.
"""
import impact as impact_mod


def make_entry(**overrides):
    base = dict(
        activity_id="ACT-9001", date="2026-07-10", type="qbr", title="Fixture entry",
        status="active", visibility="communardo_internal", organisation="Fixture Corp",
        contribution_type="led", participants=[], value={}, recognition_status="unrecognised",
        confidence="verified", evidence_links=[],
    )
    base.update(overrides)
    return base


def test_impact_category_partition_sums_to_total(fixed_today):
    entries = [
        make_entry(activity_id="ACT-1", type="qbr"),               # relationship
        make_entry(activity_id="ACT-2", type="deal_support"),      # commercial
        make_entry(activity_id="ACT-3", type="campaign"),          # strategic
        make_entry(activity_id="ACT-4", type="enablement"),        # operational
        make_entry(activity_id="ACT-5", type="totally_unknown_type"),  # falls back to operational
    ]
    agg = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]
    assert agg["total_contributions"] == 5
    category_sum = sum(agg["categories"][c]["count"] for c in impact_mod.IMPACT_CATEGORIES)
    assert category_sum == agg["total_contributions"], "categories must partition the total exactly, no double-count or gap"
    assert agg["categories"]["relationship"]["count"] == 1
    assert agg["categories"]["commercial"]["count"] == 1
    assert agg["categories"]["strategic"]["count"] == 1
    assert agg["categories"]["operational"]["count"] == 2  # enablement + unknown-type fallback


def test_personal_only_entries_are_excluded(fixed_today):
    """Intentional-failure case: proves the personal_only filter actually
    removes entries rather than being a no-op — construct one visible and
    one personal_only entry and assert only the visible one is counted."""
    entries = [
        make_entry(activity_id="ACT-1", visibility="communardo_internal"),
        make_entry(activity_id="ACT-2", visibility="personal_only"),
    ]
    agg = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]
    assert agg["total_contributions"] == 1


def test_archived_entries_are_excluded(fixed_today):
    entries = [
        make_entry(activity_id="ACT-1", status="active"),
        make_entry(activity_id="ACT-2", status="archived"),
    ]
    agg = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]
    assert agg["total_contributions"] == 1


def test_financial_totals_never_combined_across_status_or_currency(fixed_today):
    entries = [
        make_entry(activity_id="ACT-1", value={"amount": 1000, "currency": "GBP", "status": "confirmed"}),
        make_entry(activity_id="ACT-2", value={"amount": 500, "currency": "USD", "status": "confirmed"}),
        make_entry(activity_id="ACT-3", value={"amount": 200, "currency": "GBP", "status": "estimated"}),
    ]
    fin = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]["financial"]
    assert fin["by_status"]["confirmed"] == {"GBP": 1000, "USD": 500}
    assert fin["by_status"]["estimated"] == {"GBP": 200}
    assert "protected" not in fin["by_status"] or fin["by_status"]["protected"] == {}
    # Nothing should have been summed across currency or status into one number.
    assert 1500 not in fin["by_status"]["confirmed"].values()


def test_awaiting_validation_is_driven_by_confidence_not_value_status(fixed_today):
    entries = [
        make_entry(activity_id="ACT-1", value={"amount": 300, "currency": "GBP", "status": "confirmed"}, confidence="unverified"),
        make_entry(activity_id="ACT-2", value={"amount": 100, "currency": "GBP", "status": "estimated"}, confidence="verified"),
    ]
    fin = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]["financial"]
    assert fin["awaiting_validation"] == {"GBP": 300}
    assert fin["awaiting_validation_count"] == 1


def test_narrative_joint_contribution_never_implies_sole_ownership(fixed_today):
    entries = [
        make_entry(activity_id="ACT-1", contribution_type="supported", participants=["Fixture Colleague"]),
    ]
    agg = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]
    assert "drove" not in agg["narrative"].lower()
    assert "contributed to" in agg["narrative"].lower()
    assert "other people were involved" in agg["narrative"]


def test_narrative_sole_ownership_language_for_led(fixed_today):
    entries = [make_entry(activity_id="ACT-1", contribution_type="led", participants=[])]
    agg = impact_mod.compute_impact_aggregates(entries)["by_period"]["year"]
    assert "drove" in agg["narrative"].lower()


def test_empty_period_narrative_is_encouraging_not_blank(fixed_today):
    agg = impact_mod.compute_impact_aggregates([])["by_period"]["year"]
    assert agg["total_contributions"] == 0
    assert "Add Activity" in agg["narrative"]
