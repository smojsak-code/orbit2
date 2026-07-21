"""
Migration 003: Introduce the Contacts register (Phase 1, roadmap task
R3-T01 — pulled forward ahead of its original sequence position at Steve's
request).

Creates four new files if they don't already exist. There is nothing to
backfill: no contacts register existed before this, so this migration is
pure file creation, not a data transformation of anything else. It never
touches value_journal.jsonl, evidence_index.csv, or any other existing
register — a future task may wire value_journal.jsonl's free-text
`participants` field to real contact_ids, but that is explicitly out of
scope here (see scripts/contacts.py's module docstring for the full
design and docs/data_dictionary.md for the field reference).

  - data/contacts.csv                 Current profile view, one row per contact.
  - data/contact_aliases.csv          Known name spellings/variants per contact.
  - data/contact_evidence.jsonl       Append-only extracted-fact/observation log.
  - data/contact_evidence_fields.json Controlled vocabulary for evidence 'field'.

Idempotent: only creates a file if it's missing. Running this (or the whole
migration runner) twice never overwrites or duplicates anything.
"""
import json
import os

MIGRATION_ID = "003_contacts"

CONTACTS_FIELDNAMES = [
    "contact_id", "status", "canonical_name", "raw_extracted_name",
    "title", "seniority", "department", "business_unit", "company",
    "affiliation", "region", "country", "location", "email", "phone",
    "relationship_owner", "stakeholder_role", "influence_level",
    "relationship_strength", "vendor", "visibility", "merged_into",
    "first_seen_at", "last_interaction_at", "summary", "summary_updated_at",
    "created_at", "updated_at", "created_by", "updated_by", "notes",
]

ALIASES_FIELDNAMES = [
    "alias_id", "contact_id", "alias", "alias_type", "source_evidence_id",
    "added_at", "added_by",
]

DEFAULT_EVIDENCE_FIELDS = {
    "name": {"label": "Name (as extracted)", "group": "identity"},
    "title": {"label": "Title / job role", "group": "identity"},
    "seniority": {"label": "Seniority", "group": "identity"},
    "department": {"label": "Department", "group": "identity"},
    "business_unit": {"label": "Business unit", "group": "identity"},
    "company": {"label": "Company", "group": "identity"},
    "region": {"label": "Region", "group": "identity"},
    "country": {"label": "Country", "group": "identity"},
    "location": {"label": "Location", "group": "identity"},
    "email": {"label": "Email address", "group": "identity"},
    "phone": {"label": "Phone number", "group": "identity"},
    "topic_discussed": {"label": "Topic discussed", "group": "engagement"},
    "priority": {"label": "Priority", "group": "engagement"},
    "concern": {"label": "Concern", "group": "engagement"},
    "objective": {"label": "Objective", "group": "engagement"},
    "blocker": {"label": "Blocker", "group": "engagement"},
    "interest": {"label": "Interest", "group": "engagement"},
    "like": {"label": "Like", "group": "personal"},
    "dislike": {"label": "Dislike", "group": "personal"},
    "preference": {"label": "Preference", "group": "personal"},
    "communication_style": {"label": "Communication style", "group": "personal"},
    "personality_cue": {"label": "Personality cue", "group": "personal"},
    "influence_level": {"label": "Influence level signal", "group": "relationship"},
    "stakeholder_role": {"label": "Stakeholder role", "group": "relationship"},
    "relationship_strength_signal": {"label": "Relationship strength signal", "group": "relationship"},
    "commitment": {"label": "Commitment", "group": "actions"},
    "action": {"label": "Action / follow-up", "group": "actions"},
    "follow_up": {"label": "Follow-up needed", "group": "actions"},
    "key_date": {"label": "Key date", "group": "relationship"},
    "general_note": {"label": "General note", "group": "engagement"},
    "merge_event": {"label": "Merge/identity-resolution event (system-generated audit entry, not extracted content)", "group": "system"},
    "possible_duplicate": {"label": "Possible duplicate contact flagged for review (system-generated during batch ingest, not extracted content)", "group": "system"},
}


def apply(data_dir):
    """Apply the migration. Returns a short human-readable summary string.
    Safe to call more than once."""
    created = []

    contacts_path = os.path.join(data_dir, "contacts.csv")
    if not os.path.exists(contacts_path):
        with open(contacts_path, "w", newline="") as f:
            f.write(",".join(CONTACTS_FIELDNAMES) + "\n")
        created.append("data/contacts.csv")

    aliases_path = os.path.join(data_dir, "contact_aliases.csv")
    if not os.path.exists(aliases_path):
        with open(aliases_path, "w", newline="") as f:
            f.write(",".join(ALIASES_FIELDNAMES) + "\n")
        created.append("data/contact_aliases.csv")

    evidence_path = os.path.join(data_dir, "contact_evidence.jsonl")
    if not os.path.exists(evidence_path):
        with open(evidence_path, "w") as f:
            pass  # empty file — JSONL with zero lines is a valid empty register
        created.append("data/contact_evidence.jsonl")

    evidence_fields_path = os.path.join(data_dir, "contact_evidence_fields.json")
    if not os.path.exists(evidence_fields_path):
        with open(evidence_fields_path, "w") as f:
            json.dump(DEFAULT_EVIDENCE_FIELDS, f, indent=2)
        created.append("data/contact_evidence_fields.json")

    if not created:
        return "No files needed creating (already up to date)."
    return "Created: " + ", ".join(created) + "."
