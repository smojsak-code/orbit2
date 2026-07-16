"""
Migration 001: Add stable record_id columns to registers that previously had
no per-row stable identifier.

Why: R1-T01 of the Orbit2 technical roadmap requires every referenceable
record to carry a stable ID that never changes when a title, name or quarter
changes (see docs/data_dictionary.md, "Stable record IDs"). Before this
migration, category sub-metric rows, changelog rows, solution-vertical rows
and news-log rows were only identifiable by a composite key (e.g.
vendor+quarter+sub_metric) — fragile, because renaming a sub-metric or
re-running a quarter would silently orphan any future reference to that row.

Affected files (all live in data/):
  - The 9 category sub-metric CSVs (sales_performance.csv, marketing.csv,
    market_visibility.csv, ai_adoption.csv, business_planning_qbr.csv,
    registrations.csv, third_party_coselling.csv, solutions.csv,
    services.csv) -> shared "MET-" namespace. Every row across these 9 files
    is the same logical entity (a scorecard sub-metric result for one
    vendor/quarter) just partitioned by category into separate files for
    editing convenience, so they share one ID counter rather than nine.
  - metric_changelog.csv -> "CHG-" namespace.
  - solution_verticals.csv -> "SV-" namespace.
  - news_log.csv -> "NEWS-" namespace.

data/evidence_index.csv (evidence_id / "EVD-") and data/deals.csv (deal_id)
already had stable IDs before this migration and are left untouched.

Idempotent: only backfills a record_id for rows that don't already have one,
and continues numbering from the highest existing ID in that namespace.
Running this migration (or the whole runner) twice never reassigns,
duplicates, or renumbers an existing ID.
"""
import csv
import os

MIGRATION_ID = "001_add_record_ids"

CATEGORY_FILES = [
    "sales_performance", "marketing", "market_visibility", "ai_adoption",
    "business_planning_qbr", "registrations", "third_party_coselling",
    "solutions", "services",
]


def _read(path):
    if not os.path.exists(path):
        return None, []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _write(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _backfill_shared_namespace(data_dir, filenames, prefix):
    """Backfill record_id across one or more CSVs that share one ID
    namespace (e.g. all 9 category CSVs draw from the same MET- counter).
    Returns the list of filenames that were actually changed."""
    file_data = {}
    max_num = 0

    # First pass: find the current highest ID already in use for this
    # prefix, across every file in the shared namespace, so a fresh backfill
    # never collides with an ID a human (or another script) already assigned.
    for fname in filenames:
        path = os.path.join(data_dir, f"{fname}.csv")
        fieldnames, rows = _read(path)
        if fieldnames is None:
            continue
        for r in rows:
            existing = (r.get("record_id") or "").strip()
            if existing.startswith(prefix):
                try:
                    max_num = max(max_num, int(existing[len(prefix):]))
                except ValueError:
                    pass
        file_data[fname] = (path, fieldnames, rows)

    # Second pass: assign IDs to rows that don't have one yet, in file then
    # row order, so results are reproducible.
    changed = []
    for fname in filenames:
        if fname not in file_data:
            continue
        path, fieldnames, rows = file_data[fname]
        new_fieldnames = list(fieldnames)
        file_changed = "record_id" not in fieldnames
        if "record_id" not in new_fieldnames:
            new_fieldnames = ["record_id"] + new_fieldnames
        for r in rows:
            if not (r.get("record_id") or "").strip():
                max_num += 1
                r["record_id"] = f"{prefix}{max_num:04d}"
                file_changed = True
        if file_changed:
            _write(path, new_fieldnames, rows)
            changed.append(fname)
    return changed


def apply(data_dir):
    """Apply the migration. Returns a short human-readable summary string.
    Safe to call more than once — only touches rows/files that still need a
    record_id."""
    summary_parts = []

    changed = _backfill_shared_namespace(data_dir, CATEGORY_FILES, "MET-")
    if changed:
        summary_parts.append(
            "category sub-metric rows in " + ", ".join(f"{f}.csv" for f in changed)
        )

    changed = _backfill_shared_namespace(data_dir, ["metric_changelog"], "CHG-")
    if changed:
        summary_parts.append("metric_changelog.csv rows")

    changed = _backfill_shared_namespace(data_dir, ["solution_verticals"], "SV-")
    if changed:
        summary_parts.append("solution_verticals.csv rows")

    changed = _backfill_shared_namespace(data_dir, ["news_log"], "NEWS-")
    if changed:
        summary_parts.append("news_log.csv rows")

    if not summary_parts:
        return "No rows needed a record_id (already backfilled)."
    return "Added record_id to: " + "; ".join(summary_parts) + "."
