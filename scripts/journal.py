#!/usr/bin/env python3
"""
Orbit2 Partner Value Journal — the central chronological record of alliance
activities and what came of them.

Storage: data/value_journal.jsonl (JSON Lines — one JSON object per line, the
explicit alternative the roadmap allows to a CSV for this register, chosen
here because journal entries have genuinely nested/multi-value fields
(participants, metric_links, opportunity_links, evidence_links, value) that
would need fragile in-cell encoding in a CSV. See docs/data_dictionary.md,
"Partner Value Journal", for the full field reference and for the difference
between activity / outcome / contribution / value.

Commands:
  create    Add a new journal entry. Only --date, --type, --title and
            --outcome are required — everything else can be added later
            with `edit` against the same activity_id (never a duplicate row).
  edit      Update one or more fields on an existing entry by --activity-id.
            Only the fields you pass change; everything else is preserved.
  archive   Mark an entry archived (never deletes it — see acceptance
            criteria: archived entries stay available for reporting/audit).
  list      List entries with optional filters, newest first.
  export    Write filtered entries to a file (or stdout) as JSON or CSV.

Every command prints what it did. Run scripts/validate_data.py afterwards to
check for broken references or value-field violations.
"""
import argparse
import csv as csvmod
import json
import os
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
JOURNAL_PATH = os.path.join(DATA_DIR, "value_journal.jsonl")
ACTIVITY_TYPES_PATH = os.path.join(DATA_DIR, "activity_types.json")
CONTRIBUTION_TYPES_PATH = os.path.join(DATA_DIR, "contribution_types.json")

VALID_VISIBILITY = {
    "personal_only", "communardo_internal", "communardo_management",
    "atlassian_shareable", "customer_approved", "anonymised", "public",
}
VALID_VALUE_STATUS = {"confirmed", "estimated", "protected", "potential"}
VALID_RECOGNITION_STATUS = {"unrecognised", "logged", "shared", "acknowledged"}
VALID_STATUS = {"active", "archived"}
VALID_SOURCE_TYPE = {"manual", "import", "evidence_extraction", "calculated", "migrated"}
VALID_CONFIDENCE = {"confirmed", "supported", "estimated", "unverified"}

DEFAULT_USER = "Steve Mojsak"  # falls back to data/app_config.json's user_display_name if present


def _default_user():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import config as app_config
        return app_config.load_config().get("user_display_name") or DEFAULT_USER
    except Exception:
        return DEFAULT_USER


