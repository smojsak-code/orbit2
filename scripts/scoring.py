#!/usr/bin/env python3
"""
Orbit2 scoring engine.

Reads the category CSVs in /data, applies the documented scoring methodology
(see /docs/methodology.md), and writes a single snapshot file:
/data/scores_snapshot.json

Run manually any time after updating a CSV:
    python3 scripts/scoring.py

Design notes:
- Each category CSV has one row per sub-metric per vendor per quarter.
- score_method "ratio": sub_score = min(100, actual/target*100), lower actual than target = lower score.
  If a metric is naturally "lower is better", store it as ratio of target/actual instead (documented per row).
- category_score = weighted average of its sub-metric scores (weight_pct_in_category, must sum to 100)
- overall_score = weighted average of category_score using weights.json (must sum to 100 per vendor)
- Only the LATEST quarter present per vendor/category is scored (so partial updates don't skew history).
"""
import csv
import json
import os
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

def load_categories():
    """Category registry now lives in data/categories.json, not hardcoded here —
    add a whole new category by editing that file, no code change needed."""
    with open(os.path.join(DATA_DIR, "categories.json")) as f:
        registry = json.load(f)
    registry.pop("_comment", None)
    return registry


def load_weights():
    with open(os.path.join(DATA_DIR, "weights.json")) as f:
        return json.load(f)


def read_category_csv(filename):
    path = os.path.join(DATA_DIR, f"{filename}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def latest_quarter(rows, vendor):
    quarters = sorted({r["quarter"] for r in rows if r["vendor"] == vendor})
    return quarters[-1] if quarters else None


def score_submetric(row):
    try:
        target = float(row["target"])
        actual = float(row["actual"])
    except (ValueError, KeyError):
        return None
    if target == 0:
        return None
    method = row.get("score_method", "ratio")
    if method == "ratio":
        return min(100.0, round((actual / target) * 100, 1))
    if method == "inverse":  # lower actual is better (e.g. escalations, churn)
        return min(100.0, round((target / actual) * 100, 1)) if actual else 100.0
    return None


def score_category(filename, vendor):
    rows = [r for r in read_category_csv(filename) if r["vendor"] == vendor]
    q = latest_quarter(rows, vendor)
    rows = [r for r in rows if r["quarter"] == q]
    submetrics = []
    weighted_sum = 0.0
    weight_total = 0.0
    for r in rows:
        s = score_submetric(r)
        w = float(r.get("weight_pct_in_category", 0) or 0)
        submetrics.append({
            "sub_metric": r["sub_metric"],
            "target": r["target"],
            "actual": r["actual"],
            "unit": r.get("unit", ""),
            "weight_pct_in_category": w,
            "score": s,
            "source": r.get("source", ""),
            "notes": r.get("notes", ""),
            "description": r.get("description", ""),
        })
        if s is not None:
            weighted_sum += s * w
            weight_total += w
    category_score = round(weighted_sum / weight_total, 1) if weight_total > 0 else None
    return {
        "quarter": q,
        "category_score": category_score,
        "weight_check": round(weight_total, 1),  # should be ~100; flag if not
        "sub_metrics": submetrics,
    }


def read_solution_verticals(vendor):
    rows = [r for r in read_category_csv("solution_verticals") if r["vendor"] == vendor]
    q = latest_quarter(rows, vendor)
    return [r for r in rows if r["quarter"] == q]


def read_deals(vendor, quarter=None):
    """Key deals register (data/deals.csv). Not part of the weighted score — supporting
    detail for reports/dashboard. If quarter is None, returns all quarters for the vendor
    (most recent first) so the report can show a running deal history, not just one quarter."""
    path = os.path.join(DATA_DIR, "deals.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("vendor") == vendor]
    if quarter:
        rows = [r for r in rows if r.get("quarter") == quarter]
    return sorted(rows, key=lambda r: r.get("close_date", ""), reverse=True)


def score_vendor(vendor, cat_weights, category_registry):
    categories = {}
    overall_weighted_sum = 0.0
    overall_weight_total = 0.0
    for key, meta in category_registry.items():
        result = score_category(meta["file"], vendor)
        result["label"] = meta["label"]
        w = cat_weights.get(key, 0)
        result["weight_pct"] = w
        categories[key] = result
        if result["category_score"] is not None:
            overall_weighted_sum += result["category_score"] * w
            overall_weight_total += w
    overall_score = round(overall_weighted_sum / overall_weight_total, 1) if overall_weight_total > 0 else None
    return {
        "vendor": vendor,
        "overall_score": overall_score,
        "weight_check": round(overall_weight_total, 1),
        "categories": categories,
        "solution_verticals": read_solution_verticals(vendor),
        "deals": read_deals(vendor),
    }


def read_evidence_index():
    path = os.path.join(DATA_DIR, "evidence_index.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_changelog():
    path = os.path.join(DATA_DIR, "metric_changelog.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main():
    weights = load_weights()
    weights.pop("_comment", None)
    categories = load_categories()
    snapshot = {
        "generated_note": "Run scripts/scoring.py after updating any CSV in /data to refresh this file.",
        "vendors": {v: score_vendor(v, w, categories) for v, w in weights.items()},
        "evidence": read_evidence_index(),
        "changelog": read_changelog(),
        "category_registry": categories,
    }
    out_path = os.path.join(DATA_DIR, "scores_snapshot.json")
    with open(out_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Wrote {out_path}")
    for v, data in snapshot["vendors"].items():
        print(f"  {v}: overall score = {data['overall_score']} (weight check: {data['weight_check']}/100)")
        for k, c in data["categories"].items():
            flag = "" if c["weight_check"] == 100 else "  <-- weights don't sum to 100, check CSV"
            print(f"    {c['label']}: {c['category_score']}{flag}")


if __name__ == "__main__":
    main()
