"""
Actions & commitments date-logic tests (R1-T09 instruction #53).

is_overdue()/is_due_soon()/period_start() all accept an explicit `today`
override, so these can be tested deterministically without depending on the
sandbox's real clock or timezone.
"""
from datetime import date


def test_is_overdue_true_for_past_due_open_action():
    import actions as actions_mod
    row = {"status": "open", "due_date": "2026-01-01"}
    assert actions_mod.is_overdue(row, today=date(2026, 7, 18)) is True


def test_is_overdue_false_for_future_due_date():
    import actions as actions_mod
    row = {"status": "open", "due_date": "2026-12-01"}
    assert actions_mod.is_overdue(row, today=date(2026, 7, 18)) is False


def test_is_overdue_false_for_terminal_status_even_if_past_due():
    """A completed action whose due_date is in the past is not overdue —
    completion excludes it, matching scripts/actions.py's own docstring."""
    import actions as actions_mod
    row = {"status": "completed", "due_date": "2026-01-01"}
    assert actions_mod.is_overdue(row, today=date(2026, 7, 18)) is False


def test_is_overdue_false_for_no_due_date():
    import actions as actions_mod
    row = {"status": "open", "due_date": ""}
    assert actions_mod.is_overdue(row, today=date(2026, 7, 18)) is False


def test_is_due_soon_true_within_window():
    import actions as actions_mod
    row = {"status": "open", "due_date": "2026-07-22"}  # 4 days out
    assert actions_mod.is_due_soon(row, today=date(2026, 7, 18), window_days=7) is True


def test_is_due_soon_false_outside_window():
    import actions as actions_mod
    row = {"status": "open", "due_date": "2026-08-01"}  # 14 days out
    assert actions_mod.is_due_soon(row, today=date(2026, 7, 18), window_days=7) is False


def test_is_due_soon_false_when_already_overdue():
    """Intentional-failure case: an overdue action must NOT also be
    reported as 'due soon' — proves the two calculations are
    mutually exclusive, not just independently 'close enough'."""
    import actions as actions_mod
    row = {"status": "open", "due_date": "2026-07-01"}  # in the past
    assert actions_mod.is_due_soon(row, today=date(2026, 7, 18)) is False
    assert actions_mod.is_overdue(row, today=date(2026, 7, 18)) is True


def test_period_start_week_is_monday():
    import actions as actions_mod
    # 2026-07-18 is a Saturday.
    result = actions_mod.period_start("week", today=date(2026, 7, 18))
    assert result == date(2026, 7, 13)
    assert result.weekday() == 0


def test_period_start_month():
    import actions as actions_mod
    assert actions_mod.period_start("month", today=date(2026, 7, 18)) == date(2026, 7, 1)


def test_period_start_quarter():
    import actions as actions_mod
    assert actions_mod.period_start("quarter", today=date(2026, 8, 5)) == date(2026, 7, 1)
    assert actions_mod.period_start("quarter", today=date(2026, 1, 20)) == date(2026, 1, 1)
    assert actions_mod.period_start("quarter", today=date(2026, 11, 30)) == date(2026, 10, 1)


def test_period_start_year():
    import actions as actions_mod
    assert actions_mod.period_start("year", today=date(2026, 11, 30)) == date(2026, 1, 1)


def test_period_start_intentional_failure_unknown_period_raises():
    """Intentional-failure case: an unrecognised period string must raise,
    not silently fall through to some default range."""
    import actions as actions_mod
    import pytest
    with pytest.raises(ValueError):
        actions_mod.period_start("fortnight", today=date(2026, 7, 18))


def test_create_from_fields_preserves_original_due_date_across_defer(patched_actions):
    rows = patched_actions.read_actions()
    row = patched_actions.create_from_fields(
        {"description": "Fixture action", "due_date": "2026-07-01", "owner": "Test User", "vendor": "TestVendor"},
        rows,
    )
    assert row["due_date"] == "2026-07-01"
    assert row["original_due_date"] == "2026-07-01"
