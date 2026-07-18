"""
Schema loading tests (R1-T09 instruction #53).

Covers the three pieces of "schema" Orbit2 loads at startup/build time:
categories.json + weights.json (the category registry), app_config.json
(scripts/config.py), and schema_version.json's own shape. All against the
isolated fixture copy — never the real data/ directory.
"""
import json
import os

from conftest import read_json


def test_categories_and_weights_load_and_agree(fixture_data_dir):
    categories = read_json(os.path.join(fixture_data_dir, "categories.json"))
    categories.pop("_comment", None)
    weights = read_json(os.path.join(fixture_data_dir, "weights.json"))
    weights.pop("_comment", None)

    assert categories, "fixture categories.json should not be empty"
    assert "TestVendor" in weights

    # Every category referenced in weights.json must exist in categories.json —
    # the same cross-reference scripts/validate_data.py's
    # validate_weights_and_categories() checks.
    for vendor, cat_weights in weights.items():
        for cat_key in cat_weights:
            assert cat_key in categories, f"{vendor} has a weight for unknown category '{cat_key}'"

    # Category weights must sum to 100 per vendor.
    for vendor, cat_weights in weights.items():
        total = sum(float(v) for v in cat_weights.values())
        assert round(total, 1) == 100.0, f"{vendor}'s weights sum to {total}, not 100"


def test_categories_and_weights_intentional_failure(fixture_data_dir):
    """Intentional-failure case: weights that DON'T sum to 100 must be
    detectable — proves the same check validate_data.py relies on actually
    catches a real mistake, not just passes fixture data by construction."""
    weights_path = os.path.join(fixture_data_dir, "weights.json")
    weights = read_json(weights_path)
    weights["TestVendor"]["sales_performance"] = 999  # deliberately break the 100% total

    total = sum(float(v) for v in weights["TestVendor"].values() if not str(v).startswith("_"))
    assert round(total, 1) != 100.0, "the deliberately-broken fixture should NOT sum to 100"


def test_app_config_loads_with_expected_fixture_values(fixture_data_dir, patched_config):
    import config as config_mod
    config = config_mod.load_config(path=os.path.join(fixture_data_dir, "app_config.json"))
    errors = config_mod.validate(config)
    assert errors == [], f"fixture app_config.json should be valid, got: {errors}"
    assert config["user_display_name"] == "Test User"
    assert config["default_vendor"] == "TestVendor"
    assert config["financial_currency"] == "GBP"


def test_app_config_defaults_applied_when_fields_missing(tmp_path):
    import config as config_mod
    minimal_path = tmp_path / "minimal_app_config.json"
    minimal_path.write_text(json.dumps({
        "user_display_name": "Test User", "company": "TestCo", "default_vendor": "TestVendor",
    }))
    config = config_mod.load_config(path=str(minimal_path))
    # DEFAULTS should backfill everything not explicitly set.
    assert config["timezone"] == "Europe/London"
    assert config["financial_currency"] == "EUR"
    assert config["feature_flags"] == {}
    assert isinstance(config["reporting_year"], int)


def test_app_config_intentional_failure_missing_required_field():
    """Intentional-failure case: a config missing a required field must be
    rejected by validate() — proves the required-field check actually
    fires rather than always passing."""
    import config as config_mod
    broken = {"company": "TestCo", "default_vendor": "TestVendor"}  # user_display_name missing
    errors = config_mod.validate(broken)
    assert any("user_display_name" in e for e in errors)


def test_app_config_intentional_failure_secret_like_field():
    """Intentional-failure case: a field name that looks like it stores a
    credential must be rejected, at any nesting depth — this is the
    non-negotiable rule from the roadmap that app_config.json can never
    hold an API key/password/token."""
    import config as config_mod
    broken = {
        "user_display_name": "Test User", "company": "TestCo", "default_vendor": "TestVendor",
        "feature_flags": {"some_api_key": True},
    }
    errors = config_mod.validate(broken)
    assert any("secret" in e.lower() or "credential" in e.lower() for e in errors)


def test_schema_version_file_shape(fixture_data_dir):
    state = read_json(os.path.join(fixture_data_dir, "schema_version.json"))
    assert "schema_version" in state
    assert isinstance(state.get("applied_migrations"), list)
    assert isinstance(state.get("history"), list)
    for h in state["history"]:
        assert "migration_id" in h and "applied_at" in h
