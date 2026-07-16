#!/usr/bin/env python3
"""
Orbit2 My Impact aggregation (R1-T07) — an evidence-backed view of the
user's personal contribution to Communardo, built entirely from the Partner
Value Journal (data/value_journal.jsonl). See docs/data_dictionary.md, "My
Impact dashboard", for the full design write-up.

Design decisions (see individual functions for detail):

- Every contribution figure counts value_journal.jsonl entries and ONLY
  those entries — never actions.csv. An activity and its optional linked
  follow-up action describe the same underlying event; counting both would
  double-count. This makes "no double-counting" true by construction rather
  than something that has to be actively guarded against.

- Every active, non-personal-only journal entry falls into exactly one of
  four activity-based categories (relationship / commercial / strategic /
  operational) via ACTIVITY_TYPE_TO_IMPACT_CATEGORY below — a partition, not
  an overlapping tagging scheme, so category totals always sum to the grand
  total. "Recognition" is a fifth, orthogonal section: the same entries
  grouped by recognition_status instead of activity type.

- Financial value is never combined across value.status labels (R1-T07
  acceptance criterion). Five separately-labeled totals are produced:
  confirmed / estimated / protected / potential (value.status's own
  controlled vocabulary, data/journal.py's VALID_VALUE_STATUS — no schema
  change) plus "awaiting_validation", which is the total value.amount for
  entries whose overall `confidence` field is "unverified" — i.e. a claim
  that hasn't been checked yet, cutting across whatever value.status it was
  filed under. This reuses the existing `confidence` field (already in the
  R1-T03 schema) rather than inventing a new one.

- Financial totals are also never combined across currency — each status
  bucket is a dict of {currency: amount}.

- Contribution type (initiated/led/influenced/supported/connected/
  accelerated/protected/other) is surfaced per category and the narrative
  text is worded so joint work (influenced/supported/connected/accelerated)
  never reads as sole ownership — see generate_narrative()'s _verb_for().

- The narrative is built entirely from Python string templates driven by
  the computed aggregates — no LLM/AI call of any kind, per instruction #46
  ("not unapproved AI").
"""
import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journal as journal_mod  # scripts/journal.py — read_journal(), VALID_VALUE_STATUS
import actions as actions_mod  # scripts/actions.py — today_london(), period_start()

PERSONAL_VISIBILITY = "personal_only"

ACTIVITY_TYPE_TO_IMPACT_CATEGORY = {
    "qbr": "relationship", "meeting": "relationship", "executive_briefing": "relationship",
    "deal_support": "commercial", "co_sell": "commercial", "marketplace_activity": "commercial",
    "campaign": "strategic", "workshop": "strategic",
    "enablement": "operational", "escalation_support": "operational",
    "program_admin": "operational", "other": "operational",
}
IMPACT_CATEGORIES = ["relationship", "commercial", "strategic", "operational"]
CATEGORY_LABELS = {
    "relationship": "Relationship", "commercial": "Commercial",
    "strategic": "Strategic", "operational": "Operational",
}

VALUE_STATUSES = ["confirmed", "estimated", "protected", "potential"]
RECOGNITION_STATUSES = ["unrecognised", "logged", "shared", "acknowledged"]


def impact_category_for(entry_type):
    return ACTIVITY_TYPE_TO_IMPACT_CATEGORY.get(entry_type, "operational")


def _visible_for_impact(entry):
    """Same personal_only exclusion as the homepage (R1-T06 instruction #40)
    — this is a public-site view, so entries the user marked for their own
    eyes only don't appear here either."""
    return (entry.get("visibility") or PERSONAL_VISIBILITY) != PERSONAL_VISIBILITY


def _slim_contribution(entry):
    value = entry.get("value") or {}
    return {
        "activity_id": entry.get("activity_id"),
        "date": entry.get("date"),
        "type": entry.get("type"),
        "title": entry.get("title"),
        "contribution_type": entry.get("contribution_type") or "",
        "participants": entry.get("participants") or [],
        "organisation": entry.get("organisation") or "",
        "value_amount": value.get("amount"),
        "value_currency": value.get("currency"),
        "value_status": value.get("status"),
        "recognition_status": entry.get("recognition_status"),
        "confidence": entry.get("confidence"),
        "has_evidence": bool(entry.get("evidence_links")),
    }


