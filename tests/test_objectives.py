"""
Objectives progress-computation tests (R1-T09, covering R1-T08's own logic
since it's part of Release 1's safety net too).

compute_progress() takes a plain row dict (+ optional journal_by_id map),
so most of these are filesystem-free. The at-risk workflow tests exercise
the real CLI commands against the isolated fixture register.
"""
from types import SimpleNamespace

import objectives as objectives_mod


def test_period_type_detects_quarter_and_year():
    assert objectives_mod.period_type("2026-Q3") == "quarter"
    assert objectives_mod.period_type("2026") == "year"
    assert objectives_mod.period_type("not-a-period") is None


def test_compute_progress_manual_uncapped_and_capped():
    row = {"progress_method": "manual", "progress_pct": "133"}
    p = objectives_mod.compute_progress(row)
    assert p["raw_pct"] == 133.0
    assert p["official_pct"] == 100.0, "official progress must never exceed 100"
    assert p["overachievement_pct"] == 33.0, "overachievement must be surfaced separately, not folded into official_pct"


def test_compute_progress_manual_at_zero_when_unset():
    row = {"progress_method": "manual", "progress_pct": ""}
    p = objectives_mod.compute_progress(row)
    assert p["official_pct"] == 0.0
    assert p["overachievement_pct"] == 0.0


def test_compute_progress_count_linked():
    row = {"progress_method": "count_linked", "target": "4", "linked_activities": "ACT-1;ACT-2"}
    p = objectives_mod.compute_progress(row)
    assert p["official_pct"] == 50.0
    assert p["overachievement_pct"] == 0.0


def test_compute_progress_count_linked_overachievement():
    row = {"progress_method": "count_linked", "target": "2", "linked_activities": "ACT-1;ACT-2;ACT-3"}
    p = objectives_mod.compute_progress(row)
    assert p["official_pct"] == 100.0
    assert p["overachievement_pct"] == 50.0


def test_compute_progress_sum_linked_value():
    row = {"progress_method": "sum_linked_value", "target": "1000", "linked_activities": "ACT-1;ACT-2"}
    journal_by_id = {
        "ACT-1": {"value": {"amount": 600, "currency": "GBP"}},
        "ACT-2": {"value": {"amount": 400, "currency": "GBP"}},
    }
    p = objectives_mod.compute_progress(row, journal_by_id)
    assert p["official_pct"] == 100.0
    assert p["overachievement_pct"] == 0.0
    assert "1,000" in p["basis"] or "1000" in p["basis"]


def test_compute_progress_sum_linked_value_ignores_missing_journal_entries():
    """A linked_activities id that doesn't resolve in journal_by_id (e.g.
    it was later archived out of the export, or is simply unknown) must
    not crash the calculation — it's just treated as contributing 0."""
    row = {"progress_method": "sum_linked_value", "target": "500", "linked_activities": "ACT-missing"}
    p = objectives_mod.compute_progress(row, {})
    assert p["official_pct"] == 0.0


def test_compute_progress_intentional_failure_zero_target_does_not_divide_by_zero():
    """Intentional-failure case: a target of 0 (or blank) must not raise a
    ZeroDivisionError — proves the guard actually exists rather than just
    happening not to trigger in the happy-path tests above."""
    row = {"progress_method": "count_linked", "target": "0", "linked_activities": "ACT-1"}
    p = objectives_mod.compute_progress(row)
    assert p["official_pct"] == 0.0


def test_split_and_join_ids_roundtrip():
    ids = ["ACT-0001", "ACT-0002"]
    joined = objectives_mod.join_ids(ids)
    assert objectives_mod.split_ids(joined) == ids
    assert objectives_mod.split_ids("") == []
    assert objectives_mod.split_ids("  ACT-0001 ; ACT-0002  ") == ["ACT-0001", "ACT-0002"]


def test_at_risk_requires_reason_and_recovery_action_via_cli(patched_objectives):
    args = SimpleNamespace(objective_id="OBJ-0001", reason="Fixture reason", recovery_action="Fixture recovery")
    patched_objectives.cmd_at_risk(args)
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["status"] == "at_risk"
    assert row["at_risk_reason"] == "Fixture reason"
    assert row["recovery_action"] == "Fixture recovery"


def test_resolve_risk_returns_to_on_track_and_keeps_audit_trail(patched_objectives):
    patched_objectives.cmd_at_risk(SimpleNamespace(
        objective_id="OBJ-0001", reason="Fixture reason", recovery_action="Fixture recovery",
    ))
    patched_objectives.cmd_resolve_risk(SimpleNamespace(objective_id="OBJ-0001"))
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["status"] == "on_track"
    assert row["at_risk_reason"] == "Fixture reason", "audit trail should be kept, not wiped, on resolve"


