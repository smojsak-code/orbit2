"""
Migration 005: Add a `function` column to data/contacts.csv.

Why: Steve asked (2026-07-21) that every contact be sortable into one of
five functional sections — Management, Sales, Partner / Channel,
Delivery/Technical, Solution — so the Contacts tab can be browsed/searched
as groups of people ("show me everyone in Sales"), not just looked up one
person at a time (see scripts/contacts.py's VALID_FUNCTION/FUNCTION_LABELS
for the controlled vocabulary and full rationale). Before this migration,
contacts.csv had no field to record that. Unlike objectives.py's `category`
migration (004), this column is NOT required going forward — contacts are
very often auto-extracted from documents with incomplete information, so
`create`/`find-or-create`/`ingest` all accept `--function`/`function` as
OPTIONAL. This migration only handles the schema change for any contacts
that already existed — it backfills an empty string (never guesses),
leaving it to a follow-up `contacts.py edit --function` call to actually
sort each pre-existing row (validate_data.py warns on any row left blank
so this can't silently get missed).

Idempotent: only adds the column if it's not already present. Running this
(or the whole runner) twice never re-adds the column or touches a function
value someone already set.
"""
import csv
import os

MIGRATION_ID = "005_contacts_function"

# Mirrors scripts/contacts.py's FIELDNAMES at the time this migration was
# written. Deliberately hard-coded here (not imported) — a migration must
# keep working exactly as written even if contacts.py's schema evolves
# further later; see migration_004's own precedent for the same choice.
FIELDNAMES = [
    "contact_id", "status", "canonical_name", "raw_extracted_name",
    "title", "seniority", "department", "business_unit", "function", "company",
    "affiliation", "region", "country", "location", "email", "phone",
    "relationship_owner", "stakeholder_role", "influence_level",
    "relationship_strength", "vendor", "visibility", "merged_into",
    "first_seen_at", "last_interaction_at", "summary", "summary_updated_at",
    "created_at", "updated_at", "created_by", "updated_by", "notes",
]


def apply(data_dir):
    """Apply the migration. Returns a short human-readable summary string.
    Safe to call more than once."""
    path = os.path.join(data_dir, "contacts.csv")
    if not os.path.exists(path):
        return "data/contacts.csv does not exist yet — nothing to migrate (a fresh install already gets the column via scripts/contacts.py)."

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if "function" in fieldnames:
        return "data/contacts.csv already has a 'function' column — nothing to do."

    for r in rows:
        r["function"] = ""

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    return f"Added 'function' column to data/contacts.csv ({len(rows)} existing row(s) backfilled with an empty function — sort them with 'contacts.py edit --function ...')."
