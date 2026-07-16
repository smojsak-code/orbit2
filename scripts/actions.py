#!/usr/bin/env python3
"""
Orbit2 Actions & Commitments register (R1-T05) — follow-ups arising from
activities, meetings, performance gaps and support requests.

Storage: data/actions.csv (plain CSV — unlike the Partner Value Journal,
every field here is a single scalar value, so there's no need for JSONL's
nested-field support).

Commands:
  create    Add a new action. --description is the only required field —
            everything else (owner, due date, priority, links) can be added
            later with `edit` against the same action_id.
  edit      Update non-terminal fields on an existing action by --action-id.
            Only the fields you pass change. Also the only way to move a
            non-terminal action between 'open' and 'blocked' — terminal
            transitions (completed/cancelled) must go through their own
            commands so their side effects (timestamps, required note)
            always happen.
  complete  Mark an action completed. Requires --completion-note or
            --completion-evidence when the action was created with
            --evidence-required. Never deletes the row, never touches
            due_date (see acceptance criteria: completed actions retain
            their original due date and gain a completion timestamp).
  cancel    Mark an action cancelled. --reason is required.
  defer     Push an action's due date out. The action's very first due date
            is captured once at creation in 'original_due_date' and is never
            overwritten by defer, so there's always an audit trail of the
            original commitment even after any number of deferrals.
  list      List actions with optional filters (owner/status/due-period/
            vendor/priority), newest-due-first, showing calculated
            overdue/due-soon badges.

Overdue / due-soon are NOT stored fields — they're calculated fresh every
time from due_date compared to "today" in the Europe/London timezone
specifically (per R1-T05's acceptance criteria: "Overdue and due-soon states
are calculated consistently from Europe/London dates"), regardless of what
data/app_config.json's own timezone setting happens to be set to. See
is_overdue()/is_due_soon() below — also used by scripts/build_dashboard.py
and scripts/build_web.py when building the snapshot the dashboard renders.

Every command prints what it did. Run scripts/validate_data.py afterwards to
check for broken references or status-consistency violations.
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    LONDON = ZoneInfo("Europe/London")
except Exception:  # pragma: no cover - py<3.9 fallback, not expected here
    LONDON = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACTIONS_PATH = os.path.join(DATA_DIR, "actions.csv")
ACTION_STATUSES_PATH = os.path.join(DATA_DIR, "action_statuses.json")

FIELDNAMES = [
    "action_id", "description", "owner",
    "source_activity", "related_metric", "related_opportunity",
    "due_date", "original_due_date", "priority", "expected_impact", "dependency",
    "evidence_required", "status",
    "completion_note", "completion_evidence", "completed_at",
    "cancelled_reason", "cancelled_at",
    "deferred_reason", "deferred_at",
    "vendor", "visibility",
    "created_at", "updated_at", "created_by", "updated_by", "notes",
    "source_request_id",
]

VALID_STATUS = {"open", "blocked", "deferred", "completed", "cancelled"}
TERMINAL_STATUSES = {"completed", "cancelled"}
# Statuses settable directly through `edit` — terminal states must go through
# complete/cancel so their required side effects (timestamp, reason/note)
# always happen. 'deferred' is also excluded from direct edit for the same
# reason — use the `defer` command so original_due_date is preserved.
EDITABLE_STATUSES = {"open", "blocked"}
VALID_PRIORITY = {"low", "medium", "high", "critical"}
DUE_SOON_WINDOW_DAYS = 7

DEFAULT_USER = "Steve Mojsak"
DEFAULT_VENDOR = "Atlassian"


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


def today_london():
    """'Today' in Europe/London, independent of app_config.json's configured
    timezone — see module docstring for why this is hardcoded rather than
    read from config."""
    if LONDON is not None:
        return datetime.now(LONDON).date()
    return datetime.now().date()  # fallback if zoneinfo's tz database is unavailable


def period_start(period, today=None):
    """Start date (inclusive) of the given rolling period — 'week' (Monday of
    the current week), 'month', 'quarter', or 'year' (all calendar-based, not
    a rolling N-day window). Shared by build_web.py's homepage aggregation
    (R1-T06) and impact.py's My Impact aggregation (R1-T07) so the period
    selector means exactly the same thing everywhere it appears."""
    today = today or today_london()
    if period == "week":
        return today - timedelta(days=today.weekday())  # Monday of this week
    if period == "month":
        return today.replace(day=1)
    if period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return today.replace(month=q_start_month, day=1)
    if period == "year":
        return today.replace(month=1, day=1)
    raise ValueError(f"unknown period: {period}")


def is_overdue(row, today=None):
    """True if this action's due date has passed and it's still in a
    non-terminal, non-deferred-away state. Deferred actions are judged
    against their new due_date like any other open action — being deferred
    doesn't itself mean overdue."""
    if row.get("status") in TERMINAL_STATUSES:
        return False
    due = (row.get("due_date") or "").strip()
    if not due:
        return False
    today = today or today_london()
    try:
        due_date = datetime.strptime(due, "%Y-%m-%d").date()
    except ValueError:
        return False
    return due_date < today


