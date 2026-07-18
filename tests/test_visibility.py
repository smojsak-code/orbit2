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
