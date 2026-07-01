#!/usr/bin/env python3
"""
Orbit2 metric manager — the tool for keeping the scorecard aligned with a
vendor's program when they add, change, or retire a metric (e.g. Atlassian
renames PVR, drops a registration type, or introduces a new one).

Every command that changes the schema writes a row to data/metric_changelog.csv
so there's a permanent record of *what* changed and *why* — this is what lets
Orbit2 answer "why did our score move" months later instead of just showing a
new number with no history.

Commands:
  add-category      Register a brand-new scorecard category (creates its CSV too)
  deprecate-category  Zero out a category's weight and log why (data stays, just stops counting)
  set-category-weight Change a category's weight in weights.json
  add-submetric     Add a new sub-metric row to a category for a given quarter
  amend-submetric   Change an existing sub-metric's weight/target/unit for a quarter
  deprecate-submetric Log that a sub-metric is being dropped going forward
                      (simplest correct approach: just don't include it in the next quarter's rows —
                      this command only logs the change for the audit trail)
  diff-quarter      Auto-detect what changed between two quarters of one category
                      and write changelog rows for you (added / removed / amended)

Every command prints what it did. Re-run scripts/scoring.py afterwards to refresh the scorecard.
"""
import argparse
import csv
import json
import os
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CATEGORIES_PATH = os.path.join(DATA_DIR, "categories.json")
WEIGHTS_PATH = os.path.join(DATA_DIR, "weights.json")
CHANGELOG_PATH = os.path.join(DATA_DIR, "metric_changelog.csv")
CHANGELOG_FIELDS = ["date", "vendor", "category", "sub_metric", "change_type", "old_value", "new_value", "reason", "source"]
SUBMETRIC_FIELDS = ["vendor", "quarter", "sub_metric", "weight_pct_in_category", "target", "actual", "unit", "score_method", "source", "notes", "description"]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def log_change(vendor, category, sub_metric, change_type, old_value, new_value, reason, source="Claude"):
    rows = []
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, newline="") as f:
            rows = list(csv.DictReader(f))
    rows.append({
        "date": date.today().isoformat(), "vendor": vendor, "category": category,
        "sub_metric": sub_metric, "change_type": change_type,
        "old_value": old_value, "new_value": new_value, "reason": reason, "source": source,
    })
    with open(CHANGELOG_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CHANGELOG_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Logged to metric_changelog.csv: [{change_type}] {category} / {sub_metric or '(category-level)'}")


def cmd_add_category(args):
    categories = load_json(CATEGORIES_PATH)
    if args.key in categories:
        print(f"Category '{args.key}' already exists — use amend/deprecate commands instead.")
        return
    categories[args.key] = {"label": args.label, "file": args.key}
    save_json(CATEGORIES_PATH, categories)

    csv_path = os.path.join(DATA_DIR, f"{args.key}.csv")
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="") as f:
            csv.writer(f).writerow(SUBMETRIC_FIELDS)

    weights = load_json(WEIGHTS_PATH)
    vendor_weights = weights.setdefault(args.vendor, {})
    vendor_weights[args.key] = args.weight
    save_json(WEIGHTS_PATH, weights)

    total = sum(v for k, v in vendor_weights.items())
    warn = "" if total == 100 else f"  WARNING: {args.vendor}'s category weights now sum to {total}, not 100 — adjust others with set-category-weight."
    log_change(args.vendor, args.key, "", "added", "", f"new category, weight {args.weight}%", args.reason, args.source)
    print(f"Added category '{args.key}' ({args.label}) at {args.weight}% for {args.vendor}. Created data/{args.key}.csv — add sub-metric rows next.{warn}")


def cmd_deprecate_category(args):
    weights = load_json(WEIGHTS_PATH)
    old = weights.get(args.vendor, {}).get(args.key)
    weights.setdefault(args.vendor, {})[args.key] = 0
    save_json(WEIGHTS_PATH, weights)
    log_change(args.vendor, args.key, "", "deprecated", f"{old}%", "0%", args.reason, args.source)
    print(f"Deprecated category '{args.key}' for {args.vendor} (weight set to 0). Historical data is untouched — remaining categories won't auto-rebalance, adjust weights.json yourself if you want the freed weight redistributed.")


