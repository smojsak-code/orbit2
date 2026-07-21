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
