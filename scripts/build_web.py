#!/usr/bin/env python3
"""
Orbit2 web build — produces the static bundle served live by GitHub Pages at the repo root:

  index.html               copied from web/index_template.html (rarely changes; fetches its data
                            fresh on every page load, so this almost never needs to be re-pushed)
  data/web_snapshot.json   vendors, news, evidence, changelog, category registry, and a manifest
                            of which report files exist per vendor (filenames only — the files
                            themselves are plain static downloads, not embedded)
  reports/*.docx/.pdf/.pptx  same report files build_dashboard.py produces, reused here

Why this is a separate build from build_dashboard.py: the Cowork artifact (build_dashboard.py)
has no filesystem of its own, so it must embed everything (data + report bytes) directly into the
HTML it pushes. A GitHub Pages site IS a filesystem — index.html can just fetch data/web_snapshot.json
and link straight to reports/*.docx, so nothing needs to be base64-embedded or republished except
when the page's own code changes (rare) or the data/reports actually change (routine).

Run this after any data change, then commit + push data/, reports/, and (if it changed) index.html
to GitHub. That's the one manual/automatable step that makes the live site reflect the change.

Usage:
    python3 scripts/build_web.py [vendor ...]
"""
import csv
import json
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, SCRIPTS_DIR)
import build_dashboard as bd  # reuses run() + build_vendor_reports() — same generation logic
import journal as journal_mod  # scripts/journal.py — read_journal(), reused for R1-T06's homepage
import actions as actions_mod  # scripts/actions.py — today_london(), reused for period math
import impact as impact_mod  # scripts/impact.py — compute_impact_aggregates() (R1-T07)
import contacts as contacts_mod  # scripts/contacts.py — Contacts Phase 4 public-site mirror (R3-T01)
import visibility as visibility_mod  # scripts/visibility.py — shared is_public_visible() (Improvement Roadmap IR-A1/A2/C1)

# --- R1-T06: Daily Alliance Manager homepage aggregation ---
#
# Deliberately lives in build_web.py, not build_dashboard.py — R1-T06's own
# "Primary files/components" list scopes this feature to the public site
# only (web/index_template.html, web/assets/home.js, scripts/build_web.py,
# data/web_snapshot.json). The Cowork dashboard's own Dashboard tab is
# untouched by this task.
#
# Instruction #39 ("publish only the calculated view data needed by the
# page") is why this returns small, pre-shaped lists/counts rather than the
# full contents of value_journal.jsonl or actions.csv (actions.csv's full
# contents already get published separately for the Actions tab — see
# R1-T05 — but the homepage itself only receives the slim, curated subset it
# actually renders).

PERSONAL_VISIBILITY = "personal_only"


def _visible_for_homepage(row):
    """R1-T06 instruction #40: don't expose personal_only records on the
    (potentially shared) public homepage. This is the one visibility value
    that unambiguously means 'not for anyone else' — the rest of the
    visibility scale (communardo_internal, atlassian_shareable, etc.) is a
    Release 2 enforcement concern (see docs/data_dictionary.md) and is left
    alone here; only personal_only is filtered at this stage."""
    return (row.get("visibility") or PERSONAL_VISIBILITY) != PERSONAL_VISIBILITY


def _slim_action(row):
    return {
        "action_id": row.get("action_id"),
        "description": row.get("description"),
        "owner": row.get("owner"),
        "due_date": row.get("due_date"),
        "priority": row.get("priority"),
        "status": row.get("status"),
        "vendor": row.get("vendor"),
    }


def _slim_journal(entry):
    value = entry.get("value") or {}
    return {
        "activity_id": entry.get("activity_id"),
        "date": entry.get("date"),
        "type": entry.get("type"),
        "title": entry.get("title"),
        "outcome": entry.get("outcome"),
        "next_action": entry.get("next_action"),
        "organisation": entry.get("organisation"),
        "value_amount": value.get("amount"),
        "value_currency": value.get("currency"),
        "value_status": value.get("status"),
        "recognition_status": entry.get("recognition_status"),
    }