def is_due_soon(row, today=None, window_days=DUE_SOON_WINDOW_DAYS):
    """True if due within the next `window_days` (inclusive of today) and
    not already overdue or terminal."""
    if row.get("status") in TERMINAL_STATUSES:
        return False
    due = (row.get("due_date") or "").strip()
    if not due:
        return False
    today = today or today_london()
    try:
        due_date = datetime.strptime(due, "%Y-%m-%d").date()
    except ValueError:
        return False
    if due_date < today:
        return False  # overdue, not "due soon"
    return due_date <= today + timedelta(days=window_days)


def read_actions():
    if not os.path.exists(ACTIONS_PATH):
        return []
    with open(ACTIONS_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_actions(rows):
    with open(ACTIONS_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDNAMES})


def next_id(rows):
    nums = []
    for r in rows:
        aid = r.get("action_id", "")
        if aid.startswith("ACTN-"):
            try:
                nums.append(int(aid[5:]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"ACTN-{n:04d}"


def create_from_fields(fields, rows, source_activity=None, source_request_id=None):
    """Build a fully-formed action row dict from a plain dict of field values
    (already using canonical field names). Shared by cmd_create's CLI path,
    journal.py's opt-in linked-action creation (R1-T05 instruction #31:
    'automatic action generation only when explicitly selected during
    activity capture'), and the standalone "Add Action" change-request path
    (R1-T06) so all three produce identical, fully-validated rows. Does not
    write to disk — caller owns read_actions()/write_actions().

    source_request_id lets a standalone action_create change request be
    de-duplicated the same way activity_create requests are against
    value_journal.jsonl — see journal.py's _import_one_request()."""
    now = datetime.now().isoformat(timespec="seconds")
    user = _default_user()
    due_date = (fields.get("due_date") or "").strip()
    row = {
        "action_id": next_id(rows),
        "description": fields["description"],
        "owner": fields.get("owner") or user,
        "source_activity": source_activity or fields.get("source_activity") or "",
        "related_metric": fields.get("related_metric") or "",
        "related_opportunity": fields.get("related_opportunity") or "",
        "due_date": due_date,
        "original_due_date": due_date,
        "priority": fields.get("priority") or "medium",
        "expected_impact": fields.get("expected_impact") or "",
        "dependency": fields.get("dependency") or "",
        "evidence_required": "true" if fields.get("evidence_required") else "false",
        "status": "open",
        "completion_note": "",
        "completion_evidence": "",
        "completed_at": "",
        "cancelled_reason": "",
        "cancelled_at": "",
        "deferred_reason": "",
        "deferred_at": "",
        "vendor": fields.get("vendor") or _default_vendor(),
        "visibility": fields.get("visibility") or "personal_only",
        "created_at": now,
        "updated_at": now,
        "created_by": user,
        "updated_by": user,
        "notes": fields.get("notes") or "",
        "source_request_id": source_request_id or fields.get("source_request_id") or "",
    }
    return row


def cmd_create(args):
    rows = read_actions()
    fields = {
        "description": args.description, "owner": args.owner,
        "source_activity": args.source_activity, "related_metric": args.related_metric,
        "related_opportunity": args.related_opportunity, "due_date": args.due_date,
        "priority": args.priority, "expected_impact": args.expected_impact,
        "dependency": args.dependency, "evidence_required": args.evidence_required,
        "vendor": args.vendor, "visibility": args.visibility, "notes": args.notes,
    }
    row = create_from_fields(fields, rows)
    rows.append(row)
    write_actions(rows)
    print(f"Created {row['action_id']}: {row['description']} (owner: {row['owner']}, "
          f"due: {row['due_date'] or 'no due date'}, priority: {row['priority']})")


def _find(rows, action_id):
    for r in rows:
        if r.get("action_id") == action_id:
            return r
    return None


def cmd_edit(args):
    rows = read_actions()
    row = _find(rows, args.action_id)
    if not row:
        print(f"No action found with action_id '{args.action_id}'.")
        return

    if args.status is not None:
        if args.status not in EDITABLE_STATUSES:
            print(f"Cannot set status to '{args.status}' via edit — use complete/cancel/defer "
                  f"for terminal or deferred transitions. Editable statuses: {sorted(EDITABLE_STATUSES)}.")
            return

    field_map = {
        "description": args.description, "owner": args.owner,
        "source_activity": args.source_activity, "related_metric": args.related_metric,
        "related_opportunity": args.related_opportunity, "due_date": args.due_date,
        "priority": args.priority, "expected_impact": args.expected_impact,
        "dependency": args.dependency, "vendor": args.vendor,
        "visibility": args.visibility, "notes": args.notes, "status": args.status,
    }
    changed = []
    for field, value in field_map.items():
        if value is not None:
            row[field] = value
            changed.append(field)
    if args.evidence_required is not None:
        row["evidence_required"] = "true" if args.evidence_required else "false"
        changed.append("evidence_required")

    if not changed:
        print("No fields provided to change — nothing done.")
        return

    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_actions(rows)
    print(f"Updated {args.action_id}: {', '.join(changed)}")


def cmd_complete(args):
    rows = read_actions()
    row = _find(rows, args.action_id)
    if not row:
        print(f"No action found with action_id '{args.action_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.action_id} is already {row['status']} — nothing to do.")
        return

    evidence_required = (row.get("evidence_required") or "").strip().lower() == "true"
    if evidence_required and not (args.completion_note or args.completion_evidence):
        print(f"{args.action_id} was created with --evidence-required — a completion note or "
              f"completion evidence reference is required to complete it. Refusing.")
        sys.exit(1)

    now = datetime.now().isoformat(timespec="seconds")
    row["status"] = "completed"
    row["completed_at"] = now
    row["completion_note"] = args.completion_note or row.get("completion_note") or ""
    row["completion_evidence"] = args.completion_evidence or row.get("completion_evidence") or ""
    # due_date is deliberately left untouched — acceptance criteria requires
    # completed actions to retain their original due date.
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_actions(rows)
    print(f"Completed {args.action_id}: {row['description']} (due date retained: "
          f"{row['due_date'] or 'none set'})")


def cmd_cancel(args):
    rows = read_actions()
    row = _find(rows, args.action_id)
    if not row:
        print(f"No action found with action_id '{args.action_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.action_id} is already {row['status']} — nothing to do.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    row["status"] = "cancelled"
    row["cancelled_at"] = now
    row["cancelled_reason"] = args.reason
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_actions(rows)
    print(f"Cancelled {args.action_id} (reason: {args.reason}). It remains in the file for audit history.")


def cmd_defer(args):
    rows = read_actions()
    row = _find(rows, args.action_id)
    if not row:
        print(f"No action found with action_id '{args.action_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.action_id} is already {row['status']} — cannot defer a completed/cancelled action.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    if not row.get("original_due_date"):
        row["original_due_date"] = row.get("due_date") or ""
    row["due_date"] = args.new_due_date
    row["status"] = "deferred"
    row["deferred_at"] = now
    row["deferred_reason"] = args.reason or ""
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_actions(rows)
    print(f"Deferred {args.action_id} to {args.new_due_date} "
          f"(original due date preserved: {row['original_due_date'] or 'none was set'}).")


def _due_period_matches(row, period, today=None):
    if not period or period == "all":
        return True
    today = today or today_london()
    if period == "overdue":
        return is_overdue(row, today)
    if period == "due_soon":
        return is_due_soon(row, today)
    due = (row.get("due_date") or "").strip()
    if not due:
        return False
    try:
        due_date = datetime.strptime(due, "%Y-%m-%d").date()
    except ValueError:
        return False
    if period == "this_week":
        return today <= due_date <= today + timedelta(days=7)
    if period == "this_month":
        return today.year == due_date.year and today.month == due_date.month
    return True


def _matches_filters(row, args, today=None):
    if args.status and args.status != "all":
        if args.status == "open_all":
            if row.get("status") in TERMINAL_STATUSES:
                return False
        elif row.get("status") != args.status:
            return False
    if args.owner and args.owner.lower() not in (row.get("owner") or "").lower():
        return False
    if args.vendor and row.get("vendor") != args.vendor:
        return False
    if args.priority and row.get("priority") != args.priority:
        return False
    if not _due_period_matches(row, args.due_period, today):
        return False
    return True


def cmd_list(args):
    rows = read_actions()
    today = today_london()
    filtered = [r for r in rows if _matches_filters(r, args, today)]
    filtered.sort(key=lambda r: r.get("due_date") or "9999-99-99")
    if not filtered:
        print("No actions match those filters.")
        return
    for r in filtered:
        badges = []
        if is_overdue(r, today):
            badges.append("OVERDUE")
        elif is_due_soon(r, today):
            badges.append("due soon")
        badge_str = f" [{', '.join(badges)}]" if badges else ""
        print(f"{r['action_id']}  due:{r.get('due_date') or '—'}  "
              f"[{r.get('priority','?')}] [{r.get('status','?')}]{badge_str}  "
              f"{r.get('description','?')}  (owner: {r.get('owner','?')})")
        if args.verbose:
            if r.get("source_activity"):
                print(f"    source activity: {r['source_activity']}")
            if r.get("dependency"):
                print(f"    dependency: {r['dependency']}")
            if r.get("notes"):
                print(f"    notes: {r['notes']}")
    print(f"\n{len(filtered)} of {len(rows)} action(s) shown (as of {today.isoformat()}, Europe/London).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--description", required=True)
    p.add_argument("--owner", default=None, help="defaults to app_config.json's user_display_name")
    p.add_argument("--due-date", default=None, dest="due_date", help="YYYY-MM-DD, optional")
    p.add_argument("--priority", default="medium", choices=sorted(VALID_PRIORITY))
    p.add_argument("--source-activity", default=None, dest="source_activity", help="ACT-xxxx, optional")
    p.add_argument("--related-metric", default=None, dest="related_metric", help="MET-xxxx, optional")
    p.add_argument("--related-opportunity", default=None, dest="related_opportunity",
                   help="reserved — no opportunities register exists until R3-T03, free text for now")
    p.add_argument("--expected-impact", default=None, dest="expected_impact")
    p.add_argument("--dependency", default=None)
    p.add_argument("--evidence-required", action="store_true", dest="evidence_required",
                   help="if set, `complete` will refuse without a completion note or evidence reference")
    p.add_argument("--vendor", default=None, help="defaults to app_config.json's default_vendor")
    p.add_argument("--visibility", default=None, choices=[
        "personal_only", "communardo_internal", "communardo_management",
        "atlassian_shareable", "customer_approved", "anonymised", "public",
    ])
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("edit")
    p.add_argument("--action-id", required=True, dest="action_id")
    p.add_argument("--description", default=None)
    p.add_argument("--owner", default=None)
    p.add_argument("--source-activity", default=None, dest="source_activity")
    p.add_argument("--related-metric", default=None, dest="related_metric")
    p.add_argument("--related-opportunity", default=None, dest="related_opportunity")
    p.add_argument("--due-date", default=None, dest="due_date")
    p.add_argument("--priority", default=None, choices=sorted(VALID_PRIORITY))
    p.add_argument("--expected-impact", default=None, dest="expected_impact")
    p.add_argument("--dependency", default=None)
    p.add_argument("--evidence-required", type=lambda v: v.lower() == "true", default=None, dest="evidence_required")
    p.add_argument("--vendor", default=None)
    p.add_argument("--visibility", default=None, choices=[
        "personal_only", "communardo_internal", "communardo_management",
        "atlassian_shareable", "customer_approved", "anonymised", "public",
    ])
    p.add_argument("--status", default=None, choices=sorted(EDITABLE_STATUSES),
                   help="only open/blocked — use complete/cancel/defer for other transitions")
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("complete")
    p.add_argument("--action-id", required=True, dest="action_id")
    p.add_argument("--completion-note", default=None, dest="completion_note")
    p.add_argument("--completion-evidence", default=None, dest="completion_evidence", help="EVD-xxxx or free text")
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser("cancel")
    p.add_argument("--action-id", required=True, dest="action_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_cancel)

    p = sub.add_parser("defer")
    p.add_argument("--action-id", required=True, dest="action_id")
    p.add_argument("--new-due-date", required=True, dest="new_due_date", help="YYYY-MM-DD")
    p.add_argument("--reason", default=None)
    p.set_defaults(func=cmd_defer)

    p = sub.add_parser("list")
    p.add_argument("--status", default="open_all",
                   help="open_all (default: any non-terminal status), open, blocked, deferred, completed, cancelled, or all")
    p.add_argument("--owner", default=None)
    p.add_argument("--vendor", default=None)
    p.add_argument("--priority", default=None, choices=sorted(VALID_PRIORITY))
    p.add_argument("--due-period", default="all", dest="due_period",
                   choices=["all", "overdue", "due_soon", "this_week", "this_month"])
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
