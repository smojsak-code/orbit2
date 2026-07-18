#!/usr/bin/env python3
"""
Orbit2 Objectives register (R1-T08) — connects daily activity to quarterly
and annual role objectives.

Storage: data/objectives.csv (plain CSV — every field here is a scalar or a
semicolon-separated list of IDs, so there's no need for JSONL's nested-field
support; semicolons rather than commas because Communardo/Atlassian names in
free-text fields elsewhere in this project already use commas).

Commands:
  create        Add a new objective. --objective, --period, and
                --progress-method are required — everything else can be
                added later with `edit`.
  edit          Update non-terminal fields by --objective-id. Cannot set
                status directly — terminal/at-risk transitions go through
                their own commands (at-risk / resolve-risk / complete /
                miss) so required side effects (timestamp, reason) always
                happen, same discipline as scripts/actions.py.
  link-activity Attach a value_journal.jsonl activity_id as evidence this
                objective is progressing (also accepted at create/edit time
                via --linked-activities for bulk-setting the whole list).
  link-evidence Attach an evidence_id the same way.
  set-progress  Set the manual progress percentage. Only valid when
                progress_method is 'manual' — calculated methods derive
                their percentage from linked records instead (see
                compute_progress() below).
  at-risk       Mark an objective at risk. --reason and --recovery-action
                are both required (acceptance criterion: "An objective can
                be marked at risk with a reason and recovery action").
  resolve-risk  Move an at-risk objective back to on_track.
  complete      Mark an objective completed (terminal).
  miss          Mark an objective missed (terminal) — for objectives whose
                target_date passed without being met.
  list          List objectives with computed progress, optionally filtered
                by period/status.
  export        Write a deterministic Markdown objective-review file to
                reports/Objective_Review_<period>.md — plain string
                templates over already-computed data, no AI call, matching
                the same discipline as scripts/impact.py's narrative.

Progress is either stored directly (progress_method='manual') or computed
fresh every time from linked records (progress_method='count_linked' or
'sum_linked_value') — see compute_progress(). Either way, the *raw* (possibly
>100%) percentage and the *official* (capped at 100%) percentage are always
both available, so overachievement is never silently hidden (R1-T08
acceptance criterion / instruction #51) — it's on the caller (the CLI's
`list` output, and later the UI) to display both rather than just the
capped figure.

Every command prints what it did. Run scripts/validate_data.py afterwards to
check for broken references or status-consistency violations.
"""
import argparse
import csv
import os
import re
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
OBJECTIVES_PATH = os.path.join(DATA_DIR, "objectives.csv")

FIELDNAMES = [
    "objective_id", "period", "objective", "success_measure",
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

QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")
YEAR_RE = re.compile(r"^\d{4}$")

VALID_STATUS = {"on_track", "at_risk", "completed", "missed"}
TERMINAL_STATUSES = {"completed", "missed"}
# Same discipline as actions.py's EDITABLE_STATUSES: `edit` can only move an
# objective between on_track/at_risk directly; every other transition goes
# through its own command so required side effects always happen. In
# practice at-risk always goes through `at-risk` (reason + recovery action
# are required and `edit` doesn't collect them), so this exists mainly to
# allow `edit --status on_track` as a manual escape hatch distinct from
# `resolve-risk` if ever needed.
EDITABLE_STATUSES = {"on_track", "at_risk"}
VALID_PROGRESS_METHOD = {"manual", "count_linked", "sum_linked_value"}
VALID_PRIORITY = {"", "low", "medium", "high"}

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


def period_type(period):
    """'quarter' or 'year', inferred from the period string's own format
    (e.g. '2026-Q3' vs '2026') rather than a separate stored field — mirrors
    how the category sub-metric CSVs already encode a quarter as a single
    string. Returns None if the format doesn't match either."""
    period = (period or "").strip()
    if QUARTER_RE.match(period):
        return "quarter"
    if YEAR_RE.match(period):
        return "year"
    return None


def split_ids(value):
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def join_ids(values):
    return ";".join(values)


def read_objectives():
    if not os.path.exists(OBJECTIVES_PATH):
        return []
    with open(OBJECTIVES_PATH, newline="") as f:
        return list(csv.DictReader(f))


def write_objectives(rows):
    with open(OBJECTIVES_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in FIELDNAMES})


def next_id(rows):
    nums = []
    for r in rows:
        oid = r.get("objective_id", "")
        if oid.startswith("OBJ-"):
            try:
                nums.append(int(oid[4:]))
            except ValueError:
                pass
    n = (max(nums) + 1) if nums else 1
    return f"OBJ-{n:04d}"


