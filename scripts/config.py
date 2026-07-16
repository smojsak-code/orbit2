#!/usr/bin/env python3
"""
Orbit2 application configuration loader/validator.

Reads data/app_config.json: the single place that stores who's using Orbit2,
which company and default vendor this instance scores, and a few display
preferences. Generated views (dashboard headings, Word/PowerPoint report
headers) read these values instead of hard-coding "Steve Mojsak" /
"Communardo" / "Atlassian" — see docs/data_dictionary.md for the full field
list.

Usage:
    python3 scripts/config.py --show          # print the effective config (defaults applied) as JSON
    python3 scripts/config.py --check-only    # validate only; non-zero exit on error

This file intentionally has no field for API keys, passwords, or connection
credentials (see the roadmap's "Non-negotiable engineering rules"). validate()
rejects the config if any key name looks like it's trying to store a secret,
at any nesting level.
"""
import argparse
import datetime
import json
import os
import re
import sys

try:
    from zoneinfo import ZoneInfo
    _HAVE_ZONEINFO = True
except ImportError:  # pragma: no cover - py<3.9 fallback, not expected here
    _HAVE_ZONEINFO = False

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "app_config.json")

REQUIRED_FIELDS = ["user_display_name", "company", "default_vendor"]

# Applied by load_config() for any field the file omits. reporting_year has
# no static default — it falls back to the current year at load time.
DEFAULTS = {
    "job_title": "",
    "timezone": "Europe/London",
    "financial_currency": "EUR",
    "reporting_year": None,
    "feature_flags": {},
}

# Deliberately small — extend as Orbit2 actually needs another currency
# rather than pre-guessing every ISO 4217 code.
VALID_CURRENCIES = {"EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK"}

SECRET_LIKE = re.compile(r"(api[_-]?key|secret|password|token|credential)", re.IGNORECASE)


def load_config(path=CONFIG_PATH):
    """Load app_config.json and apply documented defaults for any optional
    field that's missing or blank. Does not validate — call validate()
    separately so callers can decide how to handle problems."""
    if not os.path.exists(path):
        config = {}
    else:
        with open(path) as f:
            config = json.load(f)
    config.pop("_comment", None)

    merged = dict(DEFAULTS)
    merged.update(config)
    if not merged.get("reporting_year"):
        merged["reporting_year"] = datetime.date.today().year
    return merged


def _scan_for_secrets(obj, errors, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if SECRET_LIKE.search(str(k)):
                errors.append(
                    f"Field '{path}{k}' looks like it stores a secret/credential — "
                    f"not allowed in app_config.json"
                )
            _scan_for_secrets(v, errors, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan_for_secrets(v, errors, f"{path}[{i}].")


def validate(config):
    """Return a list of human-readable error strings for the given config
    dict (typically the output of load_config()). Empty list = valid."""
    errors = []

    for field in REQUIRED_FIELDS:
        if not str(config.get(field, "")).strip():
            errors.append(f"Missing required field: {field}")

    currency = config.get("financial_currency")
    if currency and currency not in VALID_CURRENCIES:
        errors.append(
            f"Invalid financial_currency '{currency}' (expected one of {sorted(VALID_CURRENCIES)})"
        )

    timezone = config.get("timezone")
    if timezone:
        if _HAVE_ZONEINFO:
            try:
                ZoneInfo(timezone)
            except Exception:
                errors.append(f"Invalid timezone '{timezone}' (not a recognised IANA timezone name)")
        # If zoneinfo's tz database isn't available in this environment,
        # skip the check rather than false-reject a plausible value.

    reporting_year = config.get("reporting_year")
    if reporting_year is not None:
        try:
            year = int(reporting_year)
            if year < 2000 or year > 2100:
                errors.append(f"reporting_year {year} is out of plausible range (2000-2100)")
        except (ValueError, TypeError):
            errors.append(f"reporting_year '{reporting_year}' is not a valid integer year")

    feature_flags = config.get("feature_flags")
    if feature_flags is not None and not isinstance(feature_flags, dict):
        errors.append("feature_flags must be an object of flag_name: true/false")
    elif isinstance(feature_flags, dict):
        for k, v in feature_flags.items():
            if not isinstance(v, bool):
                errors.append(f"feature_flags.{k} must be true or false, got {v!r}")

    _scan_for_secrets(config, errors)

    return errors


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--show", action="store_true", help="Print the effective configuration (defaults applied) as JSON.")
    ap.add_argument("--check-only", action="store_true", help="Validate only; print errors and exit non-zero if any.")
    args = ap.parse_args()

    config = load_config()
    errors = validate(config)

    if args.show:
        print(json.dumps(config, indent=2))

    if errors:
        print(f"data/app_config.json — {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print(f"  [ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    elif args.check_only:
        print("data/app_config.json is valid.")


if __name__ == "__main__":
    main()
