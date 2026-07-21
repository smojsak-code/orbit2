#!/usr/bin/env python3
"""
Orbit2 Contacts register — stakeholder identity resolution and profile
history (Contacts Phase 1, formalised as roadmap task R3-T01, pulled
forward ahead of its original sequence position at Steve's request).

Storage: three files, each doing one job (same "separate the current view
from the evidence trail" discipline scripts/metric_results.py established
in R2-T01):

  - data/contacts.csv           One row per contact — the CURRENT profile
                                 view only. Never holds history; see below.
  - data/contact_aliases.csv    Known name spellings/variants per contact,
                                 so "Jon Smith" and "Jonathan Smythe" are
                                 provably the same contact_id over time.
  - data/contact_evidence.jsonl Append-only. One row per extracted fact or
                                 observation, ever. NEVER edited or deleted
                                 — a field's "current value" is derived by
                                 finding the most recent non-superseded
                                 evidence row for that field, not by
                                 mutating contacts.csv's history in place.
                                 contacts.csv's own current-view columns
                                 are a cache of that derivation, refreshed
                                 by add-evidence — the append-only log is
                                 the actual source of truth.

Why this shape: a contact profile has a handful of stable, single-valued
identity fields (title, company, email, ...) that suit a CSV's current-view
row, but also an open-ended, ever-growing set of observations (topics
discussed, priorities, likes/dislikes, commitments...) that don't fit
fixed columns and must never be overwritten — journal.py made the same
CSV-vs-JSONL call for value_journal.jsonl for the same reason.

Commands:
  find-or-create   The identity resolution entry point. Given a name (plus
                    optional company/title/email/context), decides whether
                    this is an existing confirmed contact, a likely match
                    needing human review, or a brand new provisional
                    contact — and creates the provisional contact if so.
                    Never silently merges an ambiguous match.
  create            Explicitly create a contact (skips matching — use when
                    you already know this is a new person).
  edit               Update non-terminal identity fields directly.
  confirm            Move a provisional contact to confirmed status.
  set-canonical-name Correct/confirm the canonical name. Automatically logs
                    the prior name as an alias, so the platform can say
                    "originally extracted as 'Jon Smith', later confirmed
                    as 'Jonathan Smythe'."
  add-alias          Manually record a known spelling variant/nickname.
  add-evidence        Append one extracted fact/observation. If the field
                    maps to a contacts.csv column and the new evidence is
                    at least as well-supported as what's currently on file,
                    refreshes that column and marks the prior evidence for
                    that field superseded (never deleted).
  resolve-match       Human review verdict on a needs_review match from
                    find-or-create: either merge the provisional contact
                    into the suggested match, or confirm it's a distinct
                    person.
  merge               Merge one contact into another directly (the losing
                    contact_id is preserved with status=merged and
                    merged_into set — never deleted, and every prior
                    evidence/alias row keeps pointing at its original
                    contact_id; resolve_canonical() follows the chain).
  archive             Mark a contact archived (never deletes).
  summary             Print the generated profile summary for one contact.
  list                List contacts with optional filters.

Every command prints what it did. Run scripts/validate_data.py afterwards.
"""
import argparse
import csv
import difflib
import json
import os
import re
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONTACTS_PATH = os.path.join(DATA_DIR, "contacts.csv")
ALIASES_PATH = os.path.join(DATA_DIR, "contact_aliases.csv")
EVIDENCE_PATH = os.path.join(DATA_DIR, "contact_evidence.jsonl")
EVIDENCE_FIELDS_PATH = os.path.join(DATA_DIR, "contact_evidence_fields.json")

FIELDNAMES = [
    "contact_id", "status", "canonical_name", "raw_extracted_name",
    "title", "seniority", "department", "business_unit", "company",
    "affiliation", "region", "country", "location", "email", "phone",
    "relationship_owner", "stakeholder_role", "influence_level",
    "relationship_strength", "vendor", "visibility", "merged_into",
    "first_seen_at", "last_interaction_at", "summary", "summary_updated_at",
    "created_at", "updated_at", "created_by", "updated_by", "notes",
]

ALIAS_FIELDNAMES = [
    "alias_id", "contact_id", "alias", "alias_type", "source_evidence_id",
    "added_at", "added_by",
]