def _add_amount(totals, currency, amount):
    if not currency:
        currency = "?"
    totals[currency] = totals.get(currency, 0) + amount


def _category_block(entries):
    """Build one activity-type category's aggregate block from its entries
    (already filtered to just this category)."""
    contribution_type_counts = {}
    confidence_counts = {}
    with_evidence = 0
    for e in entries:
        ct = e.get("contribution_type") or "unspecified"
        contribution_type_counts[ct] = contribution_type_counts.get(ct, 0) + 1
        conf = e.get("confidence") or "unspecified"
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1
        if e.get("has_evidence"):
            with_evidence += 1
    count = len(entries)
    return {
        "count": count,
        "evidence_coverage_pct": round(100 * with_evidence / count, 1) if count else 0,
        "contribution_type_counts": contribution_type_counts,
        "confidence_counts": confidence_counts,
        "organisations": sorted({e.get("organisation") for e in entries if e.get("organisation")}),
        "entries": sorted(entries, key=lambda e: e.get("date") or "", reverse=True),
    }


def _financial_block(entries):
    """Five separately-labeled financial totals — see module docstring.
    Each bucket is {currency: amount}; never summed across currency or
    across status. 'awaiting_validation' cuts across value.status by
    confidence=='unverified' instead."""
    by_status = {status: {} for status in VALUE_STATUSES}
    counts_by_status = {status: 0 for status in VALUE_STATUSES}
    awaiting_validation = {}
    awaiting_validation_count = 0

    for e in entries:
        amount = e.get("value_amount")
        if not amount:
            continue
        currency = e.get("value_currency")
        status = e.get("value_status")
        if status in by_status:
            _add_amount(by_status[status], currency, amount)
            counts_by_status[status] += 1
        if (e.get("confidence") or "") == "unverified":
            _add_amount(awaiting_validation, currency, amount)
            awaiting_validation_count += 1

    return {
        "by_status": by_status,
        "counts_by_status": counts_by_status,
        "awaiting_validation": awaiting_validation,
        "awaiting_validation_count": awaiting_validation_count,
    }


def _recognition_block(entries):
    by_status = {}
    for status in RECOGNITION_STATUSES:
        status_entries = [e for e in entries if e.get("recognition_status") == status]
        by_status[status] = {
            "count": len(status_entries),
            "entries": sorted(status_entries, key=lambda e: e.get("date") or "", reverse=True),
        }
    return {"by_status": by_status}


def compute_impact_aggregates(journal_entries):
    """Compute the full My Impact snapshot for all four periods
    (week/month/quarter/year) in one pass. Returns a dict keyed by period,
    each value shaped:
      {
        "period_start": "YYYY-MM-DD",
        "total_contributions": int,
        "organisations": [...],
        "distinct_participants": int,
        "categories": {relationship: {...}, commercial: {...}, ...},
        "financial": {...},
        "recognition": {...},
        "narrative": "...",
      }
    """
    today = actions_mod.today_london()

    public_entries = [
        e for e in journal_entries
        if e.get("status") == "active" and _visible_for_impact(e)
    ]
    slim_all = [_slim_contribution(e) for e in public_entries]
    for s, e in zip(slim_all, public_entries):
        s["_impact_category"] = impact_category_for(e.get("type"))

    by_period = {}
    for period in ("week", "month", "quarter", "year"):
        start = actions_mod.period_start(period, today)
        in_period = [s for s in slim_all if (s.get("date") or "9999-99-99") >= start.isoformat()]

        categories = {}
        for cat in IMPACT_CATEGORIES:
            cat_entries = [s for s in in_period if s["_impact_category"] == cat]
            categories[cat] = _category_block(cat_entries)

        financial = _financial_block(in_period)
        recognition = _recognition_block(in_period)

        distinct_participants = {p for s in in_period for p in (s.get("participants") or [])}
        organisations = sorted({s.get("organisation") for s in in_period if s.get("organisation")})

        agg = {
            "period_start": start.isoformat(),
            "total_contributions": len(in_period),
            "organisations": organisations,
            "distinct_participants": len(distinct_participants),
            "categories": categories,
            "financial": financial,
            "recognition": recognition,
        }
        agg["narrative"] = generate_narrative(period, agg)
        by_period[period] = agg

    return {"generated_at_london": today.isoformat(), "by_period": by_period}


# --- Deterministic narrative (instruction #46 — templates, not AI) ---