def load_controlled_list(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    return data.get("types", {})


def read_journal():
    if not os.path.exists(JOURNAL_PATH):
        return []
    entries = []
    with open(JOURNAL_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def write_journal(entries):
    with open(JOURNAL_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True) + "\n")


def next_id(entries):
    nums = []
    for e in entries:
        aid = e.get("activity_id", "")
        if aid.startswith("ACT-"):
            try:
                nums.append(int(aid[4:]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"ACT-{n:04d}"


def _split_list_arg(value):
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def cmd_create(args):
    entries = read_journal()

    activity_types = load_controlled_list(ACTIVITY_TYPES_PATH)
    if args.type not in activity_types:
        print(f"WARNING: type '{args.type}' is not in data/activity_types.json — allowed anyway, "
              f"but consider using 'other' with a note, or add it to the controlled list.")

    now = datetime.now().isoformat(timespec="seconds")
    user = _default_user()

    entry = {
        "activity_id": next_id(entries),
        "date": args.date,
        "type": args.type,
        "title": args.title,
        "description": args.description or "",
        "participants": _split_list_arg(args.participants),
        "organisation": args.organisation or "",
        "customer_account": args.customer_account or "",
        "contribution_type": args.contribution_type or "",
        "outcome": args.outcome,
        "next_action": args.next_action or "",
        "metric_links": _split_list_arg(args.metric_links),
        "opportunity_links": _split_list_arg(args.opportunity_links),
        "evidence_links": _split_list_arg(args.evidence_links),
        "value": {
            "amount": args.value_amount,
            "currency": args.value_currency or None,
            "status": args.value_status or None,
        },
        "recognition_status": args.recognition_status or "unrecognised",
        "visibility": args.visibility or "personal_only",
        "status": "active",
        "archived_at": None,
        "archived_reason": None,
        "created_at": now,
        "updated_at": now,
        "created_by": user,
        "updated_by": user,
        "source_type": args.source_type or "manual",
        "confidence": args.confidence or "confirmed",
        "notes": args.notes or "",
    }
    entries.append(entry)
    write_journal(entries)
    print(f"Created {entry['activity_id']}: [{entry['type']}] {entry['title']} ({entry['date']})")
    print("Add more detail any time with: python3 scripts/journal.py edit --activity-id "
          f"{entry['activity_id']} --description \"...\" ...")


def cmd_edit(args):
    entries = read_journal()
    found = None
    for e in entries:
        if e["activity_id"] == args.activity_id:
            found = e
            break
    if not found:
        print(f"No journal entry found with activity_id '{args.activity_id}'.")
        return

    field_map = {
        "date": args.date, "type": args.type, "title": args.title,
        "description": args.description, "organisation": args.organisation,
        "customer_account": args.customer_account, "contribution_type": args.contribution_type,
        "outcome": args.outcome, "next_action": args.next_action,
        "recognition_status": args.recognition_status, "visibility": args.visibility,
        "source_type": args.source_type, "confidence": args.confidence, "notes": args.notes,
    }
    changed = []
    for field, value in field_map.items():
        if value is not None:
            found[field] = value
            changed.append(field)

    if args.participants is not None:
        found["participants"] = _split_list_arg(args.participants)
        changed.append("participants")
    if args.metric_links is not None:
        found["metric_links"] = _split_list_arg(args.metric_links)
        changed.append("metric_links")
    if args.opportunity_links is not None:
        found["opportunity_links"] = _split_list_arg(args.opportunity_links)
        changed.append("opportunity_links")
    if args.evidence_links is not None:
        found["evidence_links"] = _split_list_arg(args.evidence_links)
        changed.append("evidence_links")

    if args.value_amount is not None:
        found.setdefault("value", {})["amount"] = args.value_amount
        changed.append("value.amount")
    if args.value_currency is not None:
        found.setdefault("value", {})["currency"] = args.value_currency
        changed.append("value.currency")
    if args.value_status is not None:
        found.setdefault("value", {})["status"] = args.value_status
        changed.append("value.status")

    if not changed:
        print("No fields provided to change — nothing done.")
        return

    found["updated_at"] = datetime.now().isoformat(timespec="seconds")
    found["updated_by"] = _default_user()
    write_journal(entries)
    print(f"Updated {args.activity_id}: {', '.join(changed)}")


def cmd_archive(args):
    entries = read_journal()
    found = None
    for e in entries:
        if e["activity_id"] == args.activity_id:
            found = e
            break
    if not found:
        print(f"No journal entry found with activity_id '{args.activity_id}'.")
        return
    if found["status"] == "archived":
        print(f"{args.activity_id} is already archived (reason: {found.get('archived_reason')}).")
        return
    found["status"] = "archived"
    found["archived_at"] = datetime.now().isoformat(timespec="seconds")
    found["archived_reason"] = args.reason
    found["updated_at"] = found["archived_at"]
    found["updated_by"] = _default_user()
    write_journal(entries)
    print(f"Archived {args.activity_id} (reason: {args.reason}). It remains in the file and "
          "available for reporting/audit history — archiving never deletes.")


def _matches_filters(e, args):
    if args.status and args.status != "all" and e.get("status") != args.status:
        return False
    if args.type and e.get("type") != args.type:
        return False
    if args.organisation and args.organisation.lower() not in (e.get("organisation") or "").lower():
        return False
    if args.from_date and (e.get("date") or "") < args.from_date:
        return False
    if args.to_date and (e.get("date") or "") > args.to_date:
        return False
    return True


def cmd_list(args):
    entries = read_journal()
    filtered = [e for e in entries if _matches_filters(e, args)]
    filtered.sort(key=lambda e: e.get("date", ""), reverse=True)
    if not filtered:
        print("No journal entries match those filters.")
        return
    for e in filtered:
        value = e.get("value") or {}
        value_str = ""
        if value.get("amount"):
            value_str = f" · {value['amount']} {value.get('currency') or '?'} ({value.get('status') or 'unlabelled'})"
        print(f"{e['activity_id']}  {e.get('date','?')}  [{e.get('type','?')}]  "
              f"{e.get('title','?')}  ({e.get('status','?')}){value_str}")
        if args.verbose:
            print(f"    outcome: {e.get('outcome','')}")
            if e.get("next_action"):
                print(f"    next action: {e.get('next_action')}")


def cmd_export(args):
    entries = read_journal()
    filtered = [e for e in entries if _matches_filters(e, args)]
    filtered.sort(key=lambda e: e.get("date", ""), reverse=True)

    if args.format == "json":
        out = json.dumps(filtered, indent=2)
    else:  # csv — flatten nested fields to make it spreadsheet-friendly
        fieldnames = [
            "activity_id", "date", "type", "title", "description", "participants",
            "organisation", "customer_account", "contribution_type", "outcome", "next_action",
            "metric_links", "opportunity_links", "evidence_links",
            "value_amount", "value_currency", "value_status",
            "recognition_status", "visibility", "status", "archived_at", "archived_reason",
            "created_at", "updated_at", "created_by", "updated_by",
            "source_type", "confidence", "notes",
        ]
        import io
        buf = io.StringIO()
        w = csvmod.DictWriter(buf, fieldnames=fieldnames)
        w.writeheader()
        for e in filtered:
            value = e.get("value") or {}
            row = {k: e.get(k, "") for k in fieldnames if k in e}
            row["participants"] = ";".join(e.get("participants") or [])
            row["metric_links"] = ";".join(e.get("metric_links") or [])
            row["opportunity_links"] = ";".join(e.get("opportunity_links") or [])
            row["evidence_links"] = ";".join(e.get("evidence_links") or [])
            row["value_amount"] = value.get("amount", "")
            row["value_currency"] = value.get("currency", "")
            row["value_status"] = value.get("status", "")
            w.writerow(row)
        out = buf.getvalue()

    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
        print(f"Wrote {len(filtered)} entries to {args.output}")
    else:
        print(out)


def _add_filter_args(p):
    p.add_argument("--status", default="active", help="active (default), archived, or all")
    p.add_argument("--type", default=None)
    p.add_argument("--organisation", default=None)
    p.add_argument("--from-date", default=None, dest="from_date")
    p.add_argument("--to-date", default=None, dest="to_date")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--type", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--outcome", required=True)
    p.add_argument("--description", default=None)
    p.add_argument("--participants", default=None, help="comma-separated names")
    p.add_argument("--organisation", default=None)
    p.add_argument("--customer-account", default=None, dest="customer_account")
    p.add_argument("--contribution-type", default=None, dest="contribution_type")
    p.add_argument("--next-action", default=None, dest="next_action")
    p.add_argument("--metric-links", default=None, dest="metric_links", help="comma-separated record_id (MET-xxxx)")
    p.add_argument("--opportunity-links", default=None, dest="opportunity_links", help="comma-separated (register doesn't exist until R3-T03 — free text ID for now)")
    p.add_argument("--evidence-links", default=None, dest="evidence_links", help="comma-separated evidence_id (EVD-xxxx)")
    p.add_argument("--value-amount", type=float, default=None, dest="value_amount")
    p.add_argument("--value-currency", default=None, dest="value_currency")
    p.add_argument("--value-status", default=None, dest="value_status", choices=sorted(VALID_VALUE_STATUS))
    p.add_argument("--recognition-status", default=None, dest="recognition_status", choices=sorted(VALID_RECOGNITION_STATUS))
    p.add_argument("--visibility", default=None, choices=sorted(VALID_VISIBILITY))
    p.add_argument("--source-type", default=None, dest="source_type", choices=sorted(VALID_SOURCE_TYPE))
    p.add_argument("--confidence", default=None, choices=sorted(VALID_CONFIDENCE))
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("edit")
    p.add_argument("--activity-id", required=True, dest="activity_id")
    p.add_argument("--date", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--outcome", default=None)
    p.add_argument("--description", default=None)
    p.add_argument("--participants", default=None)
    p.add_argument("--organisation", default=None)
    p.add_argument("--customer-account", default=None, dest="customer_account")
    p.add_argument("--contribution-type", default=None, dest="contribution_type")
    p.add_argument("--next-action", default=None, dest="next_action")
    p.add_argument("--metric-links", default=None, dest="metric_links")
    p.add_argument("--opportunity-links", default=None, dest="opportunity_links")
    p.add_argument("--evidence-links", default=None, dest="evidence_links")
    p.add_argument("--value-amount", type=float, default=None, dest="value_amount")
    p.add_argument("--value-currency", default=None, dest="value_currency")
    p.add_argument("--value-status", default=None, dest="value_status", choices=sorted(VALID_VALUE_STATUS))
    p.add_argument("--recognition-status", default=None, dest="recognition_status", choices=sorted(VALID_RECOGNITION_STATUS))
    p.add_argument("--visibility", default=None, choices=sorted(VALID_VISIBILITY))
    p.add_argument("--source-type", default=None, dest="source_type", choices=sorted(VALID_SOURCE_TYPE))
    p.add_argument("--confidence", default=None, choices=sorted(VALID_CONFIDENCE))
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("archive")
    p.add_argument("--activity-id", required=True, dest="activity_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("list")
    _add_filter_args(p)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("export")
    _add_filter_args(p)
    p.add_argument("--format", choices=["json", "csv"], default="json")
    p.add_argument("--output", default=None, help="file path; omit to print to stdout")
    p.set_defaults(func=cmd_export)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