VALID_STATUS = {"provisional", "confirmed", "merged", "archived"}
TERMINAL_STATUSES = {"merged", "archived"}
EDITABLE_STATUSES = {"provisional", "confirmed"}
VALID_AFFILIATION = {"", "communardo", "atlassian", "customer", "partner", "other"}
VALID_INFLUENCE = {"", "low", "medium", "high", "critical"}
VALID_RELATIONSHIP_STRENGTH = {"", "weak", "developing", "strong", "at_risk"}
VALID_ALIAS_TYPE = {"name_spelling", "nickname", "prior_name", "title_variant", "company_variant"}
VALID_SOURCE_TYPE = {
    "meeting_note", "transcript", "audio_summary", "document", "slide_deck",
    "pdf", "spreadsheet", "email_summary", "manual_note",
}
VALID_CONFIDENCE = {"confirmed", "probable", "low_confidence"}
CONFIDENCE_RANK = {"low_confidence": 0, "probable": 1, "confirmed": 2}
VALID_SENSITIVITY = {"standard", "subjective", "sensitive"}
VALID_REVIEWER_STATUS = {"unreviewed", "confirmed", "rejected"}
VALID_VISIBILITY = {
    "personal_only", "communardo_internal", "communardo_management",
    "atlassian_shareable", "customer_approved", "anonymised", "public",
}

# contact_evidence.jsonl 'field' values that have a direct contacts.csv
# current-view column. Everything else (topics, priorities, likes,
# commitments, ...) lives only in the evidence log and is rolled up by
# compute_profile_summary() instead — there's no single "current value"
# for an open-ended observation the way there is for a title or email.
FIELD_TO_CONTACT_COLUMN = {
    "title": "title", "seniority": "seniority", "department": "department",
    "business_unit": "business_unit", "company": "company",
    "region": "region", "country": "country", "location": "location",
    "email": "email", "phone": "phone",
    "influence_level": "influence_level", "stakeholder_role": "stakeholder_role",
    "relationship_strength_signal": "relationship_strength",
}

DEFAULT_USER = "Steve Mojsak"
DEFAULT_VENDOR = "Atlassian"

# Auto-match / needs-review thresholds for find_candidate_matches(). Deliberately
# conservative — per the spec's own rule, "must not treat spelling differences
# alone as a new person when other evidence suggests the same identity" cuts
# both ways: it's just as important never to silently fold two different
# people together. An exact email match is the only thing trusted enough to
# auto-match on its own; every name-based match needs a corroborating signal
# (company or title) to auto-match, and anything below AUTO_MATCH_THRESHOLD
# is surfaced for human review rather than acted on.
AUTO_MATCH_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.55


def _app_config():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config as app_config
        return app_config.load_config()
    except Exception:
        return {}


def _default_user():
    return _app_config().get("user_display_name") or DEFAULT_USER


def _default_vendor():
    return _app_config().get("default_vendor") or DEFAULT_VENDOR


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _today_iso():
    return date.today().isoformat()


def load_evidence_fields():
    if not os.path.exists(EVIDENCE_FIELDS_PATH):
        return {}
    with open(EVIDENCE_FIELDS_PATH) as f:
        fields = json.load(f)
    fields.pop("_comment", None)
    return fields


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def read_contacts():
    if not os.path.exists(CONTACTS_PATH):
        return []
    with open(CONTACTS_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_contacts(rows):
    with open(CONTACTS_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})


def read_aliases():
    if not os.path.exists(ALIASES_PATH):
        return []
    with open(ALIASES_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_aliases(rows):
    with open(ALIASES_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ALIAS_FIELDNAMES)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in ALIAS_FIELDNAMES})


