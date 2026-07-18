"""
Shared pytest fixtures for the Orbit2 test suite (R1-T09).

Every test that touches "data" operates on a throwaway copy of
tests/fixtures/data/ inside pytest's own tmp_path — never on the real
data/ directory. This is the mechanism behind the acceptance criterion
"Tests do not modify production data": there is no code path in this test
suite that can reach the real data/ directory, because every module's
path constants (DATA_DIR / JOURNAL_PATH / ACTIONS_PATH / OBJECTIVES_PATH /
CONFIG_PATH) are monkeypatched to point at the copy before any test body
runs, and monkeypatch automatically reverts them after the test.

Fixture data (tests/fixtures/data/) is entirely fabricated — fake vendor
("TestVendor"), fake user ("Test User"), fake company ("TestCo"), fake
organisations ("Fixture Corp", "Fixture Widgets Ltd"). No real Orbit2
production data, Communardo, or Atlassian confidential information appears
anywhere in tests/.
"""
import csv
import json
import os
import shutil
import sys

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(TESTS_DIR)
FIXTURE_DATA_DIR = os.path.join(TESTS_DIR, "fixtures", "data")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.join(SCRIPTS_DIR, "migrations"))


@pytest.fixture
def fixture_data_dir(tmp_path):
    """Copy tests/fixtures/data/ into a fresh tmp_path and return its path.
    Nothing under the real project's data/ directory is read or written by
    tests that use this fixture — only this throwaway copy is touched."""
    dest = tmp_path / "data"
    shutil.copytree(FIXTURE_DATA_DIR, dest)
    return str(dest)


@pytest.fixture
def patched_config(monkeypatch, fixture_data_dir):
    """config.py, pointed at the isolated fixture copy. Also applied inside
    the actions/objectives/journal fixtures below so that _default_user()/
    _default_vendor() (which call config.load_config() with no path
    override) resolve against the fixture's fake 'Test User'/'TestVendor'
    rather than reading the real project's data/app_config.json — read-only
    access to the real file wouldn't violate "no production data written",
    but it would make tests non-deterministic if that file ever changes."""
    import config as config_mod
    fixture_config_path = os.path.join(fixture_data_dir, "app_config.json")
    monkeypatch.setattr(config_mod, "DATA_DIR", fixture_data_dir)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", fixture_config_path)

    # load_config(path=CONFIG_PATH)'s default argument was already bound to
    # the REAL CONFIG_PATH at module-import time — reassigning the module
    # attribute above does not retroactively change that default (Python
    # evaluates default argument values once, at function-definition time).
    # Wrap it so a no-argument call still resolves to the fixture path.
    original_load_config = config_mod.load_config

    def _fixture_load_config(path=None):
        return original_load_config(path=path or fixture_config_path)

    monkeypatch.setattr(config_mod, "load_config", _fixture_load_config)
    return config_mod


@pytest.fixture
def patched_journal(monkeypatch, fixture_data_dir, patched_config):
    """journal.py, pointed at the isolated fixture copy."""
    import journal as journal_mod
    monkeypatch.setattr(journal_mod, "DATA_DIR", fixture_data_dir)
    monkeypatch.setattr(journal_mod, "JOURNAL_PATH", os.path.join(fixture_data_dir, "value_journal.jsonl"))
    monkeypatch.setattr(journal_mod, "ACTIVITY_TYPES_PATH", os.path.join(fixture_data_dir, "activity_types.json"))
    monkeypatch.setattr(journal_mod, "CONTRIBUTION_TYPES_PATH", os.path.join(fixture_data_dir, "contribution_types.json"))
    monkeypatch.setattr(journal_mod, "CHANGE_REQUESTS_DIR", os.path.join(fixture_data_dir, "change_requests"))
    monkeypatch.setattr(journal_mod, "CHANGE_REQUESTS_PROCESSED_DIR", os.path.join(fixture_data_dir, "change_requests", "processed"))
    return journal_mod


@pytest.fixture
def patched_actions(monkeypatch, fixture_data_dir, patched_config):
    """actions.py, pointed at the isolated fixture copy."""
    import actions as actions_mod
    monkeypatch.setattr(actions_mod, "DATA_DIR", fixture_data_dir)
    monkeypatch.setattr(actions_mod, "ACTIONS_PATH", os.path.join(fixture_data_dir, "actions.csv"))
    monkeypatch.setattr(actions_mod, "ACTION_STATUSES_PATH", os.path.join(fixture_data_dir, "action_statuses.json"))
    return actions_mod


@pytest.fixture
def patched_objectives(monkeypatch, fixture_data_dir, patched_config, patched_journal):
    """objectives.py, pointed at the isolated fixture copy. Depends on
    patched_journal too — objectives.py's _load_journal_by_id() (used by
    sum_linked_value progress and the CLI's `list`/`export` commands)
    imports journal.py internally and calls its read_journal(), so without
    this the sum_linked_value path would silently read the real project's
    value_journal.jsonl instead of the fixture."""
    import objectives as objectives_mod
    monkeypatch.setattr(objectives_mod, "DATA_DIR", fixture_data_dir)
    monkeypatch.setattr(objectives_mod, "OBJECTIVES_PATH", os.path.join(fixture_data_dir, "objectives.csv"))
    monkeypatch.setattr(objectives_mod, "REPORTS_DIR", os.path.join(fixture_data_dir, "..", "reports"))
    return objectives_mod


@pytest.fixture
def patched_validate_data(monkeypatch, fixture_data_dir, patched_config):
    """validate_data.py, pointed at the isolated fixture copy. Depends on
    patched_config too — validate_app_config() calls config.load_config()
    with no path argument, which (per patched_config's own docstring)
    needs the load_config wrapper, not just a DATA_DIR/CONFIG_PATH
    attribute patch, to actually resolve against the fixture."""
    import validate_data as validate_data_mod
    monkeypatch.setattr(validate_data_mod, "DATA_DIR", fixture_data_dir)
    return validate_data_mod


@pytest.fixture
def fixed_today(monkeypatch):
    """Pin actions.today_london() (and therefore every caller that doesn't
    take an explicit `today` override, notably impact.py's and
    objectives.py's use of it) to a fixed date, so period-bucketing tests
    don't depend on the real wall-clock date and stay correct indefinitely."""
    import datetime as _datetime
    import actions as actions_mod
    fixed = _datetime.date(2026, 7, 18)
    monkeypatch.setattr(actions_mod, "today_london", lambda: fixed)
    return fixed


def read_csv_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    with open(path) as f:
        return json.load(f)