PERIOD_LABELS = {"week": "this week", "month": "this month", "quarter": "this quarter", "year": "this year"}

# Contribution types that describe joint/supporting work rather than sole
# ownership — the narrative must never phrase these as "you delivered X"
# (acceptance criterion: "Joint contributions do not imply sole ownership").
JOINT_CONTRIBUTION_TYPES = {"influenced", "supported", "connected", "accelerated", "protected"}
SOLE_CONTRIBUTION_TYPES = {"initiated", "led"}


def _dominant_contribution_type(categories):
    counts = {}
    for cat in categories.values():
        for ct, n in cat["contribution_type_counts"].items():
            counts[ct] = counts.get(ct, 0) + n
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _verb_phrase(dominant_type):
    if dominant_type in SOLE_CONTRIBUTION_TYPES:
        return "drove"
    if dominant_type in JOINT_CONTRIBUTION_TYPES:
        return "contributed to"
    return "logged"


def _format_money(by_currency):
    if not by_currency:
        return None
    parts = [f"{amount:,.0f} {currency}" for currency, amount in sorted(by_currency.items())]
    return " + ".join(parts)


def generate_narrative(period, agg):
    """Build a short plain-language paragraph purely from string templates
    over the already-computed aggregate — no external calls, no LLM. Every
    figure it states is traceable back to the same `agg` dict the UI
    renders from (acceptance criterion: 'every count and value can be
    traced to underlying journal records')."""
    label = PERIOD_LABELS.get(period, period)
    total = agg["total_contributions"]

    if total == 0:
        return (
            f"Nothing logged {label} yet. Use \"+ Add Activity\" on the Home tab to start "
            f"building this picture — it takes under a minute per entry."
        )

    categories = agg["categories"]
    dominant_type = _dominant_contribution_type(categories)
    verb = _verb_phrase(dominant_type)

    org_count = len(agg["organisations"])
    org_clause = ""
    if org_count == 1:
        org_clause = f" with {agg['organisations'][0]}"
    elif org_count > 1:
        org_clause = f" across {org_count} organisations"

    sentence1 = f"You {verb} {total} logged contribution{'s' if total != 1 else ''} {label}{org_clause}."

    # Category breakdown clause — only mention categories that actually have entries.
    active_cats = [(cat, categories[cat]) for cat in IMPACT_CATEGORIES if categories[cat]["count"] > 0]
    if active_cats:
        cat_parts = [f"{block['count']} {CATEGORY_LABELS[cat].lower()}" for cat, block in active_cats]
        sentence2 = "That breaks down as " + ", ".join(cat_parts) + "."
    else:
        sentence2 = ""

    # Financial clause — separately labeled, never combined (acceptance criterion).
    fin = agg["financial"]
    money_clauses = []
    for status in VALUE_STATUSES:
        money = _format_money(fin["by_status"][status])
        if money:
            money_clauses.append(f"{money} {status}")
    sentence3 = ""
    if money_clauses:
        sentence3 = "Financial value attached: " + "; ".join(money_clauses) + "."
    aw = _format_money(fin["awaiting_validation"])
    if aw:
        sentence3 += f" A further {aw} is awaiting validation (unverified confidence)."

    # Recognition clause.
    unrecognised = agg["recognition"]["by_status"]["unrecognised"]["count"]
    sentence4 = ""
    if unrecognised:
        sentence4 = (
            f"{unrecognised} contribution{'s' if unrecognised != 1 else ''} {'is' if unrecognised == 1 else 'are'} "
            f"still unrecognised — worth flagging up if that value hasn't been acknowledged yet."
        )

    if agg["distinct_participants"]:
        sentence1 += f" {agg['distinct_participants']} other people were involved across these — this reflects joint work, not solo output."

    return " ".join(s for s in [sentence1, sentence2, sentence3, sentence4] if s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", default="quarter", choices=["week", "month", "quarter", "year"])
    ap.add_argument("--show", action="store_true", help="Print the computed aggregate for --period as JSON.")
    args = ap.parse_args()

    entries = journal_mod.read_journal()
    full = compute_impact_aggregates(entries)
    agg = full["by_period"][args.period]

    print(f"My Impact — {args.period} (as of {full['generated_at_london']}, Europe/London)\n")
    print(agg["narrative"])
    if args.show:
        print("\n" + json.dumps(agg, indent=2, default=str))


if __name__ == "__main__":
    main()