def compute_homepage_aggregates(scores_snapshot, action_rows, journal_entries, evidence_rows):
    today = actions_mod.today_london()

    public_actions = [a for a in action_rows if _visible_for_homepage(a)]
    public_journal = [
        e for e in journal_entries
        if e.get("status") == "active" and _visible_for_homepage(e)
    ]

    overdue_actions = sorted(
        [a for a in public_actions if a.get("is_overdue")],
        key=lambda a: a.get("due_date") or "",
    )
    due_soon_actions = sorted(
        [a for a in public_actions if a.get("is_due_soon")],
        key=lambda a: a.get("due_date") or "",
    )

    # Follow-ups due: an activity noted a next step, but no action was ever
    # created for it (the opt-in checkbox on Add Activity was left
    # unchecked, or the follow-up was never turned into a tracked action at
    # all). This is the gap list, not a duplicate of the Actions tab.
    linked_activity_ids = {a.get("source_activity") for a in action_rows if a.get("source_activity")}
    followups_due = [
        e for e in public_journal
        if (e.get("next_action") or "").strip() and e.get("activity_id") not in linked_activity_ids
    ]
    followups_due.sort(key=lambda e: e.get("date") or "", reverse=True)

    # Metrics at risk / missing evidence — per vendor, current-quarter facts
    # (not period-scoped, unlike the journal-derived sections below).
    active_evidence_pairs = {
        (r.get("category"), r.get("sub_metric"))
        for r in evidence_rows if r.get("status") == "active"
    }
    per_vendor = {}
    for vendor, v in (scores_snapshot.get("vendors") or {}).items():
        at_risk = []
        missing_evidence = []
        for cat_key, cat in (v.get("categories") or {}).items():
            for sm in cat.get("sub_metrics") or []:
                try:
                    actual = float(sm.get("actual") or 0)
                except (TypeError, ValueError):
                    actual = 0
                score = sm.get("score")
                # "At risk" requires something to actually have been
                # measured (actual != 0) — a sub-metric that's simply
                # unstarted (actual 0, score 0) isn't "at risk," it's just
                # not begun yet, and treating it as at-risk would flood this
                # section with noise on a freshly-reset scorecard.
                if actual and score is not None and score < 70:
                    at_risk.append({
                        "category_key": cat_key, "category_label": cat.get("label"),
                        "sub_metric": sm.get("sub_metric"), "score": score,
                        "actual": sm.get("actual"), "target": sm.get("target"), "unit": sm.get("unit"),
                    })
                if actual and (cat_key, sm.get("sub_metric")) not in active_evidence_pairs:
                    missing_evidence.append({
                        "category_key": cat_key, "category_label": cat.get("label"),
                        "sub_metric": sm.get("sub_metric"), "actual": sm.get("actual"), "unit": sm.get("unit"),
                    })
        at_risk.sort(key=lambda m: m.get("score") if m.get("score") is not None else 999)
        per_vendor[vendor] = {"metrics_at_risk": at_risk, "missing_evidence": missing_evidence}

    # Period-bucketed sections (recent journal entries, unrecognised value) —
    # precomputed for all four periods at build time so the client-side
    # period selector is just a lookup, not a re-fetch, while still only
    # ever shipping the slim/curated shape (instruction #39).
    by_period = {}
    for period in ("week", "month", "quarter", "year"):
        start = actions_mod.period_start(period, today)
        in_period = [e for e in public_journal if (e.get("date") or "9999-99-99") >= start.isoformat()]
        in_period.sort(key=lambda e: e.get("date") or "", reverse=True)
        unrecognised = [
            e for e in in_period
            if (e.get("value") or {}).get("amount") and e.get("recognition_status") == "unrecognised"
        ]
        by_period[period] = {
            "period_start": start.isoformat(),
            "recent_journal": [_slim_journal(e) for e in in_period[:8]],
            "recent_journal_total": len(in_period),
            "unrecognised_value": [_slim_journal(e) for e in unrecognised],
        }

    return {
        "generated_at_london": today.isoformat(),
        "overdue_actions": [_slim_action(a) for a in overdue_actions],
        "due_soon_actions": [_slim_action(a) for a in due_soon_actions],
        "followups_due": [_slim_journal(e) for e in followups_due],
        "per_vendor": per_vendor,
        "by_period": by_period,
    }


