# Orbit2 testing & release validation (R1-T09)

This is the safety net required before any Release 1 task is trusted:
repeatable automated tests plus one command that validates the whole
release. Read this before changing any script in `scripts/` or either
HTML surface (`dashboard.html`, `web/index_template.html`).

## Quick start

```bash
pip install pytest beautifulsoup4 --break-system-packages   # one-time, if not already installed
python3 scripts/validate_release.py
```

Expected output ends with:

```
======================================================================
Release 1 validation summary
======================================================================
  [PASS] 1. Data validation (scripts/validate_data.py) — exit code 0
  [PASS] 2. Python unit tests (pytest tests/) — 82 passed in 0.4Xs
  [PASS] 3. Scoring engine (scripts/scoring.py) — exit code 0
  [PASS] 4. Web build + report smoke test (scripts/build_web.py) — report smoke test OK for 1 vendor(s)
  [PASS] 5. HTML structural checks (scripts/check_html.py) — exit code 0

All checks passed.
```

Exit code `0` means every check passed. Exit code `1` means at least one
step failed — the summary table shows exactly which one(s); scroll up in
the output for that step's full detail.

**Release 1 must not be declared complete until this passes against a
FRESH CLONE of the repository**, not just the long-lived working copy —
see "Clean-checkout verification" below. This is roadmap instruction #58,
not optional.

## Running just the unit tests

```bash
python3 -m pytest tests/ -v
```

Expected: `82 passed` (as of R1-T09; this number grows as later releases
add tests — check `pytest.ini`/`tests/` for the current count, don't treat
82 as a hardcoded expectation). Runtime is well under a second — the suite
is fully isolated from disk I/O against real data (see "Test isolation"
below), so there's no reason for it to ever take more than a few seconds
even as it grows.

Run one file at a time while iterating:

```bash
python3 -m pytest tests/test_impact.py -v
python3 -m pytest tests/test_objectives.py -v
python3 -m pytest tests/test_validate_data.py -v
```

## What's covered

| File | Covers |
|---|---|
| `tests/test_schema.py` | `categories.json`/`weights.json` loading & cross-reference, `app_config.json` loading/defaults/validation (`scripts/config.py`), `schema_version.json` shape |
| `tests/test_migrations.py` | `scripts/migrations/migration_001_add_record_ids.py`'s `apply()` — backfill correctness, **idempotency** (running twice never reassigns/duplicates an ID), shared-namespace ID uniqueness across files, graceful handling of a missing file. Also `migration_002_metric_results_history.py` (R2-T01) — creates `metric_results_history.csv`/`verification_levels.json`, migrates every category-CSV row with correctly-computed `official_score`/`actual_attainment`, `evidence_backed` verification when evidence is linked, `freshness_date` from `metric_changelog.csv`, idempotency, and never touching the category CSVs/scoring inputs themselves. Also `migration_003_contacts.py` (Contacts Phase 1 / R3-T01) — creates all four Contacts files, idempotent, never overwrites existing contacts on a second run |
| `tests/test_journal.py` | Partner Value Journal CRUD (`scripts/journal.py`'s `cmd_create`/`cmd_edit`/`cmd_archive`) — archiving never deletes, editing only touches requested fields, re-archiving is a safe no-op, the change-request executable-content guard |
| `tests/test_actions.py` | `scripts/actions.py`'s date logic — `is_overdue()`/`is_due_soon()`/`period_start()` against fixed injected dates, mutual exclusivity of overdue vs. due-soon, `original_due_date` preservation |
| `tests/test_impact.py` | `scripts/impact.py`'s `compute_impact_aggregates()` — category partition sums to the total exactly, `personal_only`/archived exclusion, financial totals **never combined** across status or currency, `awaiting_validation` driven by `confidence` not `value.status`, narrative language (joint contribution ≠ sole ownership) |
| `tests/test_objectives.py` | `scripts/objectives.py`'s `compute_progress()` — manual/count_linked/sum_linked_value calculation, overachievement always surfaced separately from the capped official percentage, the at-risk/resolve-risk/complete CLI workflow and its terminal-state discipline |
| `tests/test_visibility.py` | `build_web.py`'s `_visible_for_homepage()` and `impact.py`'s `_visible_for_impact()` — both independently exclude only `personal_only`, and are asserted to agree with each other on every visibility value |
| `tests/test_validate_data.py` | Every `validate_*()` function in `scripts/validate_data.py`, each with one deliberately-corrupted fixture proving that specific check actually fires (not just that clean data passes). Includes `validate_metric_results_history()` (R2-T01) — duplicate version rejection, `official_score`/`actual_attainment` drift detection, invalid `verification_level`, unknown `evidence_refs`. Also `validate_contacts()`/`validate_contact_aliases()`/`validate_contact_evidence()` (Contacts Phase 1 / R3-T01) — duplicate ids, `merged_into` chain validity, invalid enums, dangling `superseded_by` references (and confirms a valid *forward* `superseded_by` reference is NOT flagged) |
| `tests/test_html_checks.py` | `scripts/check_html.py` against the real `dashboard.html`/`web/index_template.html` — no duplicate element IDs, every `VIEWS` entry has a matching `#view*`/`#tab*` pair |
| `tests/test_validate_release.py` | `scripts/validate_release.py`'s own report-file-existence logic (the naming-convention bug this file's test suite caught during R1-T09's own development — see below) |
| `tests/test_metric_results.py` | `scripts/metric_results.py` (R2-T01) — `official_score` capped vs `actual_attainment` uncapped for both `ratio`/`inverse` methods, evidence-ref matching, changelog-based freshness lookup, result versioning (`append_result_version()` never overwrites a previous version) |
| `tests/test_metric_manager.py` | `scripts/metric_manager.py`'s `add-submetric`/`amend-submetric` (R2-T01 addition) — each appends a correctly-linked, correctly-versioned `metric_results_history.csv` row; a rejected duplicate `add-submetric` call does not append one |
| `tests/test_contacts.py` | `scripts/contacts.py` (Contacts Phase 1 / R3-T01) — name normalisation/similarity, `find_candidate_matches()`/`match_contact()` auto-match vs. needs-review vs. new-provisional decisions, `find-or-create`/`set-canonical-name`/`merge` CLI workflow, evidence supersession (higher-or-equal confidence updates the profile, lower confidence does not), `compute_profile_summary()`'s confirmed/probable/subjective separation and missing-information flagging |

Every test file that touches business logic also includes at least one
**intentional-failure case** — the acceptance criterion "at least one
intentional failure test proves each major validator works." Look for
`intentional_failure` in a test's name to find these.

## Test isolation — "tests do not modify production data"

No test in `tests/` ever reads or writes the real `data/` directory.
`tests/conftest.py`'s `fixture_data_dir` fixture copies
`tests/fixtures/data/` (entirely fabricated content — fake vendor
`"TestVendor"`, fake user `"Test User"`, fake company `"TestCo"`, fake
organisations like `"Fixture Corp"`) into pytest's own `tmp_path` for every
test that needs it, and the `patched_*` fixtures
(`patched_journal`/`patched_actions`/`patched_objectives`/
`patched_config`/`patched_validate_data`) monkeypatch each module's path
constants to point there — monkeypatch automatically reverts every change
when the test ends. There is no code path in the test suite that can reach
the real `data/` directory.

This was verified directly during R1-T09's own development by hashing the
real project's `actions.csv`/`objectives.csv`/`value_journal.jsonl`/
`app_config.json`/`weights.json` before and after a full test run and
confirming they were byte-identical.

`scripts/validate_release.py`'s own non-pytest steps (data validation,
scoring, web build) DO run against the real `data/` directory — but only
ever in the same read-mostly/rebuild-derived-artifacts way
`scripts/build_dashboard.py`/`build_web.py`/`validate_data.py` already do
on every ordinary task in this project. No step anywhere in this test
suite or the release validator writes a fabricated row into any register.