def test_complete_is_terminal_and_cannot_be_completed_twice(patched_objectives, capsys):
    patched_objectives.cmd_complete(SimpleNamespace(objective_id="OBJ-0001", completion_note="Fixture note"))
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["status"] == "completed"
    assert row["completed_at"]

    patched_objectives.cmd_complete(SimpleNamespace(objective_id="OBJ-0001", completion_note="Second attempt"))
    out = capsys.readouterr().out
    assert "already" in out.lower()
    row_after = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row_after["completion_note"] == "Fixture note", "second complete call must not overwrite the first"


def test_edit_rejects_terminal_status(patched_objectives, capsys):
    """Intentional-failure case: `edit --status completed` must be
    rejected — completing an objective is only allowed through the
    dedicated `complete` command so its required side effects (timestamp)
    always happen."""
    args = SimpleNamespace(
        objective_id="OBJ-0001", objective=None, period=None, success_measure=None,
        target=None, target_unit=None, target_date=None, communardo_priority=None,
        atlassian_priority=None, progress_method=None, linked_activities=None,
        linked_evidence=None, vendor=None, visibility=None, status="completed", notes=None,
    )
    patched_objectives.cmd_edit(args)
    out = capsys.readouterr().out
    assert "cannot set status" in out.lower()
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["status"] == "on_track", "status must be unchanged after a rejected edit"


# ---------------------------------------------------------------------------
# Category (relationship / commercial / strategic / operational / recognition)
# ---------------------------------------------------------------------------