def filter_public_objectives(rows):
    """Pure filter, no I/O — the objective-half of Improvement Roadmap
    IR-A1's fix. Separated out from main() so it's unit-testable without a
    real build (see tests/test_visibility.py), same "pure check, separated
    from the step that calls it" discipline validate_release.py's
    check_report_files_exist() already uses. An objective only passes if
    its own `visibility` is explicitly one of
    visibility_mod.PUBLIC_VISIBILITY_TIERS — everything else, including a
    missing/blank value, is excluded."""
    return [o for o in rows if visibility_mod.is_public_visible(o)]


def filter_public_actions(rows):
    """Pure filter, no I/O — the action-half of Improvement Roadmap IR-A2's
    fix. Same rule as filter_public_objectives() above (shared
    visibility_mod.is_public_visible()), deliberately a DIFFERENT, stricter
    cut than compute_homepage_aggregates()'s own _visible_for_homepage()
    filter, which is unchanged and still only excludes personal_only for
    the homepage's own aggregates — see the call site in main() for which
    filter feeds which output."""
    return [a for a in rows if visibility_mod.is_public_visible(a)]


def compute_public_contacts():
    """Contacts Phase 4 — the public-site mirror. Deliberately stricter than
    every other public-site filter in this file: contacts carry real
    people's PII, and this file's output is fetched by a genuinely public
    GitHub Pages URL, not just a Steve-only Cowork session. See
    contacts.py's PUBLIC_VISIBILITY_TIERS/is_public_visible()/
    public_contact_view() docstrings for the full policy (confirmed with
    Steve): only contacts whose own `visibility` field was explicitly set
    to an external-sharing tier appear here, terminal (merged/archived)
    contacts never do, and even a cleared contact's sensitive/subjective
    evidence and direct contact details are stripped before publishing."""
    contacts = contacts_mod.read_contacts()
    evidence = contacts_mod.read_evidence()
    visible = [
        r for r in contacts
        if r.get("status") in ("provisional", "confirmed") and contacts_mod.is_public_visible(r)
    ]
    return [contacts_mod.public_contact_view(r, evidence) for r in visible]