def cmd_set_category_weight(args):
    weights = load_json(WEIGHTS_PATH)
    old = weights.get(args.vendor, {}).get(args.key)
    weights.setdefault(args.vendor, {})[args.key] = args.weight
    save_json(WEIGHTS_PATH, weights)
    total = sum(v for k, v in weights[args.vendor].items())
    warn = "" if total == 100 else f"  WARNING: {args.vendor}'s category weights now sum to {total}, not 100."
    log_change(args.vendor, args.key, "", "amended", f"{old}%", f"{args.weight}%", args.reason, args.source)
    print(f"Set '{args.key}' weight to {args.weight}% for {args.vendor}.{warn}")


def read_category_rows(category_key):
    categories = load_json(CATEGORIES_PATH)
    filename = categories[category_key]["file"]
    path = os.path.join(DATA_DIR, f"{filename}.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    return path, rows


def write_category_rows(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUBMETRIC_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def cmd_add_submetric(args):
    path, rows = read_category_rows(args.category)
    existing = [r for r in rows if r["vendor"] == args.vendor and r["quarter"] == args.quarter and r["sub_metric"] == args.sub_metric]
    if existing:
        print(f"'{args.sub_metric}' already exists for {args.vendor} {args.quarter} in this category — use amend-submetric instead.")
        return
    rows.append({
        "vendor": args.vendor, "quarter": args.quarter, "sub_metric": args.sub_metric,
        "weight_pct_in_category": args.weight, "target": args.target, "actual": args.actual,
        "unit": args.unit, "score_method": args.score_method, "source": args.source_field, "notes": args.notes,
        "description": args.description,
    })
    write_category_rows(path, rows)
    log_change(args.vendor, args.category, args.sub_metric, "added", "", f"weight {args.weight}%, target {args.target} {args.unit}", args.reason, args.source_field)
    print(f"Added sub-metric '{args.sub_metric}' to {args.category} for {args.vendor} {args.quarter}. Remember: weights within a category must sum to 100 — check the others.")


def cmd_amend_submetric(args):
    path, rows = read_category_rows(args.category)
    found = False
    old_summary = None
    for r in rows:
        if r["vendor"] == args.vendor and r["quarter"] == args.quarter and r["sub_metric"] == args.sub_metric:
            old_summary = f"weight {r['weight_pct_in_category']}%, target {r['target']} {r['unit']}"
            if args.weight is not None:
                r["weight_pct_in_category"] = args.weight
            if args.target is not None:
                r["target"] = args.target
            if args.actual is not None:
                r["actual"] = args.actual
            if args.unit is not None:
                r["unit"] = args.unit
            if args.notes is not None:
                r["notes"] = args.notes
            if args.description is not None:
                r["description"] = args.description
            found = True
    if not found:
        print(f"No row found for '{args.sub_metric}' / {args.vendor} / {args.quarter} in {args.category} — use add-submetric instead.")
        return
    write_category_rows(path, rows)
    new_summary = f"weight {args.weight}%, target {args.target}" if args.weight or args.target else "see notes"
    log_change(args.vendor, args.category, args.sub_metric, "amended", old_summary, new_summary, args.reason, "Claude")
    print(f"Amended '{args.sub_metric}' in {args.category} for {args.vendor} {args.quarter}.")


def cmd_deprecate_submetric(args):
    log_change(args.vendor, args.category, args.sub_metric, "deprecated", "active", "removed", args.reason, args.source)
    print(f"Logged deprecation of '{args.sub_metric}' in {args.category}. To take effect, simply don't include this sub-metric when you next add rows for a new quarter — the scorecard only reads the latest quarter present, so it'll drop out naturally. Remember the remaining sub-metrics' weights need to still sum to 100.")


def cmd_diff_quarter(args):
    _, rows = read_category_rows(args.category)
    rows = [r for r in rows if r["vendor"] == args.vendor]
    from_rows = {r["sub_metric"]: r for r in rows if r["quarter"] == args.from_quarter}
    to_rows = {r["sub_metric"]: r for r in rows if r["quarter"] == args.to_quarter}

    added = set(to_rows) - set(from_rows)
    removed = set(from_rows) - set(to_rows)
    common = set(from_rows) & set(to_rows)

    for name in added:
        r = to_rows[name]
        log_change(args.vendor, args.category, name, "added", "", f"weight {r['weight_pct_in_category']}%, target {r['target']} {r['unit']}", args.reason or f"New in {args.to_quarter}", args.source)
    for name in removed:
        r = from_rows[name]
        log_change(args.vendor, args.category, name, "deprecated", f"weight {r['weight_pct_in_category']}%, target {r['target']} {r['unit']}", "removed", args.reason or f"No longer present as of {args.to_quarter}", args.source)
    for name in common:
        old, new = from_rows[name], to_rows[name]
        changed_fields = [f for f in ("weight_pct_in_category", "target", "unit", "score_method") if old.get(f) != new.get(f)]
        if changed_fields:
            old_s = ", ".join(f"{f}={old.get(f)}" for f in changed_fields)
            new_s = ", ".join(f"{f}={new.get(f)}" for f in changed_fields)
            log_change(args.vendor, args.category, name, "amended", old_s, new_s, args.reason or f"Changed between {args.from_quarter} and {args.to_quarter}", args.source)

    if not (added or removed or any(
        [f for f in ("weight_pct_in_category", "target", "unit", "score_method") if from_rows[n].get(f) != to_rows[n].get(f)]
        for n in common
    )):
        print(f"No differences found between {args.from_quarter} and {args.to_quarter} for {args.category}.")
    else:
        print(f"Diffed {args.category}: {len(added)} added, {len(removed)} deprecated, "
              f"{sum(1 for n in common if any(from_rows[n].get(f) != to_rows[n].get(f) for f in ('weight_pct_in_category','target','unit','score_method')))} amended.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add-category")
    p.add_argument("--vendor", required=True)
    p.add_argument("--key", required=True, help="short id, e.g. 'partner_certifications'")
    p.add_argument("--label", required=True)
    p.add_argument("--weight", type=float, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="Claude")
    p.set_defaults(func=cmd_add_category)

    p = sub.add_parser("deprecate-category")
    p.add_argument("--vendor", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="Claude")
    p.set_defaults(func=cmd_deprecate_category)

    p = sub.add_parser("set-category-weight")
    p.add_argument("--vendor", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--weight", type=float, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="Claude")
    p.set_defaults(func=cmd_set_category_weight)

    p = sub.add_parser("add-submetric")
    p.add_argument("--vendor", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--quarter", required=True)
    p.add_argument("--sub-metric", required=True, dest="sub_metric")
    p.add_argument("--weight", type=float, required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--actual", required=True)
    p.add_argument("--unit", default="")
    p.add_argument("--score-method", default="ratio", dest="score_method")
    p.add_argument("--source-field", default="", dest="source_field")
    p.add_argument("--notes", default="")
    p.add_argument("--description", default="", help="plain-language explanation of what this sub-metric measures and why it matters")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_add_submetric)

    p = sub.add_parser("amend-submetric")
    p.add_argument("--vendor", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--quarter", required=True)
    p.add_argument("--sub-metric", required=True, dest="sub_metric")
    p.add_argument("--weight", type=float, default=None)
    p.add_argument("--target", default=None)
    p.add_argument("--actual", default=None)
    p.add_argument("--unit", default=None)
    p.add_argument("--notes", default=None)
    p.add_argument("--description", default=None)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_amend_submetric)

    p = sub.add_parser("deprecate-submetric")
    p.add_argument("--vendor", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--sub-metric", required=True, dest="sub_metric")
    p.add_argument("--reason", required=True)
    p.add_argument("--source", default="Claude")
    p.set_defaults(func=cmd_deprecate_submetric)

    p = sub.add_parser("diff-quarter")
    p.add_argument("--vendor", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--from-quarter", required=True, dest="from_quarter")
    p.add_argument("--to-quarter", required=True, dest="to_quarter")
    p.add_argument("--reason", default=None)
    p.add_argument("--source", default="Claude")
    p.set_defaults(func=cmd_diff_quarter)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
