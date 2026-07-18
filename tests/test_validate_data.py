"""
scripts/validate_data.py validator tests (R1-T09 acceptance criterion:
"At least one intentional failure test proves each major validator works").

Each test here deliberately corrupts one field in the isolated fixture copy
of data/ and asserts the relevant validate_*() function actually reports an
error for it — not just that the happy-path fixture passes clean. A "happy
path" test at the top proves the unmodified fixture has zero errors, so
every failure asserted below is attributable to the specific corruption
introduced in that test, not to some pre-existing fixture problem.
"""
import csv
import json
import os


def _run_full_validation(patched_validate_data):
    """Mirrors validate_data.py's own main() sequencing exactly, so these
    tests exercise the real cross-function wiring (e.g. validate_actions
    needs the activity_ids validate_journal already collected)."""
    vd = patched_validate_data
    report = vd.Report()
    categories = vd.validate_weights_and_categories(report)
    metric_ids = vd.validate_category_files(report, categories) or set()
    evidence_ids = vd.validate_evidence_index(report, categories) or set()
    vd.validate_changelog(report)
    vd.validate_app_config(report)
    activity_ids = vd.validate_journal(report, set(metric_ids), evidence_ids) or set()
    vd.validate_actions(report, activity_ids, set(metric_ids))
    vd.validate_objectives(report, activity_ids, evidence_ids)
    return report


def test_fixture_data_is_clean_by_default(patched_validate_data):
    """Baseline: the unmodified fixture must have zero errors. Every test
    below corrupts exactly one thing relative to this baseline."""
    report = _run_full_validation(patched_validate_data)
    assert report.errors == [], f"fixture should start clean, got: {report.errors}"


def test_weights_not_summing_to_100_is_caught(patched_validate_data, fixture_data_dir):
    weights_path = os.path.join(fixture_data_dir, "weights.json")
    weights = json.load(open(weights_path))
    weights["TestVendor"]["sales_performance"] = 999
    json.dump(weights, open(weights_path, "w"))

    report = patched_validate_data.Report()
    patched_validate_data.validate_weights_and_categories(report)
    assert any("sum to" in e for e in report.errors)


def test_category_csv_duplicate_record_id_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "sales_performance.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []
    rows.append(dict(rows[0]))  # duplicate the only row -> duplicate record_id
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    categories = json.load(open(os.path.join(fixture_data_dir, "categories.json")))
    categories.pop("_comment", None)
    patched_validate_data.validate_category_files(report, categories)
    assert any("duplicate record_id" in e for e in report.errors)


def test_evidence_removed_without_removed_date_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "evidence_index.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows[0]["status"] = "removed"
    rows[0]["removed_date"] = ""  # required whenever status=removed
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    categories = json.load(open(os.path.join(fixture_data_dir, "categories.json")))
    categories.pop("_comment", None)
    patched_validate_data.validate_evidence_index(report, categories)
    assert any("removed_date" in e for e in report.errors)


def test_journal_entry_missing_outcome_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "value_journal.jsonl")
    lines = [json.loads(l) for l in open(path) if l.strip()]
    lines[0]["outcome"] = ""  # required field
    with open(path, "w") as f:
        for e in lines:
            f.write(json.dumps(e) + "\n")

    report = patched_validate_data.Report()
    patched_validate_data.validate_journal(report, set(), set())
    assert any("outcome" in e for e in report.errors)


def test_journal_value_amount_without_status_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "value_journal.jsonl")
    lines = [json.loads(l) for l in open(path) if l.strip()]
    lines[0]["value"] = {"amount": 500, "currency": "GBP"}  # status missing
    with open(path, "w") as f:
        for e in lines:
            f.write(json.dumps(e) + "\n")

    report = patched_validate_data.Report()
    patched_validate_data.validate_journal(report, set(), set())
    assert any("value.status" in e for e in report.errors)


def test_actions_completed_without_timestamp_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "actions.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    for r in rows:
        if r["action_id"] == "ACTN-0002":
            r["completed_at"] = ""  # required when status=completed
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    patched_validate_data.validate_actions(report, {"ACT-0001"}, set())
    assert any("completed_at" in e for e in report.errors)


def test_actions_references_unknown_source_activity_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "actions.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows[0]["source_activity"] = "ACT-9999"  # does not exist
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    patched_validate_data.validate_actions(report, {"ACT-0001", "ACT-0002"}, set())  # ACT-9999 deliberately absent
    assert any("unknown source_activity" in e for e in report.errors)


def test_objectives_at_risk_missing_recovery_action_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "objectives.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows[0]["status"] = "at_risk"
    rows[0]["at_risk_reason"] = "Fixture reason"
    rows[0]["recovery_action"] = ""  # required alongside at_risk_reason
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    patched_validate_data.validate_objectives(report, {"ACT-0001"}, {"EVD-0001"})
    assert any("recovery_action" in e for e in report.errors)


def test_objectives_bad_period_format_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "objectives.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows[0]["period"] = "sometime-next-year"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    patched_validate_data.validate_objectives(report, {"ACT-0001"}, {"EVD-0001"})
    assert any("period" in e for e in report.errors)


def test_app_config_missing_required_field_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "app_config.json")
    config = json.load(open(path))
    del config["default_vendor"]
    json.dump(config, open(path, "w"))

    report = patched_validate_data.Report()
    patched_validate_data.validate_app_config(report)
    assert any("default_vendor" in e for e in report.errors)


def test_changelog_duplicate_record_id_is_caught(patched_validate_data, fixture_data_dir):
    path = os.path.join(fixture_data_dir, "metric_changelog.csv")
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys())
    rows.append(dict(rows[0]))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    report = patched_validate_data.Report()
    patched_validate_data.validate_changelog(report)
    assert any("duplicate record_id" in e for e in report.errors)