def _find(rows, objective_id):
    for r in rows:
        if r.get("objective_id") == objective_id:
            return r
    return None


def compute_progress(row, journal_by_id=None):
    """Returns {raw_pct, official_pct, overachievement_pct, basis} for one
    objective row.

    - manual: raw_pct is whatever progress_pct was last set to via
      set-progress (0 if never set). The user may enter >100 themselves to
      record genuine overachievement on a manually-tracked objective.
    - count_linked: raw_pct = (number of linked_activities) / target * 100.
      target must parse as a positive number (a count).
    - sum_linked_value: raw_pct = (sum of value.amount across linked
      activities, regardless of value.status) / target * 100. target must
      parse as a positive number (an amount, in whatever currency the
      objective's target_unit says — currency consistency across linked
      entries is not cross-checked here, same as target_unit isn't
      cross-checked against value.currency; keeping this simple was a
      deliberate choice for R1, documented in docs/data_dictionary.md).

    official_pct is always min(100, raw_pct) — the number status/progress
    bars should show. overachievement_pct is always max(0, raw_pct - 100) —
    a separate figure the UI must display alongside, never merge into, the
    official one (R1-T08 acceptance criterion).
    """
    method = (row.get("progress_method") or "manual").strip()
    journal_by_id = journal_by_id or {}
    basis = ""

    if method == "count_linked":
        linked = split_ids(row.get("linked_activities"))
        try:
            target = float(row.get("target") or 0)
        except ValueError:
            target = 0
        raw = (len(linked) / target * 100) if target > 0 else 0
        basis = f"{len(linked)} linked activit{'y' if len(linked) == 1 else 'ies'} / target {row.get('target')}"
    elif method == "sum_linked_value":
        linked = split_ids(row.get("linked_activities"))
        total = 0.0
        for aid in linked:
            entry = journal_by_id.get(aid)
            if entry:
                amount = (entry.get("value") or {}).get("amount")
                if amount:
                    total += float(amount)
        try:
            target = float(row.get("target") or 0)
        except ValueError:
            target = 0
        raw = (total / target * 100) if target > 0 else 0
        basis = f"{total:,.0f} linked value / target {row.get('target')}"
    else:  # manual
        try:
            raw = float(row.get("progress_pct") or 0)
        except ValueError:
            raw = 0
        basis = "manually entered"

    official = max(0.0, min(100.0, raw))
    overachievement = max(0.0, raw - 100.0)
    return {
        "raw_pct": round(raw, 1),
        "official_pct": round(official, 1),
        "overachievement_pct": round(overachievement, 1),
        "basis": basis,
    }


def create_from_fields(fields, rows):
    now = datetime.now().isoformat(timespec="seconds")
    user = _default_user()
    method = fields.get("progress_method") or "manual"
    row = {
        "objective_id": next_id(rows),
        "period": fields["period"],
        "objective": fields["objective"],
        "success_measure": fields.get("success_measure") or "",
        "target": fields.get("target") or "",
        "target_unit": fields.get("target_unit") or "",
        "target_date": fields.get("target_date") or "",
        "communardo_priority": fields.get("communardo_priority") or "",
        "atlassian_priority": fields.get("atlassian_priority") or "",
        "status": "on_track",
        "progress_method": method,
        "progress_pct": str(fields.get("progress_pct") or 0) if method == "manual" else "",
        "linked_activities": join_ids(fields.get("linked_activities") or []),
        "linked_evidence": join_ids(fields.get("linked_evidence") or []),
        "at_risk_reason": "", "recovery_action": "",
        "completed_at": "", "completion_note": "",
        "missed_at": "", "missed_reason": "",
        "vendor": fields.get("vendor") or _default_vendor(),
        "visibility": fields.get("visibility") or "communardo_internal",
        "created_at": now, "updated_at": now,
        "created_by": user, "updated_by": user,
        "notes": fields.get("notes") or "",
    }
    return row


def cmd_create(args):
    if period_type(args.period) is None:
        print(f"--period '{args.period}' doesn't match either a quarter (YYYY-Q1..4) or a year (YYYY). Refusing.")
        sys.exit(1)
    rows = read_objectives()
    fields = {
        "period": args.period, "objective": args.objective,
        "success_measure": args.success_measure, "target": args.target,
        "target_unit": args.target_unit, "target_date": args.target_date,
        "communardo_priority": args.communardo_priority, "atlassian_priority": args.atlassian_priority,
        "progress_method": args.progress_method, "progress_pct": args.progress_pct,
        "linked_activities": args.linked_activities or [], "linked_evidence": args.linked_evidence or [],
        "vendor": args.vendor, "visibility": args.visibility, "notes": args.notes,
    }
    if args.progress_method in ("count_linked", "sum_linked_value") and not args.target:
        print(f"--progress-method {args.progress_method} requires a numeric --target. Refusing.")
        sys.exit(1)
    row = create_from_fields(fields, rows)
    rows.append(row)
    write_objectives(rows)
    print(f"Created {row['objective_id']} ({row['period']}): {row['objective']} "
          f"[{row['progress_method']}, target: {row['target'] or 'n/a'}]")