def read_evidence():
    if not os.path.exists(EVIDENCE_PATH):
        return []
    rows = []
    with open(EVIDENCE_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_evidence(rows):
    with open(EVIDENCE_PATH, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def next_contact_id(contacts=None):
    contacts = contacts if contacts is not None else read_contacts()
    max_num = 0
    for r in contacts:
        cid = (r.get("contact_id") or "").strip()
        if cid.startswith("CONT-"):
            try:
                max_num = max(max_num, int(cid[5:]))
            except ValueError:
                pass
    return f"CONT-{max_num + 1:04d}"


def next_alias_id(aliases=None):
    aliases = aliases if aliases is not None else read_aliases()
    max_num = 0
    for r in aliases:
        aid = (r.get("alias_id") or "").strip()
        if aid.startswith("ALIAS-"):
            try:
                max_num = max(max_num, int(aid[6:]))
            except ValueError:
                pass
    return f"ALIAS-{max_num + 1:04d}"


def next_evidence_id(evidence=None):
    evidence = evidence if evidence is not None else read_evidence()
    max_num = 0
    for r in evidence:
        eid = (r.get("evidence_id") or "").strip()
        if eid.startswith("CEV-"):
            try:
                max_num = max(max_num, int(eid[4:]))
            except ValueError:
                pass
    return f"CEV-{max_num + 1:04d}"


def contacts_by_id(contacts=None):
    contacts = contacts if contacts is not None else read_contacts()
    return {r["contact_id"]: r for r in contacts if r.get("contact_id")}


def resolve_canonical(contact_id, contacts_by_id_map, _seen=None):
    """Follow merged_into chains to the current canonical contact_id for a
    given id. A merged contact's row is never deleted or rewritten — this
    is how callers find where its history now lives. Guards against a
    pathological cycle (should never happen in practice) by tracking
    visited ids."""
    _seen = _seen or set()
    row = contacts_by_id_map.get(contact_id)
    if not row or contact_id in _seen:
        return contact_id
    merged_into = (row.get("merged_into") or "").strip()
    if row.get("status") == "merged" and merged_into:
        _seen.add(contact_id)
        return resolve_canonical(merged_into, contacts_by_id_map, _seen)
    return contact_id


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize_name(name):
    name = (name or "").strip().lower()
    name = _PUNCT_RE.sub(" ", name)
    name = _WS_RE.sub(" ", name).strip()
    return name


def name_similarity(a, b):
    """0.0-1.0. Plain stdlib difflib rather than an external fuzzy-matching
    dependency, consistent with the rest of this project's near-zero
    third-party Python footprint."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def find_candidate_matches(name, company=None, title=None, email=None, contacts=None):
    """Return a list of {contact_id, score, reasons} for every non-merged,
    non-archived contact that could plausibly be the same person as `name`,
    sorted by score descending. score combines name similarity with
    corroborating signals (company/title match, exact email) — see the
    module docstring's AUTO_MATCH_THRESHOLD/REVIEW_THRESHOLD note for how
    the score is used by match_contact()."""
    contacts = contacts if contacts is not None else read_contacts()
    email_norm = (email or "").strip().lower()
    company_norm = normalize_name(company) if company else ""
    title_norm = normalize_name(title) if title else ""

    candidates = []
    for r in contacts:
        if r.get("status") in ("merged", "archived"):
            continue

        if email_norm and (r.get("email") or "").strip().lower() == email_norm:
            candidates.append({"contact_id": r["contact_id"], "score": 1.0, "reasons": ["exact email match"]})
            continue

        names_to_check = [r.get("canonical_name", ""), r.get("raw_extracted_name", "")]
        best_name_score = max((name_similarity(name, n) for n in names_to_check if n), default=0.0)
        if best_name_score < 0.5:
            continue  # not even remotely similar — skip rather than pollute results

        score = best_name_score
        reasons = [f"name similarity {best_name_score:.2f}"]

        if company_norm and normalize_name(r.get("company", "")) == company_norm:
            score = min(1.0, score + 0.25)
            reasons.append("same company")
        if title_norm and normalize_name(r.get("title", "")) == title_norm:
            score = min(1.0, score + 0.10)
            reasons.append("same title")

        candidates.append({"contact_id": r["contact_id"], "score": round(score, 3), "reasons": reasons})

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def match_contact(name, company=None, title=None, email=None, contacts=None):
    """The core identity-resolution decision. Returns a dict:
      {"decision": "matched", "contact_id": ..., "score": ..., "reasons": [...]}
      {"decision": "needs_review", "contact_id": <best candidate>, "score": ..., "reasons": [...]}
      {"decision": "new", "candidates": [<runner-up candidates, if any, for context>]}
    'matched' only fires on an exact email match or a name+corroborating-signal
    score at/above AUTO_MATCH_THRESHOLD — anything plausible but short of that
    bar is 'needs_review', never silently merged (spec: "must not treat
    spelling differences alone as a new person when other evidence suggests
    the same identity" — the corollary this enforces is that ambiguous
    evidence must not be silently treated as the SAME person either)."""
    candidates = find_candidate_matches(name, company=company, title=title, email=email, contacts=contacts)
    if not candidates:
        return {"decision": "new", "candidates": []}

    top = candidates[0]
    if top["score"] >= AUTO_MATCH_THRESHOLD:
        return {"decision": "matched", "contact_id": top["contact_id"], "score": top["score"], "reasons": top["reasons"]}
    if top["score"] >= REVIEW_THRESHOLD:
        return {"decision": "needs_review", "contact_id": top["contact_id"], "score": top["score"], "reasons": top["reasons"]}
    return {"decision": "new", "candidates": candidates}


# ---------------------------------------------------------------------------
# Profile summary (deterministic, template-generated — no AI call, same
# discipline as impact.py's generate_narrative() and objectives.py's export:
# every sentence must be traceable back to a field the summary also lists
# directly, not invented.)
# ---------------------------------------------------------------------------

def _current_evidence_for_field(contact_id, field, evidence_rows):
    """Non-superseded evidence rows for this contact+field, newest first."""
    rows = [
        e for e in evidence_rows
        if e.get("contact_id") == contact_id and e.get("field") == field
        and not e.get("superseded_by")
    ]
    return sorted(rows, key=lambda e: e.get("extracted_at", ""), reverse=True)


def compute_profile_summary(contact_id, contacts, evidence_rows, aliases):
    """Returns a dict: {text, confirmed, probable, subjective, missing,
    open_actions, aliases_note}. `text` is the rendered summary; the other
    keys are the structured data it was built from, so a UI can also
    render them directly rather than re-parsing the text."""
    contacts_map = contacts_by_id(contacts)
    row = contacts_map.get(contact_id)
    if not row:
        return {"text": f"No contact found for {contact_id}.", "confirmed": [], "probable": [], "subjective": [], "missing": [], "open_actions": [], "aliases_note": ""}

    evidence_fields = load_evidence_fields()
    own_evidence = [e for e in evidence_rows if e.get("contact_id") == contact_id]

    confirmed, probable, subjective = [], [], []
    for e in sorted(own_evidence, key=lambda e: e.get("extracted_at", ""), reverse=True):
        if e.get("superseded_by"):
            continue
        if e.get("field") == "merge_event":
            continue
        label = evidence_fields.get(e.get("field", ""), {}).get("label", e.get("field", ""))
        line = f"{label}: {e.get('value', '')}"
        if e.get("sensitivity") == "subjective":
            subjective.append(line)
        elif e.get("confidence") == "confirmed":
            confirmed.append(line)
        else:
            probable.append(line)

    open_actions = [
        e.get("value", "") for e in own_evidence
        if e.get("field") in ("commitment", "action", "follow_up") and not e.get("superseded_by")
    ]

    missing = []
    for key, label in (("title", "title"), ("company", "company"), ("email", "email address")):
        if not (row.get(key) or "").strip():
            missing.append(label)

    contact_aliases = [a["alias"] for a in aliases if a.get("contact_id") == contact_id]
    aliases_note = ""
    raw = (row.get("raw_extracted_name") or "").strip()
    canonical = (row.get("canonical_name") or "").strip()
    if raw and canonical and raw != canonical:
        aliases_note = f"Originally extracted as '{raw}', later confirmed as '{canonical}'."
    if contact_aliases:
        aliases_note = (aliases_note + " " if aliases_note else "") + f"Known aliases/variants: {', '.join(contact_aliases)}."

    lines = [
        f"{canonical or raw or contact_id} — {row.get('title') or 'title unknown'}"
        + (f" at {row.get('company')}" if row.get("company") else "")
        + f". Status: {row.get('status')}.",
    ]
    if aliases_note:
        lines.append(aliases_note)
    if row.get("influence_level") or row.get("relationship_strength"):
        lines.append(
            f"Influence: {row.get('influence_level') or 'unknown'}. "
            f"Relationship strength: {row.get('relationship_strength') or 'unknown'}."
        )
    if confirmed:
        lines.append("Confirmed: " + "; ".join(confirmed))
    if probable:
        lines.append("Probable (unconfirmed): " + "; ".join(probable))
    if subjective:
        lines.append("Subjective observations: " + "; ".join(subjective))
    if open_actions:
        lines.append("Open actions/follow-ups: " + "; ".join(open_actions))
    if missing:
        lines.append("Missing information to confirm: " + ", ".join(missing) + ".")

    return {
        "text": "\n".join(lines),
        "confirmed": confirmed, "probable": probable, "subjective": subjective,
        "missing": missing, "open_actions": open_actions, "aliases_note": aliases_note,
    }


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_find_or_create(args):
    contacts = read_contacts()
    decision = match_contact(args.name, company=args.company, title=args.title, email=args.email, contacts=contacts)

    if decision["decision"] == "matched":
        print(f"MATCHED: '{args.name}' -> {decision['contact_id']} (score {decision['score']}, {', '.join(decision['reasons'])})")
        return decision

    if decision["decision"] == "needs_review":
        print(f"NEEDS REVIEW: '{args.name}' is a possible match for {decision['contact_id']} "
              f"(score {decision['score']}, {', '.join(decision['reasons'])}) — not auto-matched. "
              f"Use 'resolve-match' once confirmed, or 'create' to make it a distinct new contact.")
        return decision

    # decision == "new"
    now = _now_iso()
    contact_id = next_contact_id(contacts)
    row = {k: "" for k in FIELDNAMES}
    row.update({
        "contact_id": contact_id, "status": "provisional",
        "canonical_name": args.name, "raw_extracted_name": args.name,
        "company": args.company or "", "title": args.title or "", "email": args.email or "",
        "relationship_owner": _default_user(), "vendor": args.vendor or _default_vendor(),
        "visibility": args.visibility or "communardo_internal",
        "first_seen_at": now, "last_interaction_at": now,
        "created_at": now, "updated_at": now,
        "created_by": _default_user(), "updated_by": _default_user(),
    })
    contacts.append(row)
    write_contacts(contacts)
    print(f"Created new provisional contact {contact_id} for '{args.name}'."
          + (f" ({len(decision['candidates'])} other loosely-similar contact(s) found but below review threshold.)" if decision["candidates"] else ""))
    decision["contact_id"] = contact_id
    return decision


def cmd_create(args):
    contacts = read_contacts()
    now = _now_iso()
    contact_id = next_contact_id(contacts)
    row = {k: "" for k in FIELDNAMES}
    row.update({
        "contact_id": contact_id, "status": "confirmed",
        "canonical_name": args.name, "raw_extracted_name": args.name,
        "title": args.title or "", "company": args.company or "", "email": args.email or "",
        "affiliation": args.affiliation or "", "relationship_owner": _default_user(),
        "vendor": args.vendor or _default_vendor(), "visibility": args.visibility or "communardo_internal",
        "first_seen_at": now, "last_interaction_at": now,
        "created_at": now, "updated_at": now,
        "created_by": _default_user(), "updated_by": _default_user(),
    })
    contacts.append(row)
    write_contacts(contacts)
    print(f"Created confirmed contact {contact_id} for '{args.name}'.")


EDITABLE_FIELDS = [
    "title", "seniority", "department", "business_unit", "company", "affiliation",
    "region", "country", "location", "email", "phone", "relationship_owner",
    "stakeholder_role", "influence_level", "relationship_strength", "vendor",
    "visibility", "notes",
]


def cmd_edit(args):
    contacts = read_contacts()
    found = False
    for r in contacts:
        if r["contact_id"] == args.contact_id:
            if r.get("status") in TERMINAL_STATUSES:
                print(f"{args.contact_id} has status '{r.get('status')}' — cannot edit directly. Use a dedicated command.")
                return
            for field in EDITABLE_FIELDS:
                value = getattr(args, field, None)
                if value is not None:
                    r[field] = value
            r["updated_at"] = _now_iso()
            r["updated_by"] = _default_user()
            found = True
            break
    if not found:
        print(f"No contact found with contact_id '{args.contact_id}'.")
        return
    write_contacts(contacts)
    print(f"Updated {args.contact_id}.")


def cmd_confirm(args):
    contacts = read_contacts()
    for r in contacts:
        if r["contact_id"] == args.contact_id:
            if r.get("status") != "provisional":
                print(f"{args.contact_id} is not provisional (status: {r.get('status')}) — nothing to confirm.")
                return
            r["status"] = "confirmed"
            if args.canonical_name:
                r["canonical_name"] = args.canonical_name
            r["updated_at"] = _now_iso()
            r["updated_by"] = _default_user()
            write_contacts(contacts)
            print(f"Confirmed {args.contact_id} as '{r['canonical_name']}'.")
            return
    print(f"No contact found with contact_id '{args.contact_id}'.")


def cmd_set_canonical_name(args):
    contacts = read_contacts()
    aliases = read_aliases()
    for r in contacts:
        if r["contact_id"] == args.contact_id:
            old_name = (r.get("canonical_name") or "").strip()
            if old_name and old_name != args.name and normalize_name(old_name) != normalize_name(args.name):
                aliases.append({
                    "alias_id": next_alias_id(aliases), "contact_id": args.contact_id,
                    "alias": old_name, "alias_type": "prior_name",
                    "source_evidence_id": "", "added_at": _today_iso(), "added_by": _default_user(),
                })
                write_aliases(aliases)
            r["canonical_name"] = args.name
            r["updated_at"] = _now_iso()
            r["updated_by"] = _default_user()
            write_contacts(contacts)
            print(f"Set canonical name for {args.contact_id} to '{args.name}'."
                  + (f" Preserved '{old_name}' as a known alias." if old_name and old_name != args.name else ""))
            return
    print(f"No contact found with contact_id '{args.contact_id}'.")


def cmd_add_alias(args):
    contacts_map = contacts_by_id()
    if args.contact_id not in contacts_map:
        print(f"No contact found with contact_id '{args.contact_id}'.")
        return
    aliases = read_aliases()
    aliases.append({
        "alias_id": next_alias_id(aliases), "contact_id": args.contact_id,
        "alias": args.alias, "alias_type": args.alias_type,
        "source_evidence_id": args.source_evidence_id or "",
        "added_at": _today_iso(), "added_by": _default_user(),
    })
    write_aliases(aliases)
    print(f"Added alias '{args.alias}' ({args.alias_type}) for {args.contact_id}.")


def cmd_add_evidence(args):
    contacts = read_contacts()
    contacts_map = {r["contact_id"]: r for r in contacts}
    if args.contact_id not in contacts_map:
        print(f"No contact found with contact_id '{args.contact_id}'. Run find-or-create first.")
        return

    evidence_fields = load_evidence_fields()
    if evidence_fields and args.field not in evidence_fields:
        print(f"WARNING: field '{args.field}' is not in data/contact_evidence_fields.json — allowed anyway, "
              f"but consider adding it to the controlled list.")

    evidence = read_evidence()
    row = contacts_map[args.contact_id]

    new_id = next_evidence_id(evidence)
    now_date = args.extracted_at or _today_iso()
    new_entry = {
        "evidence_id": new_id, "contact_id": args.contact_id, "extracted_at": now_date,
        "source_type": args.source_type, "source_ref": args.source_ref or "",
        "field": args.field, "value": args.value,
        "confidence": args.confidence, "sensitivity": args.sensitivity,
        "reviewer_status": "unreviewed", "superseded_by": "",
        "rationale": args.rationale or "", "meeting_ref": args.meeting_ref or "",
        "created_by": _default_user(),
    }

    # Supersede the prior current evidence for this exact field, and refresh
    # the contacts.csv cached column, only if the new evidence is at least
    # as well-supported (acceptance rule: "update the contact profile only
    # where the new evidence is relevant, more recent, more complete, or
    # better supported"). A field with no prior evidence always applies.
    applied_to_profile = False
    prior = _current_evidence_for_field(args.contact_id, args.field, evidence)
    column = FIELD_TO_CONTACT_COLUMN.get(args.field)
    if column:
        if not prior or CONFIDENCE_RANK.get(args.confidence, 0) >= CONFIDENCE_RANK.get(prior[0].get("confidence"), 0):
            for p in prior:
                p["superseded_by"] = new_id
            row[column] = args.value
            row["updated_at"] = _now_iso()
            row["updated_by"] = _default_user()
            applied_to_profile = True

    row["last_interaction_at"] = max(row.get("last_interaction_at") or "", now_date)

    evidence.append(new_entry)
    write_evidence(evidence)
    write_contacts(contacts)

    print(f"Logged evidence {new_id} ({args.field}={args.value!r}, confidence={args.confidence}) for {args.contact_id}."
          + (f" Updated contacts.csv '{column}'." if applied_to_profile else
             (" Did not overwrite the current profile value (existing evidence is equally or better supported)." if column else "")))


def cmd_resolve_match(args):
    """Human verdict on a needs_review candidate from find-or-create."""
    if args.verdict == "same":
        return cmd_merge(argparse.Namespace(losing_id=args.contact_id, surviving_id=args.matched_contact_id, reason=args.reason or "Confirmed same person via resolve-match"))
    elif args.verdict == "different":
        print(f"Recorded: {args.contact_id} is a DIFFERENT person from {args.matched_contact_id} — no merge performed. "
              f"Consider add-alias if the similarity was a coincidental spelling overlap worth tracking.")
    else:
        print(f"Unknown verdict '{args.verdict}' — expected 'same' or 'different'.")


def cmd_merge(args):
    contacts = read_contacts()
    contacts_map = {r["contact_id"]: r for r in contacts}
    if args.losing_id not in contacts_map or args.surviving_id not in contacts_map:
        print("Both losing_id and surviving_id must be existing contact_ids.")
        return
    if args.losing_id == args.surviving_id:
        print("Cannot merge a contact into itself.")
        return

    losing = contacts_map[args.losing_id]
    surviving = contacts_map[args.surviving_id]
    now = _now_iso()

    losing["status"] = "merged"
    losing["merged_into"] = args.surviving_id
    losing["updated_at"] = now
    losing["updated_by"] = _default_user()

    # Preserve the losing contact's raw-extracted name as an alias on the
    # survivor, if not already known — this is exactly the "Jon Smith" ->
    # "Jonathan Smythe" case when the two records get merged rather than
    # one contact simply being renamed.
    aliases = read_aliases()
    raw = (losing.get("raw_extracted_name") or losing.get("canonical_name") or "").strip()
    if raw and not any(a["contact_id"] == args.surviving_id and normalize_name(a["alias"]) == normalize_name(raw) for a in aliases):
        aliases.append({
            "alias_id": next_alias_id(aliases), "contact_id": args.surviving_id,
            "alias": raw, "alias_type": "name_spelling",
            "source_evidence_id": "", "added_at": _today_iso(), "added_by": _default_user(),
        })
        write_aliases(aliases)

    surviving["last_interaction_at"] = max(surviving.get("last_interaction_at") or "", losing.get("last_interaction_at") or "")
    surviving["updated_at"] = now
    surviving["updated_by"] = _default_user()

    write_contacts(contacts)

    evidence = read_evidence()
    evidence.append({
        "evidence_id": next_evidence_id(evidence), "contact_id": args.losing_id,
        "extracted_at": _today_iso(), "source_type": "manual_note", "source_ref": "",
        "field": "merge_event", "value": f"Merged into {args.surviving_id}",
        "confidence": "confirmed", "sensitivity": "standard", "reviewer_status": "confirmed",
        "superseded_by": "", "rationale": getattr(args, "reason", "") or "", "meeting_ref": "",
        "created_by": _default_user(),
    })
    write_evidence(evidence)

    print(f"Merged {args.losing_id} into {args.surviving_id}. {args.losing_id}'s evidence and alias history remain "
          f"on file under its original contact_id; resolve_canonical() will now resolve it to {args.surviving_id}.")


def cmd_archive(args):
    contacts = read_contacts()
    for r in contacts:
        if r["contact_id"] == args.contact_id:
            r["status"] = "archived"
            r["updated_at"] = _now_iso()
            r["updated_by"] = _default_user()
            write_contacts(contacts)
            print(f"Archived {args.contact_id}.")
            return
    print(f"No contact found with contact_id '{args.contact_id}'.")


def cmd_summary(args):
    contacts = read_contacts()
    evidence = read_evidence()
    aliases = read_aliases()
    summary = compute_profile_summary(args.contact_id, contacts, evidence, aliases)
    print(summary["text"])

    if args.save:
        for r in contacts:
            if r["contact_id"] == args.contact_id:
                r["summary"] = summary["text"]
                r["summary_updated_at"] = _now_iso()
                break
        write_contacts(contacts)
        print(f"\nSaved to contacts.csv's 'summary' column for {args.contact_id}.")


def cmd_list(args):
    contacts = read_contacts()
    if args.status:
        contacts = [r for r in contacts if r.get("status") == args.status]
    if args.company:
        contacts = [r for r in contacts if normalize_name(r.get("company", "")) == normalize_name(args.company)]
    if args.vendor:
        contacts = [r for r in contacts if r.get("vendor") == args.vendor]
    if not contacts:
        print("No contacts match.")
        return
    for r in contacts:
        print(f"{r['contact_id']}  [{r.get('status')}]  {r.get('canonical_name')}"
              f"  —  {r.get('title') or '(no title)'} @ {r.get('company') or '(no company)'}"
              f"  —  owner: {r.get('relationship_owner') or '?'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("find-or-create")
    p.add_argument("--name", required=True)
    p.add_argument("--company", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--email", default=None)
    p.add_argument("--vendor", default=None)
    p.add_argument("--visibility", default=None)
    p.set_defaults(func=cmd_find_or_create)

    p = sub.add_parser("create")
    p.add_argument("--name", required=True)
    p.add_argument("--title", default=None)
    p.add_argument("--company", default=None)
    p.add_argument("--email", default=None)
    p.add_argument("--affiliation", default=None, choices=sorted(VALID_AFFILIATION - {""}))
    p.add_argument("--vendor", default=None)
    p.add_argument("--visibility", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("edit")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    for field in EDITABLE_FIELDS:
        p.add_argument(f"--{field.replace('_', '-')}", default=None, dest=field)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("confirm")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--canonical-name", default=None, dest="canonical_name")
    p.set_defaults(func=cmd_confirm)

    p = sub.add_parser("set-canonical-name")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_set_canonical_name)

    p = sub.add_parser("add-alias")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--alias", required=True)
    p.add_argument("--alias-type", required=True, dest="alias_type", choices=sorted(VALID_ALIAS_TYPE))
    p.add_argument("--source-evidence-id", default=None, dest="source_evidence_id")
    p.set_defaults(func=cmd_add_alias)

    p = sub.add_parser("add-evidence")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--field", required=True)
    p.add_argument("--value", required=True)
    p.add_argument("--source-type", required=True, dest="source_type", choices=sorted(VALID_SOURCE_TYPE))
    p.add_argument("--source-ref", default=None, dest="source_ref")
    p.add_argument("--confidence", required=True, choices=sorted(VALID_CONFIDENCE))
    p.add_argument("--sensitivity", default="standard", choices=sorted(VALID_SENSITIVITY))
    p.add_argument("--rationale", default=None)
    p.add_argument("--meeting-ref", default=None, dest="meeting_ref")
    p.add_argument("--extracted-at", default=None, dest="extracted_at")
    p.set_defaults(func=cmd_add_evidence)

    p = sub.add_parser("resolve-match")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--matched-contact-id", required=True, dest="matched_contact_id")
    p.add_argument("--verdict", required=True, choices=["same", "different"])
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_resolve_match)

    p = sub.add_parser("merge")
    p.add_argument("--losing-id", required=True, dest="losing_id")
    p.add_argument("--surviving-id", required=True, dest="surviving_id")
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("archive")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("summary")
    p.add_argument("--contact-id", required=True, dest="contact_id")
    p.add_argument("--save", action="store_true", help="Also write the summary text to contacts.csv's summary column.")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("list")
    p.add_argument("--status", default=None, choices=sorted(VALID_STATUS))
    p.add_argument("--company", default=None)
    p.add_argument("--vendor", default=None)
    p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
