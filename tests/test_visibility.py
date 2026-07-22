"""
Visibility filtering tests (R1-T09 instruction #53).

Both the homepage (R1-T06) and My Impact (R1-T07) public-site views
independently implement a personal_only exclusion — build_web.py's
_visible_for_homepage() and impact.py's _visible_for_impact(). These tests
prove both filters behave identically (excl. personal_only, incl. every
other visibility value) even though they're two separate functions, so a
future edit to one that silently diverges from the other gets caught.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

ALL_VISIBILITY_VALUES = [
    "personal_only", "communardo_internal", "communardo_management",
    "atlassian_shareable", "customer_approved", "anonymised", "public",
]


def test_homepage_visibility_excludes_only_personal_only():
    import build_web as build_web_mod
    for v in ALL_VISIBILITY_VALUES:
        row = {"visibility": v}
        expected = v != "personal_only"
        assert build_web_mod._visible_for_homepage(row) is expected, f"visibility={v}"


def test_homepage_visibility_defaults_to_personal_only_when_missing():
    """Intentional-failure case: a row with NO visibility field at all must
    be treated as the most restrictive value (personal_only), not
    accidentally leaked as public — proves the fail-safe default direction."""
    import build_web as build_web_mod
    assert build_web_mod._visible_for_homepage({}) is False
    assert build_web_mod._visible_for_homepage({"visibility": ""}) is False


def test_impact_visibility_excludes_only_personal_only():
    import impact as impact_mod
    for v in ALL_VISIBILITY_VALUES:
        row = {"visibility": v}
        expected = v != "personal_only"
        assert impact_mod._visible_for_impact(row) is expected, f"visibility={v}"


def test_impact_visibility_defaults_to_personal_only_when_missing():
    import impact as impact_mod
    assert impact_mod._visible_for_impact({}) is False


def test_homepage_and_impact_visibility_agree_on_every_value():
    """The two independent implementations must never diverge — if one is
    ever edited without the other, this test fails."""
    import build_web as build_web_mod
    import impact as impact_mod
    for v in ALL_VISIBILITY_VALUES + [""]:
        row = {"visibility": v}
        assert build_web_mod._visible_for_homepage(row) == impact_mod._visible_for_impact(row), f"visibility={v}"


# ---------------------------------------------------------------------------
# Contacts (Phase 4, R3-T01) deliberately use a STRICTER, separate policy —
# contacts.py's is_public_visible(), not _visible_for_homepage()/
# _visible_for_impact(). This is intentional (confirmed with Steve): those
# two exclude only personal_only because they describe Steve's own work;
# contacts carry real third parties' PII, so the bar is an explicit
# allow-list instead. These tests prove the two policies actually diverge
# on the values that matter, so a future "just reuse the homepage filter"
# refactor doesn't accidentally loosen the contacts bar.
# ---------------------------------------------------------------------------

def test_contacts_visibility_is_stricter_than_homepage_visibility():
    import contacts as contacts_mod
    import build_web as build_web_mod
    diverges_on = [
        v for v in ALL_VISIBILITY_VALUES
        if contacts_mod.is_public_visible({"visibility": v}) != build_web_mod._visible_for_homepage({"visibility": v})
    ]
    # communardo_internal and communardo_management pass the homepage's
    # bar (anything but personal_only) but must NOT pass the contacts bar.
    assert "communardo_internal" in diverges_on
    assert "communardo_management" in diverges_on


def test_compute_public_contacts_excludes_fixture_default_visibility_contact(patched_contacts):
    """tests/fixtures/data/contacts.csv's one contact has
    visibility=communardo_internal (the real create()/find-or-create()
    default) — compute_public_contacts() must return nothing for it."""
    import build_web as build_web_mod
    assert build_web_mod.compute_public_contacts() == []


def test_compute_public_contacts_includes_explicitly_cleared_contact_and_strips_pii(patched_contacts):
    import contacts as contacts_mod
    import build_web as build_web_mod
    contacts = contacts_mod.read_contacts()
    contacts[0]["visibility"] = "atlassian_shareable"
    contacts[0]["email"] = "jamie@atlassian.com"
    contacts_mod.write_contacts(contacts)

    public = build_web_mod.compute_public_contacts()
    assert len(public) == 1
    assert public[0]["contact_id"] == "CONT-0001"
    assert "email" not in public[0]


# ---------------------------------------------------------------------------
# Improvement Roadmap IR-A1/IR-A2/IR-C1 (2026-07-22) — scripts/visibility.py
# is the shared is_public_visible() service, extracted from Contacts Phase 4
# so Objectives and Actions can use the exact same allow-list Contacts
# already proved out, instead of each reinventing (or, as the 2026-07-22
# platform assessment found, simply never building) their own check. These
# tests lock in: the shared module's own behaviour, that contacts.py's
# re-exported names still resolve to the SAME function object (not a
# behaviour-alike copy that could drift), and that build_web.py's new
# objective/action filters actually exclude what they're supposed to.
# ---------------------------------------------------------------------------

def test_visibility_module_is_public_visible_matches_public_tiers_only():
    import visibility as visibility_mod
    for v in ALL_VISIBILITY_VALUES:
        row = {"visibility": v}
        expected = v in visibility_mod.PUBLIC_VISIBILITY_TIERS
        assert visibility_mod.is_public_visible(row) is expected, f"visibility={v}"


def test_visibility_module_defaults_to_excluded_when_missing():
    import visibility as visibility_mod
    assert visibility_mod.is_public_visible({}) is False
    assert visibility_mod.is_public_visible({"visibility": ""}) is False


def test_contacts_reexports_the_same_shared_visibility_function():
    """contacts.py must re-export scripts/visibility.py's actual function
    object (not a separate copy) — proves IR-C1's consolidation didn't
    leave two implementations that could silently drift apart again."""
    import contacts as contacts_mod
    import visibility as visibility_mod
    assert contacts_mod.is_public_visible is visibility_mod.is_public_visible
    assert contacts_mod.PUBLIC_VISIBILITY_TIERS is visibility_mod.PUBLIC_VISIBILITY_TIERS


def test_filter_public_objectives_excludes_internal_and_includes_shareable():
    import build_web as build_web_mod
    rows = [
        {"objective_id": "OBJ-0001", "visibility": "communardo_internal"},
        {"objective_id": "OBJ-0002", "visibility": "atlassian_shareable"},
        {"objective_id": "OBJ-0003", "visibility": ""},
        {"objective_id": "OBJ-0004"},  # missing key entirely
    ]
    result = build_web_mod.filter_public_objectives(rows)
    assert [o["objective_id"] for o in result] == ["OBJ-0002"]


def test_filter_public_actions_excludes_internal_and_includes_shareable():
    import build_web as build_web_mod
    rows = [
        {"action_id": "ACTN-0001", "visibility": "communardo_internal"},
        {"action_id": "ACTN-0002", "visibility": "public"},
        {"action_id": "ACTN-0003", "visibility": "personal_only"},
    ]
    result = build_web_mod.filter_public_actions(rows)
    assert [a["action_id"] for a in result] == ["ACTN-0002"]


def test_filter_public_actions_is_stricter_than_homepage_visibility():
    """The full public Actions list (filter_public_actions) and the
    homepage's own aggregate filter (_visible_for_homepage) are
    deliberately DIFFERENT rules — this proves they still diverge on
    communardo_internal the way the module-level comments describe, so a
    future refactor that accidentally unifies them gets caught."""
    import build_web as build_web_mod
    row = {"visibility": "communardo_internal"}
    assert build_web_mod._visible_for_homepage(row) is True
    assert build_web_mod.filter_public_actions([row]) == []


def _objective_with_detail(**detail_overrides):
    detail = {
        "linked_activities": [
            {"activity_id": "ACT-0001", "found": True, "visibility": "atlassian_shareable", "next_action": "Follow up with vendor"},
            {"activity_id": "ACT-0002", "found": True, "visibility": "communardo_internal", "next_action": "Private next step"},
            {"activity_id": "ACT-0003", "found": False},
        ],
        "action_points": [
            {"text": "From Partner Alliance Manager (Atlassian) JD, Responsibility 1", "source": "notes"},
            {"text": "Slipping because of Q3 budget freeze", "source": "at-risk reason"},
            {"text": "Follow up with vendor", "source": "next action from ACT-0001"},
            {"text": "Private next step", "source": "next action from ACT-0002"},
        ],
    }
    detail.update(detail_overrides)
    return {
        "objective_id": "OBJ-0001",
        "visibility": "atlassian_shareable",
        "notes": "From Partner Alliance Manager (Atlassian) JD, Responsibility 1",
        "at_risk_reason": "Slipping because of Q3 budget freeze",
        "recovery_action": "Escalate to VP",
        "completion_note": "",
        "missed_reason": "",
        "created_by": "Steve Mojsak",
        "updated_by": "Steve Mojsak",
        "detail": detail,
    }


def test_redact_public_objective_strips_internal_free_text_fields():
    import build_web as build_web_mod
    o = _objective_with_detail()
    redacted = build_web_mod.redact_public_objective(o)
    for f in ("notes", "at_risk_reason", "recovery_action", "completion_note", "missed_reason", "created_by", "updated_by"):
        assert redacted[f] == ""


def test_redact_public_objective_drops_linked_activity_that_is_not_public_visible():
    import build_web as build_web_mod
    o = _objective_with_detail()
    redacted = build_web_mod.redact_public_objective(o)
    ids = {a["activity_id"] for a in redacted["detail"]["linked_activities"]}
    assert ids == {"ACT-0001"}  # ACT-0002 is communardo_internal, ACT-0003 is a dangling (not found) reference


def test_redact_public_objective_drops_notes_and_at_risk_action_points_but_keeps_safe_next_actions():
    import build_web as build_web_mod
    o = _objective_with_detail()
    redacted = build_web_mod.redact_public_objective(o)
    sources = {ap["source"] for ap in redacted["detail"]["action_points"]}
    assert sources == {"next action from ACT-0001"}  # notes/at-risk reason dropped, and ACT-0002's next action dropped with it


def test_filter_public_objectives_applies_redaction_to_every_included_row():
    """filter_public_objectives() (what build_web.py actually calls) must
    apply the same redaction, not just the standalone function — this is
    what actually protects web_snapshot.json once an objective goes public
    (2026-07-22, prompted by Steve asking to publish his 8 JD objectives)."""
    import build_web as build_web_mod
    o = _objective_with_detail()
    result = build_web_mod.filter_public_objectives([o])
    assert len(result) == 1
    assert result[0]["notes"] == ""
    assert {a["activity_id"] for a in result[0]["detail"]["linked_activities"]} == {"ACT-0001"}


def test_redact_public_objective_tolerates_missing_detail_key():
    """Objectives with no detail computed yet (e.g. a bare test fixture)
    must not crash the redaction step."""
    import build_web as build_web_mod
    o = {"objective_id": "OBJ-0001", "visibility": "public"}
    redacted = build_web_mod.redact_public_objective(o)
    assert redacted["detail"] == {"linked_activities": [], "action_points": []}
