"""
Migration 004: Add a `category` column to data/objectives.csv.

Why: Steve asked that every role objective be sorted into exactly one of
five sections — relationship, commercial, strategic, operational,
recognition (see scripts/objectives.py's module docstring for what belongs
in each, derived from the Partner Alliance Manager (Atlassian) job
description's six responsibility areas). Before this migration,
objectives.csv had no field to record that. `create` now requires
--category going forward; this migration only handles the schema change
for any objectives that already existed — it backfills an empty string
(never guesses a category), leaving it to a follow-up `edit --category`
call to actually sort each pre-existing row (validate_data.py warns on any
row left blank so this can't silently get missed).

Idempotent: only adds the column if it's not already present. Running this
(or the whole runner) twice never re-adds the column or touches a
category value someone already set.
"""
import csv
import os

MIGRATION_ID = "004_objectives_category"

# Mirrors scripts/objectives.py's FIELDNAMES at the time this migration was
# written. Deliberately hard-coded here (not imported) — a migration must
# keep working exactly as written even if objectives.py's schema evolves
# further later; see migration_001/002/003's own precedent for the same
# choice.
FIELDNAMES = [
    "objective_id", "period", "category", "objective", "success_measure",
    "target", "target_unit", "target_date",
    "communardo_priority", "atlassian_priority",
    "status", "progress_method", "progress_pct",
    "linked_activities", "linked_evidence",
    "at_risk_reason", "recovery_action",
    "completed_at", "completion_note",
    "missed_at", "missed_reason",
    "vendor", "visibility",
    "created_at", "updated_at", "created_by", "updated_by", "notes",
]


def apply(data_dir):
    """Apply the migration. Returns a short human-readable summary string.
    Safe to call more than once."""
    path = os.path.join(data_dir, "objectives.csv")
    if not os.path.exists(path):
        return "data/objectives.csv does not exist yet — nothing to migrate (a fresh install already gets the column via scripts/objectives.py)."

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if "category" in fieldnames:
        return "data/objectives.csv already has a 'category' column — nothing to do."

    for r in rows:
        r["category"] = ""

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    return f"Added 'category' column to data/objectives.csv ({len(rows)} existing row(s) backfilled with an empty category — categorise them with 'objectives.py edit --category ...')."