def main():
    print("Re-running scoring engine...")
    bd.run(["python3", os.path.join(BASE_DIR, "scripts", "scoring.py")])

    with open(os.path.join(DATA_DIR, "scores_snapshot.json")) as f:
        snapshot = json.load(f)
    with open(os.path.join(DATA_DIR, "weights.json")) as f:
        weights = json.load(f)
    weights.pop("_comment", None)
    all_vendors = list(weights.keys())
    target_vendors = sys.argv[1:] if len(sys.argv) > 1 else all_vendors

    report_manifest = {}
    for vendor in target_vendors:
        if vendor not in all_vendors:
            print(f"Skipping unknown vendor: {vendor}")
            continue
        files = bd.build_vendor_reports(vendor)  # generates docx/pdf/pptx on disk in reports/
        report_manifest[vendor] = {fmt: info["filename"] for fmt, info in files.items()}

    news_path = os.path.join(DATA_DIR, "news_log.csv")
    news = []
    if os.path.exists(news_path):
        with open(news_path, newline="") as f:
            news = list(csv.DictReader(f))
    snapshot["news"] = news
    snapshot["report_files"] = report_manifest

    # app_config.json (R1-T02) — same config the Cowork dashboard embeds, so
    # generated headings on the public site read the configured company/user
    # instead of a hard-coded string.
    config = bd.app_config.load_config()
    config_errors = bd.app_config.validate(config)
    if config_errors:
        print("WARNING: data/app_config.json has validation errors (using it anyway, with defaults where possible):")
        for e in config_errors:
            print(f"  [ERROR] {e}")
    snapshot["app_config"] = config

    # activity_types.json / contribution_types.json (R1-T04) — same as build_dashboard.py.
    for fname, key in [("activity_types.json", "activity_types"), ("contribution_types.json", "contribution_types")]:
        fpath = os.path.join(DATA_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                snapshot[key] = json.load(f).get("types", {})
        else:
            snapshot[key] = {}

    # actions.csv / action_statuses.json (R1-T05) — same as build_dashboard.py.
    # `action_rows` (the FULL, unfiltered list) is kept for
    # compute_homepage_aggregates() below, which has its own separate,
    # narrower, already-documented filter (_visible_for_homepage, excludes
    # only personal_only — an R1-T06 design choice, untouched here).
    # snapshot["actions"] (the full Actions tab) is a DIFFERENT, stricter
    # cut — see the Improvement Roadmap IR-A2 comment below.
    action_rows, action_statuses = bd.load_actions_snapshot()
    snapshot["actions"] = filter_public_actions(action_rows)
    snapshot["action_statuses"] = action_statuses

    # objectives.csv (R1-T08) — read-only status surfaced on the My Impact
    # tab (instruction #50); same computed-progress helper as
    # build_dashboard.py so the two surfaces never disagree.
    #
    # Improvement Roadmap IR-A1/IR-A2 (2026-07-22): until this fix, EVERY
    # objective/action was embedded here regardless of its own `visibility`
    # field — confirmed live during the 2026-07-22 platform assessment to
    # be exposing communardo_internal objectives (including a private
    # working note quoting Steve's JD) on the actual public URL. Both lists
    # are now filtered through the same shared visibility_mod.is_public_visible()
    # Contacts already uses (Contacts Phase 4) — an objective/action only
    # appears here once its own `visibility` is explicitly set to one of
    # visibility_mod.PUBLIC_VISIBILITY_TIERS. The private Cowork dashboard
    # (build_dashboard.py's own separate call to load_objectives_snapshot())
    # is completely unaffected — full detail regardless of visibility tier,
    # by design, since that surface is never public.
    all_objectives = bd.load_objectives_snapshot(snapshot.get("evidence"))
    public_objectives = filter_public_objectives(all_objectives)
    snapshot["objectives"] = public_objectives
    snapshot["objectives_meta"] = {"total": len(all_objectives), "public": len(public_objectives)}

    # Objectives Progress Report (tasks #29/#30) — same report content as the
    # Cowork dashboard's version (bd.build_objectives_report() re-renders it
    # from the same compute_objective_detail() data, generating a fresh
    # timestamped docx+pdf every build — deliberately NOT overwritten
    # in-place, so reports/ accumulates a dated history Steve can look back
    # over, same as he asked for "a report ... that I can create at anytime
    # to show my progress"). Only the filenames go into web_snapshot.json —
    # same "manifest, not embed" pattern as report_manifest above — the
    # actual bytes are reused on disk in reports/, no separate write here.
    # Built from `public_objectives` (not `all_objectives`) so the
    # downloadable report can never contain more than the page itself shows
    # — otherwise the report would reopen the exact exposure IR-A1 closes.
    objectives_report_files = bd.build_objectives_report(public_objectives)
    snapshot["objectives_report_files"] = (
        {
            "docx": objectives_report_files["docx"]["filename"],
            "pdf": objectives_report_files["pdf"]["filename"],
            "generated_at": objectives_report_files["generated_at"],
        }
        if objectives_report_files else None
    )

    # Daily Alliance Manager homepage (R1-T06) — web-only, see module-level
    # comment above compute_homepage_aggregates().
    journal_entries = journal_mod.read_journal()
    evidence_rows = snapshot.get("evidence") or []
    snapshot["homepage"] = compute_homepage_aggregates(snapshot, action_rows, journal_entries, evidence_rows)

    # My Impact dashboard (R1-T07) — same journal_entries as the homepage
    # above; see scripts/impact.py module docstring for the full design.
    snapshot["impact"] = impact_mod.compute_impact_aggregates(journal_entries)

    # Contacts register — public-site mirror (Contacts Phase 4, R3-T01).
    # See compute_public_contacts() above for the visibility policy — this
    # is NOT the same data the Cowork dashboard's Contacts tab embeds.
    snapshot["contacts"] = compute_public_contacts()

    out_path = os.path.join(DATA_DIR, "web_snapshot.json")
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Wrote {out_path}")

    template_path = os.path.join(BASE_DIR, "web", "index_template.html")
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(template_path):
        shutil.copyfile(template_path, index_path)
        print(f"Copied {template_path} -> {index_path}")
    else:
        print(f"WARNING: {template_path} not found — index.html was not updated.")


if __name__ == "__main__":
    main()