def cmd_edit(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    if args.status is not None and args.status not in EDITABLE_STATUSES:
        print(f"Cannot set status to '{args.status}' via edit — use at-risk/resolve-risk/complete/miss "
              f"for other transitions. Editable statuses: {sorted(EDITABLE_STATUSES)}.")
        return
    if args.period is not None and period_type(args.period) is None:
        print(f"--period '{args.period}' doesn't match either a quarter (YYYY-Q1..4) or a year (YYYY). Refusing.")
        return

    field_map = {
        "period": args.period, "objective": args.objective,
        "success_measure": args.success_measure, "target": args.target,
        "target_unit": args.target_unit, "target_date": args.target_date,
        "communardo_priority": args.communardo_priority, "atlassian_priority": args.atlassian_priority,
        "progress_method": args.progress_method,
        "vendor": args.vendor, "visibility": args.visibility, "notes": args.notes,
        "status": args.status,
    }
    changed = []
    for field, value in field_map.items():
        if value is not None:
            row[field] = value
            changed.append(field)
    if args.linked_activities is not None:
        row["linked_activities"] = join_ids(args.linked_activities)
        changed.append("linked_activities")
    if args.linked_evidence is not None:
        row["linked_evidence"] = join_ids(args.linked_evidence)
        changed.append("linked_evidence")

    if not changed:
        print("No fields provided to change — nothing done.")
        return
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Updated {args.objective_id}: {', '.join(changed)}")


def cmd_link_activity(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    linked = split_ids(row.get("linked_activities"))
    if args.activity_id in linked:
        print(f"{args.activity_id} is already linked to {args.objective_id} — nothing to do.")
        return
    linked.append(args.activity_id)
    row["linked_activities"] = join_ids(linked)
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Linked {args.activity_id} to {args.objective_id} ({len(linked)} linked activit"
          f"{'y' if len(linked) == 1 else 'ies'} total).")


def cmd_link_evidence(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    linked = split_ids(row.get("linked_evidence"))
    if args.evidence_id in linked:
        print(f"{args.evidence_id} is already linked to {args.objective_id} — nothing to do.")
        return
    linked.append(args.evidence_id)
    row["linked_evidence"] = join_ids(linked)
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Linked {args.evidence_id} to {args.objective_id} ({len(linked)} linked evidence item"
          f"{'s' if len(linked) != 1 else ''} total).")


def cmd_set_progress(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    method = (row.get("progress_method") or "manual").strip()
    if method != "manual":
        print(f"{args.objective_id} uses progress_method '{method}' — progress is calculated from linked "
              f"records, not set manually. Use `link-activity`/`link-evidence` instead, or `edit "
              f"--progress-method manual` first if you want to switch to manual tracking.")
        sys.exit(1)
    row["progress_pct"] = str(args.pct)
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_objectives(rows)
    over = max(0.0, args.pct - 100.0)
    note = f" (official: 100%, overachievement: +{over:.1f}%)" if over > 0 else ""
    print(f"Set {args.objective_id} progress to {args.pct}%{note}.")


def cmd_at_risk(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.objective_id} is already {row['status']} — cannot mark a terminal objective at risk.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    row["status"] = "at_risk"
    row["at_risk_reason"] = args.reason
    row["recovery_action"] = args.recovery_action
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Marked {args.objective_id} at risk (reason: {args.reason}; recovery action: {args.recovery_action}).")


def cmd_resolve_risk(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    if row["status"] != "at_risk":
        print(f"{args.objective_id} is not currently at_risk (status: {row['status']}) — nothing to resolve.")
        return
    row["status"] = "on_track"
    row["updated_at"] = datetime.now().isoformat(timespec="seconds")
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Resolved risk on {args.objective_id} — back to on_track. "
          f"(at_risk_reason/recovery_action are kept on the row for audit history.)")


def cmd_complete(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.objective_id} is already {row['status']} — nothing to do.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    row["status"] = "completed"
    row["completed_at"] = now
    row["completion_note"] = args.completion_note or ""
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_objectives(rows)
    progress = compute_progress(row)
    over_note = f" (overachieved by +{progress['overachievement_pct']}%)" if progress["overachievement_pct"] > 0 else ""
    print(f"Completed {args.objective_id}: {row['objective']}{over_note}")


def cmd_miss(args):
    rows = read_objectives()
    row = _find(rows, args.objective_id)
    if not row:
        print(f"No objective found with objective_id '{args.objective_id}'.")
        return
    if row["status"] in TERMINAL_STATUSES:
        print(f"{args.objective_id} is already {row['status']} — nothing to do.")
        return
    now = datetime.now().isoformat(timespec="seconds")
    row["status"] = "missed"
    row["missed_at"] = now
    row["missed_reason"] = args.reason
    row["updated_at"] = now
    row["updated_by"] = _default_user()
    write_objectives(rows)
    print(f"Marked {args.objective_id} missed (reason: {args.reason}). It remains in the file for audit history.")


def _matches_filters(row, args):
    if args.period and row.get("period") != args.period:
        return False
    if args.status and args.status != "all":
        if args.status == "open_all":
            if row.get("status") in TERMINAL_STATUSES:
                return False
        elif row.get("status") != args.status:
            return False
    if args.vendor and row.get("vendor") != args.vendor:
        return False
    return True


def _load_journal_by_id():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import journal as journal_mod
        return {e.get("activity_id"): e for e in journal_mod.read_journal()}
    except Exception:
        return {}


def cmd_list(args):
    rows = read_objectives()
    filtered = [r for r in rows if _matches_filters(r, args)]
    if not filtered:
        print("No objectives match those filters.")
        return
    journal_by_id = _load_journal_by_id()
    filtered.sort(key=lambda r: (r.get("target_date") or "9999-99-99"))
    for r in filtered:
        p = compute_progress(r, journal_by_id)
        over = f" (+{p['overachievement_pct']}% over)" if p["overachievement_pct"] > 0 else ""
        print(f"{r['objective_id']}  [{r.get('period','?')}]  [{r.get('status','?')}]  "
              f"{p['official_pct']}%{over}  due:{r.get('target_date') or '—'}  {r.get('objective','?')}")
        if args.verbose:
            print(f"    success measure: {r.get('success_measure') or '—'}")
            print(f"    progress basis: {p['basis']}")
            linked_act = split_ids(r.get("linked_activities"))
            if linked_act:
                print(f"    linked activities ({len(linked_act)}): {', '.join(linked_act)}")
            if r.get("status") == "at_risk":
                print(f"    at risk: {r.get('at_risk_reason')} | recovery: {r.get('recovery_action')}")
    print(f"\n{len(filtered)} of {len(rows)} objective(s) shown.")


def cmd_export(args):
    rows = read_objectives()
    filtered = [r for r in rows if not args.period or r.get("period") == args.period]
    if not filtered:
        print(f"No objectives found for period '{args.period or 'all'}' — nothing to export.")
        return
    journal_by_id = _load_journal_by_id()

    label = args.period or "all-periods"
    lines = [f"# Objective Review — {label}", ""]
    lines.append(f"Generated {datetime.now().isoformat(timespec='seconds')} · {len(filtered)} objective(s)")
    lines.append("")
    for r in sorted(filtered, key=lambda r: (r.get("target_date") or "9999-99-99")):
        p = compute_progress(r, journal_by_id)
        lines.append(f"## {r['objective_id']} — {r.get('objective')}")
        lines.append("")
        lines.append(f"- **Period:** {r.get('period')}")
        lines.append(f"- **Status:** {r.get('status')}")
        lines.append(f"- **Success measure:** {r.get('success_measure') or '—'}")
        lines.append(f"- **Target:** {r.get('target') or '—'} {r.get('target_unit') or ''} by {r.get('target_date') or 'no date set'}".rstrip())
        lines.append(f"- **Progress:** {p['official_pct']}% official"
                      + (f", +{p['overachievement_pct']}% overachievement" if p["overachievement_pct"] > 0 else "")
                      + f" ({p['basis']})")
        lines.append(f"- **Communardo priority:** {r.get('communardo_priority') or '—'} · "
                      f"**Atlassian priority:** {r.get('atlassian_priority') or '—'}")
        linked_act = split_ids(r.get("linked_activities"))
        if linked_act:
            lines.append(f"- **Linked activities ({len(linked_act)}):** {', '.join(linked_act)}")
        if r.get("status") == "at_risk":
            lines.append(f"- **At risk:** {r.get('at_risk_reason')}")
            lines.append(f"- **Recovery action:** {r.get('recovery_action')}")
        if r.get("status") == "completed":
            lines.append(f"- **Completed:** {r.get('completed_at')}" + (f" — {r.get('completion_note')}" if r.get("completion_note") else ""))
        if r.get("status") == "missed":
            lines.append(f"- **Missed:** {r.get('missed_at')} — {r.get('missed_reason')}")
        if r.get("notes"):
            lines.append(f"- **Notes:** {r.get('notes')}")
        lines.append("")

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"Objective_Review_{label}.md")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Wrote {out_path} ({len(filtered)} objective(s)).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--objective", required=True)
    p.add_argument("--period", required=True, help="'YYYY-Q1'..'YYYY-Q4' for a quarter objective, or 'YYYY' for a year objective")
    p.add_argument("--success-measure", default=None, dest="success_measure")
    p.add_argument("--target", default=None, help="numeric — required if --progress-method is count_linked or sum_linked_value")
    p.add_argument("--target-unit", default=None, dest="target_unit", help="e.g. 'count', 'GBP', '%'")
    p.add_argument("--target-date", default=None, dest="target_date")
    p.add_argument("--communardo-priority", default=None, dest="communardo_priority", choices=sorted(VALID_PRIORITY))
    p.add_argument("--atlassian-priority", default=None, dest="atlassian_priority", choices=sorted(VALID_PRIORITY))
    p.add_argument("--progress-method", default="manual", dest="progress_method", choices=sorted(VALID_PROGRESS_METHOD))
    p.add_argument("--progress-pct", default=0, dest="progress_pct", type=float, help="only used if --progress-method manual")
    p.add_argument("--linked-activities", default=None, dest="linked_activities", nargs="*", help="ACT-xxxx ids")
    p.add_argument("--linked-evidence", default=None, dest="linked_evidence", nargs="*", help="EVD-xxxx ids")
    p.add_argument("--vendor", default=None)
    p.add_argument("--visibility", default=None, choices=[
        "personal_only", "communardo_internal", "communardo_management",
        "atlassian_shareable", "customer_approved", "anonymised", "public",
    ])
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("edit")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--objective", default=None)
    p.add_argument("--period", default=None)
    p.add_argument("--success-measure", default=None, dest="success_measure")
    p.add_argument("--target", default=None)
    p.add_argument("--target-unit", default=None, dest="target_unit")
    p.add_argument("--target-date", default=None, dest="target_date")
    p.add_argument("--communardo-priority", default=None, dest="communardo_priority", choices=sorted(VALID_PRIORITY))
    p.add_argument("--atlassian-priority", default=None, dest="atlassian_priority", choices=sorted(VALID_PRIORITY))
    p.add_argument("--progress-method", default=None, dest="progress_method", choices=sorted(VALID_PROGRESS_METHOD))
    p.add_argument("--linked-activities", default=None, dest="linked_activities", nargs="*", help="replaces the full list")
    p.add_argument("--linked-evidence", default=None, dest="linked_evidence", nargs="*", help="replaces the full list")
    p.add_argument("--vendor", default=None)
    p.add_argument("--visibility", default=None, choices=[
        "personal_only", "communardo_internal", "communardo_management",
        "atlassian_shareable", "customer_approved", "anonymised", "public",
    ])
    p.add_argument("--status", default=None, choices=sorted(EDITABLE_STATUSES))
    p.add_argument("--notes", default=None)
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("link-activity")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--activity-id", required=True, dest="activity_id")
    p.set_defaults(func=cmd_link_activity)

    p = sub.add_parser("link-evidence")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--evidence-id", required=True, dest="evidence_id")
    p.set_defaults(func=cmd_link_evidence)

    p = sub.add_parser("set-progress")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--pct", required=True, type=float, help="may exceed 100 to record genuine overachievement")
    p.set_defaults(func=cmd_set_progress)

    p = sub.add_parser("at-risk")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--recovery-action", required=True, dest="recovery_action")
    p.set_defaults(func=cmd_at_risk)

    p = sub.add_parser("resolve-risk")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.set_defaults(func=cmd_resolve_risk)

    p = sub.add_parser("complete")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--completion-note", default=None, dest="completion_note")
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser("miss")
    p.add_argument("--objective-id", required=True, dest="objective_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_miss)

    p = sub.add_parser("list")
    p.add_argument("--period", default=None)
    p.add_argument("--status", default="open_all",
                   help="open_all (default: on_track or at_risk), on_track, at_risk, completed, missed, or all")
    p.add_argument("--vendor", default=None)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("export")
    p.add_argument("--period", default=None, help="omit to export every objective across all periods")
    p.set_defaults(func=cmd_export)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