## HTML checks

```bash
python3 scripts/check_html.py dashboard.html web/index_template.html
```

Checks two things per file:
- **No duplicate element IDs** — two elements sharing an `id` means
  `document.getElementById(...)` silently picks the first one, leaving the
  second dead.
- **Every `VIEWS` entry has a matching `#view<Capitalized>` and
  `#tab<Capitalized>` element** — a view name added to the `VIEWS` array
  without its container/tab button means clicking that tab does nothing,
  with no error anywhere.

Expected output when clean:

```
dashboard.html: OK (5 nav target(s) checked)
web/index_template.html: OK (6 nav target(s) checked)
```

## Clean-checkout verification (roadmap instruction #58)

Before declaring Release 1 complete, run the full validator against a
throwaway fresh clone of the pushed repository — not the long-lived
working copy — since that's the only way to catch a file that works
locally but was never actually committed:

```bash
TOKEN="$(cat .github_token | tr -d '[:space:]')"
WORKDIR="$(mktemp -d)"
git clone --quiet "https://x-access-token:${TOKEN}@github.com/smojsak-code/orbit2.git" "$WORKDIR"
cd "$WORKDIR"
pip install pytest beautifulsoup4 --break-system-packages --quiet
python3 scripts/validate_release.py
```

This was run as part of R1-T09's own completion — see the completion
report for its result.

## A worked example: the bug this suite itself caught

While building `scripts/validate_release.py`, its first version's report
smoke-check assumed both the Word and PowerPoint outputs used the same
`Orbit2_Report_<vendor>_*` filename prefix. `scripts/build_dashboard.py`
actually names them differently — `Orbit2_Report_<vendor>_*.docx` for Word,
`Orbit2_Deck_<vendor>_*.pptx` for PowerPoint. Running the validator against
the real project caught this immediately (step 4 failed with
`"no .pptx report found"` even though a `.pptx` file existed on disk under
its real name). The fix is now locked in by
`tests/test_validate_release.py::test_report_files_intentional_failure_missing_pptx`,
which fails again if that naming assumption regresses — a concrete example
of why "at least one intentional failure test proves each major validator
works" matters in practice, not just as a checklist item.