def _create_args(**overrides):
    base = dict(
        objective="New objective", period="2026-Q3", category="operational",
        success_measure=None, target=None, target_unit=None, target_date=None,
        communardo_priority=None, atlassian_priority=None, progress_method="manual",
        progress_pct=0, linked_activities=None, linked_evidence=None,
        vendor=None, visibility=None, notes=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_create_requires_a_valid_category(patched_objectives, capsys):
    """Intentional-failure case: an invalid --category must refuse to
    create the objective rather than silently leaving it uncategorised."""
    import pytest
    with pytest.raises(SystemExit):
        patched_objectives.cmd_create(_create_args(category="not_a_real_category"))
    out = capsys.readouterr().out
    assert "category" in out.lower()


def test_create_with_valid_category_stores_it(patched_objectives):
    patched_objectives.cmd_create(_create_args(objective="Categorised objective", category="commercial"))
    rows = patched_objectives.read_objectives()
    new_row = next(r for r in rows if r["objective"] == "Categorised objective")
    assert new_row["category"] == "commercial"


def test_edit_can_recategorise_an_objective(patched_objectives):
    """OBJ-0001 in the fixture starts as 'operational'."""
    args = SimpleNamespace(
        objective_id="OBJ-0001", objective=None, period=None, category="strategic",
        success_measure=None, target=None, target_unit=None, target_date=None,
        communardo_priority=None, atlassian_priority=None, progress_method=None,
        linked_activities=None, linked_evidence=None, vendor=None, visibility=None,
        status=None, notes=None,
    )
    patched_objectives.cmd_edit(args)
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["category"] == "strategic"


def test_edit_rejects_invalid_category(patched_objectives, capsys):
    """Intentional-failure case: edit must reject an unrecognised category
    rather than writing it through."""
    args = SimpleNamespace(
        objective_id="OBJ-0001", objective=None, period=None, category="not_a_real_category",
        success_measure=None, target=None, target_unit=None, target_date=None,
        communardo_priority=None, atlassian_priority=None, progress_method=None,
        linked_activities=None, linked_evidence=None, vendor=None, visibility=None,
        status=None, notes=None,
    )
    patched_objectives.cmd_edit(args)
    out = capsys.readouterr().out
    assert "category" in out.lower()
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["category"] == "operational", "invalid category must not overwrite the existing value"


def test_edit_without_category_argument_leaves_it_unchanged(patched_objectives):
    """A caller (or an older script) that doesn't pass `category` at all
    (missing attribute, not just None) must not crash and must not touch
    the stored category — proves the getattr() fallback in cmd_edit."""
    args = SimpleNamespace(
        objective_id="OBJ-0001", objective="Renamed objective", period=None,
        success_measure=None, target=None, target_unit=None, target_date=None,
        communardo_priority=None, atlassian_priority=None, progress_method=None,
        linked_activities=None, linked_evidence=None, vendor=None, visibility=None,
        status=None, notes=None,
    )
    assert not hasattr(args, "category")
    patched_objectives.cmd_edit(args)
    row = {r["objective_id"]: r for r in patched_objectives.read_objectives()}["OBJ-0001"]
    assert row["category"] == "operational"
    assert row["objective"] == "Renamed objective"


# ---------------------------------------------------------------------------
# compute_objective_detail() — full breakdown for the click-through detail
# view (My Impact tab + Cowork dashboard Objectives tab), 2026-07-21.
# ---------------------------------------------------------------------------

def _detail_row(**overrides):
    base = dict(
        objective_id="OBJ-9001", objective="Test objective", category="commercial",
        period="2026-Q3", status="on_track", success_measure="Some measure",
        target="4", target_unit="count", target_date="2026-09-30",
        communardo_priority="high", atlassian_priority="medium",
        progress_method="count_linked", progress_pct="",
        linked_activities="ACT-0001", linked_evidence="EVD-0001",
        at_risk_reason="", recovery_action="", completed_at="", completion_note="",
        missed_at="", missed_reason="", vendor="Atlassian", visibility="communardo_internal",
        created_at="2026-07-01T09:00:00", updated_at="2026-07-01T09:00:00", notes="",
    )
    base.update(overrides)
    return base


def test_compute_objective_detail_includes_full_evidence_and_activity_details():
    row = _detail_row()
    journal_by_id = {"ACT-0001": {
        "activity_id": "ACT-0001", "date": "2026-07-10", "type": "meeting",
        "title": "QBR with Atlassian", "outcome": "Agreed next steps",
        "next_action": "Send follow-up deck", "organisation": "Atlassian",
        "contribution_type": "commercial", "value": {"amount": 1000, "currency": "GBP"},
        "participants": "Jamie Chen", "visibility": "communardo_internal",
    }}
    evidence_by_id = {"EVD-0001": {
        "evidence_id": "EVD-0001", "date_added": "2026-07-11", "category": "sales_performance",
        "sub_metric": "Bookings", "quarter": "2026-Q3", "filename": "q3_export.xlsx",
        "description": "Q3 bookings export", "status": "active", "source_type": "spreadsheet",
    }}
    detail = objectives_mod.compute_objective_detail(row, journal_by_id, evidence_by_id)

    assert len(detail["linked_evidence"]) == 1
    ev = detail["linked_evidence"][0]
    assert ev["found"] is True
    assert ev["filename"] == "q3_export.xlsx"
    assert ev["description"] == "Q3 bookings export"

    assert len(detail["linked_activities"]) == 1
    act = detail["linked_activities"][0]
    assert act["found"] is True
    assert act["title"] == "QBR with Atlassian"
    assert act["next_action"] == "Send follow-up deck"


def test_compute_objective_detail_handles_dangling_reference_without_crashing():
    """Intentional-failure case: a linked_evidence/linked_activities id that
    doesn't resolve (e.g. later archived out of an export) must not crash
    the detail assembly — it's surfaced as found=False, not silently
    dropped or fatal."""
    row = _detail_row(linked_evidence="EVD-9999", linked_activities="ACT-9999")
    detail = objectives_mod.compute_objective_detail(row, {}, {})
    assert detail["linked_evidence"] == [{"evidence_id": "EVD-9999", "found": False}]
    assert detail["linked_activities"] == [{"activity_id": "ACT-9999", "found": False}]


def test_compute_objective_detail_summary_mentions_category_and_progress():
    row = _detail_row(linked_activities="ACT-0001;ACT-0002;ACT-0003;ACT-0004", linked_evidence="")
    detail = objectives_mod.compute_objective_detail(row, {}, {})
    assert "Commercial" in detail["summary_text"]
    assert "100.0%" in detail["summary_text"] or "100%" in detail["summary_text"]
    assert detail["category_label"] == "Commercial"


def test_compute_objective_detail_summary_notes_no_evidence_when_none_linked():
    row = _detail_row(linked_activities="", linked_evidence="")
    detail = objectives_mod.compute_objective_detail(row, {}, {})
    assert "No evidence or linked activities recorded yet." in detail["summary_text"]


def test_compute_objective_detail_action_points_include_at_risk_reason_and_recovery():
    row = _detail_row(status="at_risk", at_risk_reason="Slipping behind", recovery_action="Escalate to VP")
    detail = objectives_mod.compute_objective_detail(row, {}, {})
    texts = [a["text"] for a in detail["action_points"]]
    assert "Slipping behind" in texts
    assert "Escalate to VP" in texts


def test_compute_objective_detail_action_points_include_linked_activity_next_action():
    row = _detail_row(linked_evidence="")
    journal_by_id = {"ACT-0001": {
        "activity_id": "ACT-0001", "date": "2026-07-10", "next_action": "Send follow-up deck",
    }}
    detail = objectives_mod.compute_objective_detail(row, journal_by_id, {})
    action_texts = [a["text"] for a in detail["action_points"]]
    assert "Send follow-up deck" in action_texts
    source = next(a["source"] for a in detail["action_points"] if a["text"] == "Send follow-up deck")
    assert "ACT-0001" in source


def test_compute_objective_detail_uses_passed_generated_at():
    row = _detail_row()
    detail = objectives_mod.compute_objective_detail(row, {}, {}, generated_at="2026-07-21T18:00:00")
    assert detail["generated_at"] == "2026-07-21T18:00:00"
