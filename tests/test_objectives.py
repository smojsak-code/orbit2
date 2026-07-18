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
