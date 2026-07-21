#!/usr/bin/env python3
"""
Orbit2 migration runner.

Applies pending schema migrations from scripts/migrations/ in order, each
identified by a MIGRATION_ID string registered in the MIGRATIONS list below.
Before applying ANY pending migration, takes a complete timestamped backup of
the data/ directory into backups/<timestamp>/. Records applied migrations in
data/schema_version.json so re-running the whole script is a safe no-op once
everything is applied — this is on top of each individual migration also
being written to be idempotent on its own.

Usage:
    python3 scripts/migrations/run_migrations.py            # apply all pending migrations
    python3 scripts/migrations/run_migrations.py --status    # show current version + history, apply nothing

To add a new migration:
    1. Write scripts/migrations/migration_NNN_description.py with an
       apply(data_dir) function that returns a short summary string.
    2. Add one entry to the MIGRATIONS list below.
"""
import argparse
import importlib
import json
import os
import shutil
import sys
from datetime import datetime

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(os.path.dirname(THIS_DIR))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEMA_VERSION_PATH = os.path.join(DATA_DIR, "schema_version.json")
BACKUP_ROOT = os.path.join(BASE_DIR, "backups")

# Register migrations here in application order.
# (migration_id, module_name, target_schema_version, description)
MIGRATIONS = [
    (
        "001_add_record_ids",
        "migration_001_add_record_ids",
        "1.1.0",
        "Add stable record_id columns to the 9 category sub-metric CSVs, "
        "metric_changelog.csv, solution_verticals.csv and news_log.csv.",
    ),
    (
        "002_metric_results_history",
        "migration_002_metric_results_history",
        "1.2.0",
        "Add data/metric_results_history.csv and data/verification_levels.json "
        "(R2-T01); migrate existing category sub-metric rows into a "
        "period-indexed, append-only result history without changing scoring.",
    ),
    (
        "003_contacts",
        "migration_003_contacts",
        "1.3.0",
        "Add data/contacts.csv, data/contact_aliases.csv, "
        "data/contact_evidence.jsonl and data/contact_evidence_fields.json "
        "(Contacts Phase 1 / R3-T01) — new registers, nothing to backfill.",
    ),
    (
        "004_objectives_category",
        "migration_004_objectives_category",
        "1.4.0",
        "Add a 'category' column to data/objectives.csv (relationship / "
        "commercial / strategic / operational / recognition) — pre-existing "
        "rows backfilled blank, to be sorted via 'objectives.py edit "
        "--category'.",
    ),
]


def load_schema_version():
    if not os.path.exists(SCHEMA_VERSION_PATH):
        return {"schema_version": "1.0.0", "applied_migrations": [], "history": []}
    with open(SCHEMA_VERSION_PATH) as f:
        return json.load(f)


def save_schema_version(state):
    with open(SCHEMA_VERSION_PATH, "w") as f:
        json.dump(state, f, indent=2)


def backup_data_dir():
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(BACKUP_ROOT, ts)
    shutil.copytree(DATA_DIR, dest)
    return dest


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--status", action="store_true",
        help="Show current schema version and migration history; apply nothing.",
    )
    args = ap.parse_args()

    state = load_schema_version()

    if args.status:
        print(f"Current schema version: {state.get('schema_version')}")
        applied = state.get("applied_migrations", [])
        print(f"Applied migrations: {', '.join(applied) if applied else '(none)'}")
        for h in state.get("history", []):
            print(f"  - {h.get('migration_id')} -> v{h.get('schema_version')} "
                  f"at {h.get('applied_at')} (backup: {h.get('backup')})")
        return

    applied = set(state.get("applied_migrations", []))
    pending = [m for m in MIGRATIONS if m[0] not in applied]

    if not pending:
        print(f"No pending migrations. Schema is at version {state.get('schema_version')}.")
        return

    backup_path = backup_data_dir()
    print(f"Backed up data/ to {os.path.relpath(backup_path, BASE_DIR)}")

    sys.path.insert(0, THIS_DIR)
    for migration_id, module_name, target_version, description in pending:
        module = importlib.import_module(module_name)
        print(f"Applying {migration_id}: {description}")
        summary = module.apply(DATA_DIR)
        print(f"  {summary}")
        state.setdefault("applied_migrations", []).append(migration_id)
        state.setdefault("history", []).append({
            "migration_id": migration_id,
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "schema_version": target_version,
            "description": description,
            "backup": os.path.relpath(backup_path, BASE_DIR),
        })
        state["schema_version"] = target_version
        # Save after each migration (not just at the end) so a mid-run
        # failure still leaves an accurate record of what succeeded.
        save_schema_version(state)

    print(f"Done. Schema version is now {state['schema_version']}.")


if __name__ == "__main__":
    main()
