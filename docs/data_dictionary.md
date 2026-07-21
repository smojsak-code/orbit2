# Orbit2 Data Dictionary

This document is the canonical description of every file in `data/`: what it
holds, what its stable ID is, and what values controlled fields are allowed
to take. It is maintained as part of the schema/migration framework
(`data/schema_version.json`, `scripts/migrations/`, `scripts/validate_data.py`)
introduced in R1-T01 of the technical roadmap. Update this file whenever a
migration changes a register's shape.

## Schema versioning

The current schema version and the history of applied migrations live in
`data/schema_version.json`, managed by `scripts/migrations/run_migrations.py`
(never hand-edit that file). Run `python3 scripts/validate_data.py` any time
you want to confirm every register still matches this dictionary.

## Stable record IDs

Every row in a register that can be referenced from elsewhere (an evidence
link, a report, a future journal entry) carries a stable ID that never
changes when a title, name, or quarter changes:

| Register | ID field | Prefix | Namespace |
|---|---|---|---|
| The 9 category sub-metric CSVs (see below) | `record_id` | `MET-` | Shared across all 9 files — one counter, since every row is the same kind of entity (a sub-metric result) just partitioned by category |
| `metric_changelog.csv` | `record_id` | `CHG-` | Own file |
| `solution_verticals.csv` | `record_id` | `SV-` | Own file |
| `news_log.csv` | `record_id` | `NEWS-` | Own file |
| `evidence_index.csv` | `evidence_id` | `EVD-` | Own file (pre-existing, unchanged by this migration) |
| `deals.csv` | `deal_id` | `DEAL-` | Own file (pre-existing column; no rows populated yet) |
| `value_journal.jsonl` | `activity_id` | `ACT-` | Own file (R1-T03) |
| `actions.csv` | `action_id` | `ACTN-` | Own file (R1-T05) — deliberately distinct from `ACT-` so the journal and actions registers are never visually confused |
| `objectives.csv` | `objective_id` | `OBJ-` | Own file (R1-T08) |
| `metric_results_history.csv` | `record_id` | `RES-` | Own file (R2-T01) — every row already carries the source category-CSV row's `MET-` id in `source_record_id`, but has its own independent `RES-` counter since it can also hold results with no category-CSV row behind them in future releases |
| `contacts.csv` | `contact_id` | `CONT-` | Own file (Contacts Phase 1 / R3-T01) — never reused or renumbered, including for merged/archived contacts |
| `contact_aliases.csv` | `alias_id` | `ALIAS-` | Own file (Contacts Phase 1 / R3-T01) |
| `contact_evidence.jsonl` | `evidence_id` | `CEV-` | Own file (Contacts Phase 1 / R3-T01) — distinct from `evidence_index.csv`'s `EVD-` prefix, since these are different kinds of evidence (an Evidence Library file vs. one extracted contact fact) |

IDs are assigned once and never reused or renumbered, including by
migrations run more than once (`scripts/migrations/migration_001_add_record_ids.py`
only backfills rows missing an ID; `scripts/metric_manager.py` computes the
next free ID per namespace before writing).

## Canonical common fields (target shape for new registers)

Not every existing file has all of these yet — see each file's entry below
for what actually applies today. New registers created for Release 1 and
later should include, where applicable:

- `record_id` — stable identifier, never reused.
- `created_at` / `updated_at` — ISO 8601 timestamps.
- `created_by` / `updated_by` — defaults to the named user for the personal edition (Steve Mojsak).
- `status` — controlled value appropriate to the record type.
- `visibility` — one of `personal_only`, `communardo_internal`, `communardo_management`, `atlassian_shareable`, `customer_approved`, `anonymised`, `public`. Not yet enforced anywhere in the current schema (this is a Release 2 concern, R2-T04) — listed here so future registers use consistent values from day one.
- `source_type` — one of `manual`, `import`, `evidence_extraction`, `calculated`, `migrated`.
- `confidence` — one of `confirmed`, `supported`, `estimated`, `unverified`.
- `notes` — optional plain-language context.

## Files in `data/`

### The 9 category sub-metric CSVs
`sales_performance.csv`, `marketing.csv`, `market_visibility.csv`,
`ai_adoption.csv`, `business_planning_qbr.csv`, `registrations.csv`,
`third_party_coselling.csv`, `solutions.csv`, `services.csv`

One row per sub-metric, per vendor, per quarter. Read by `scripts/scoring.py`
(only the latest quarter per vendor is scored) and written by
`scripts/metric_manager.py`.

Columns: `record_id, vendor, quarter, sub_metric, weight_pct_in_category, target, actual, unit, score_method, source, notes, description`

- `score_method`: `ratio` (higher actual is better) or `inverse` (lower actual is better).
- `weight_pct_in_category`: must sum to 100 across all rows for one vendor+quarter within a file.
- `source`: free text — where the actual value came from (evidence ID, verbal update, etc.). Not yet a structured reference.

### `metric_results_history.csv` (Metric result history, R2-T01)
A period-indexed, append-only log of metric results — introduced by
Release 2 to carry history, forecasts, confidence and evidence coverage
without disturbing how the 9 category sub-metric CSVs already work.
Written by `scripts/metric_results.py` (shared logic: computing
`official_score`/`actual_attainment`, id assignment, versioning) and by
`scripts/migrations/migration_002_metric_results_history.py` (one-time
backfill from the category CSVs). `scripts/metric_manager.py`'s
`add-submetric`/`amend-submetric` commands also append a row here going
forward — see "Relationship to the category CSVs" below.

Columns: `record_id, vendor, category, sub_metric, period, result_version, source_record_id, target, actual, unit, score_method, official_score, actual_attainment, forecast, confidence, freshness_date, owner, verification_level, evidence_refs, source, notes, recorded_date, recorded_by`

**Which fields are manual, calculated, or imported (roadmap instruction #64):**

| Field | Kind | Notes |
|---|---|---|
| `vendor`, `category`, `sub_metric`, `period`, `target`, `actual`, `unit`, `score_method` | Manual | Entered via `metric_manager.py`, or copied from the category CSV row at migration time |
| `official_score`, `actual_attainment` | Calculated | Always derived from `target`/`actual`/`score_method` — never accepted as a caller-supplied value anywhere in `scripts/metric_results.py`. `scripts/validate_data.py`'s `validate_metric_results_history()` recomputes both and flags any row where the stored value has drifted from what its own source fields produce |
| `forecast` | Manual (future) | Defined in the schema now; nothing in R2-T01 populates it yet — no forecasting workflow exists until a later Release 2 task needs one |
| `confidence` | Calculated (future) | Defined in the schema now; deliberately left blank everywhere in R2-T01 — R2-T02 ("Upgrade the scoring and confidence engine") is what computes it, from `verification_level` + `freshness_date` + evidence coverage + completeness together. Populating it here would mean inventing a number ahead of the engine that's supposed to calculate it |
| `freshness_date` | Imported / Manual | At migration time, the most recent matching `metric_changelog.csv` date; otherwise today's date when a result is recorded |
| `owner` | Imported | Defaults from `app_config.json`'s `user_display_name` (single-user edition) |
| `verification_level` | Manual | See `verification_levels.json` below. Migration defaults to `evidence_backed` when matching active evidence exists, `unverified` otherwise; `add-submetric` defaults to `self_reported`; `amend-submetric` carries forward the previous version's level unless told otherwise |
| `evidence_refs` | Imported | Semicolon-separated `evidence_id` list, matched from `evidence_index.csv` by the same `(vendor, category, sub_metric, quarter)` key `scripts/evidence_ingest.py` already uses, filtered to `status == active` |
| `source_record_id`, `source`, `notes`, `recorded_date`, `recorded_by` | Imported / Manual | Bookkeeping — which category-CSV row this came from (if any) and who/what wrote this history row |

**Versioning, not overwriting.** `result_version` starts at 1 for a new
`(vendor, category, sub_metric, period)` and increments by 1 each time
that exact period's result is amended — the previous version's row is
never mutated or deleted. `validate_metric_results_history()` rejects two
rows sharing the same `(vendor, category, sub_metric, period,
result_version)` tuple, which is what "duplicate period results are
rejected or explicitly versioned" (R2-T01 acceptance criterion) means in
practice: a duplicate at the same version is an error, a new version is
the sanctioned way to record "the number changed since we last looked."

**Relationship to the category CSVs — why a separate file.**
`scripts/scoring.py` (R1) still reads the 9 category CSVs directly and
only the latest quarter's row per vendor/category/sub_metric is scored;
this migration and everything in `scripts/metric_results.py` leaves that
contract completely untouched (R2-T01 acceptance criterion: "existing
current scores reproduce the pre-migration values" — verified by diffing
`scores_snapshot.json` before/after migration 002 byte-for-byte). Adding
history/forecast/confidence columns to the category CSVs themselves would
have broken that "only the latest row per period counts" model, since
those files were never designed to hold more than one live value per
period. `metric_results_history.csv` gets the new capabilities without
requiring `scoring.py` to change until R2-T02 formally upgrades it.

### `verification_levels.json`
Config, not a register. Controlled vocabulary for `verification_level`,
ordered least to most rigorously checked: `unverified`, `self_reported`,
`manager_reviewed`, `evidence_backed`, `third_party_verified`. Add a new
level by adding an entry here — no code change needed,
`scripts/metric_results.py`'s `load_verification_levels()` reads it fresh
on every call. Deliberately separate from `confidence`: this field
describes *how* a result was checked (a fact about process); `confidence`
is the computed trust score R2-T02's engine will derive from this field
plus freshness, evidence coverage and completeness together.

### `categories.json`
Config, not a register. Registry of category keys → `{label, file}`. Adding
a category here (plus a matching CSV and a weight in `weights.json`)
requires no code changes.

### `weights.json`
Config, not a register. `{"<vendor>": {"<category_key>": weight_pct, ...}}`.
Category weights must sum to 100 per vendor. `validate_data.py` checks this.

### `app_config.json`
Config, not a register. The single source of truth for who's using this
Orbit2 instance and how generated views should label themselves. Loaded and
validated by `scripts/config.py` (`load_config()` / `validate()`), and
included as `app_config` in both `scores_snapshot.json`'s in-memory
equivalent used by `build_dashboard.py`/`build_web.py` and therefore in
`data/web_snapshot.json` and the Cowork dashboard's embedded `SNAPSHOT`. The
dashboard's read-only Settings tab (both the Cowork artifact and the public
site) renders straight from this.

Fields:

| Field | Required | Default if missing | Notes |
|---|---|---|---|
| `user_display_name` | yes | — | |
| `job_title` | no | `""` | |
| `company` | yes | — | Drives the page title and header sub-text everywhere |
| `default_vendor` | yes | — | Must match a key in `weights.json` to be meaningful, but this isn't enforced by `config.py` itself |
| `timezone` | no | `"Europe/London"` | Must be a valid IANA timezone name |
| `financial_currency` | no | `"USD"` | One of `EUR, USD, GBP, CHF, SEK, NOK, DKK` — extend the list in `scripts/config.py` as needed |
| `reporting_year` | no | current calendar year | Integer, 2000-2100 |
| `feature_flags` | no | `{}` | Object of `flag_name: true/false` |

**No secrets.** `scripts/config.py`'s `validate()` rejects any field name
(at any nesting level, including inside `feature_flags`) matching
`api_key`, `secret`, `password`, `token`, or `credential` — this file must
never hold connection credentials.

### `evidence_index.csv`
One row per uploaded evidence file. Read/written by `scripts/evidence_ingest.py`.

Columns: `evidence_id, date_added, vendor, category, sub_metric, quarter, filename, description, dedupe_key, status, superseded_by, source_type, removed_date, removed_reason`

- `status`: `active`, `superseded`, or `removed`.
- Removing evidence resets the linked metric's `actual` to 0 rather than
  silently keeping a stale value (see `docs/methodology.md`, "Evidence
  Library"). R2-T06 of the roadmap proposes changing this to a
  flag-for-review model instead — noted here as a known future decision
  point, not yet made.

### `metric_changelog.csv`
Append-only audit log of category/sub-metric additions, amendments and
deprecations. Written by `scripts/metric_manager.py`.

Columns: `record_id, date, vendor, category, sub_metric, change_type, old_value, new_value, reason, source`

- `change_type`: `added`, `amended`, or `deprecated`.
- `category` is sometimes a real category key and sometimes a special marker
  (`all`, `(new category)`, `(category merge)`, `(full reset)`) for
  whole-scorecard events — `validate_data.py` does not enforce category
  existence on this file for that reason.

### `solution_verticals.csv`
Solution count/revenue breakdown by industry vertical, per vendor/quarter.
Supporting detail for reports — not part of the weighted score.

Columns: `record_id, vendor, quarter, vertical, solutions_count, solutions_sold, revenue, source, notes`

### `deals.csv`
Key deals register — supporting detail for reports, not part of the
weighted score. No rows populated yet.

Columns: `deal_id, vendor, quarter, company_name, close_date, tcv, acv, currency, products_sold, services_sold, vertical, atlassian_category, deal_reg_type, source, notes`

### `news_log.csv`
Press/analyst mentions found by the scheduled news-monitoring task. Feeds
the Market Visibility category's "Press/analyst mentions volume" sub-metric.

Columns: `record_id, date_found, vendor_context, headline, source_url, sentiment, sentiment_confidence, summary`

### `value_journal.jsonl` (Partner Value Journal)
The central chronological record of alliance activities and what came of
them. JSON Lines, not CSV — the roadmap explicitly allows either for this
register, and JSONL was chosen because entries have genuinely nested/
multi-value fields (`participants`, `metric_links`, `opportunity_links`,
`evidence_links`, `value`) that a CSV would need fragile in-cell encoding
for. One JSON object per line; managed by `scripts/journal.py`
(`create` / `edit` / `archive` / `list` / `export`), validated by
`scripts/validate_data.py`.

**Activity, outcome, contribution, and value are four different things —
don't conflate them:**

- **Activity** is *what happened* — a QBR, a co-sell call, an enablement
  session. It's the `type` + `title` + `description` fields. An activity on
  its own proves nothing; it's just a record that time was spent.
- **Outcome** is *what resulted* from the activity — the required `outcome`
  field. Every entry must have one, even a plain "no material outcome yet."
  This is what separates a journal from a calendar: Orbit2 cares about
  results, not attendance.
- **Contribution** is *how you personally shaped that outcome* — the
  optional `contribution_type` field (`initiated`, `led`, `influenced`,
  `supported`, `connected`, `accelerated`, `protected`, `other`). The same
  outcome can have several contributors with different contribution types;
  recording yours as `led` does not imply nobody else was involved (see
  R1-T07's "joint contributions do not imply sole ownership").
- **Value** is *the measurable business impact*, if any — the nested
  `value` object (`amount`, `currency`, `status`). It is deliberately
  optional and separate from outcome, because most outcomes (a relationship
  strengthened, a risk mitigated, a certification earned) don't reduce to a
  number. When a number is given, `value.status` must say what kind of
  number it is — `confirmed`, `estimated`, `protected`, or `potential` —
  and `value.currency` is required alongside it.
  `scripts/validate_data.py` rejects any entry with a `value.amount` but no
  `value.currency`/`value.status`, so a number can never appear without
  saying how sure it is.

Fields: `activity_id` (`ACT-` prefix, stable), `date`, `type` (controlled,
`data/activity_types.json`), `title`, `description`, `participants` (array
of free-text names — the Contacts register now exists (see "Contacts
register" below), but linking `participants` entries to real `contact_id`s
is deliberately out of scope for Contacts Phase 1 and remains a follow-on
task; `participants` is still free text today),
`organisation`, `customer_account`, `contribution_type` (controlled,
`data/contribution_types.json`), `outcome`, `next_action`, `metric_links`
(array of `record_id`s from the category CSVs), `opportunity_links` (array —
reserved, no opportunities register exists until R3-T03, not yet validated
for existence), `evidence_links` (array of `evidence_id`s), `value`
(`{amount, currency, status}`), `recognition_status` (`unrecognised`,
`logged`, `shared`, `acknowledged`), `visibility`, `status` (`active` /
`archived` — archiving is a flag, never a delete, matching the evidence
removal precedent), `archived_at`, `archived_reason`, plus the canonical
`created_at`/`updated_at`/`created_by`/`updated_by`/`source_type`/
`confidence`/`notes` fields.

### `change_requests/` (change-request files, R1-T04)
Not a register itself — a drop zone. The "+ Add Activity" quick-capture
modal exists on both `dashboard.html` (Cowork) and `web/index_template.html`
(public site), but only the public site needs this folder: it has no
backend, so its modal downloads a JSON file here instead of writing to
`value_journal.jsonl` directly. The Cowork modal applies the identical JSON
shape immediately via chat (`sendPrompt`), skipping the file round-trip
entirely, since Cowork can talk to Claude directly.

Change-request shape (`type: "activity_create"`):

```json
{
  "request_id": "CR-<opaque>",
  "created_at": "<ISO 8601>",
  "type": "activity_create",
  "activity": { "date": "...", "type": "...", "title": "...", "outcome": "...", "...": "any value_journal.jsonl field" }
}
```

`request_id` is generated client-side and is what makes re-importing the
same request a safe no-op — `scripts/journal.py import-request`/`import-all`
check every existing journal entry's `source_request_id` before creating
anything. Applying a request never modifies `value_journal.jsonl` unless
`activity.title` and `activity.outcome` are both present, `request_id` is
present, and no field anywhere in the file matches a pattern that looks like
script/markup injection (`<script`, `javascript:`, `on*=` handlers,
`<iframe`) — see `scripts/journal.py`'s `_check_no_executable_content()`.
`import-all` files processed requests (created or duplicate) into
`change_requests/processed/`, leaving malformed ones in place for review.

### `actions.csv` (Actions & commitments register, R1-T05)
Follow-ups arising from activities, meetings, performance gaps and support
requests — one plain CSV row per action (unlike the journal, no field here is
nested/multi-value, so CSV was the natural fit rather than JSONL).
`scripts/actions.py` is the only writer; the Cowork dashboard's Actions tab
and the public site's read-only mirror both render straight from the
`actions` array injected into the snapshot by
`scripts/build_dashboard.py`/`build_web.py` (see "Generated files" below).

Stable ID: `action_id`, `ACTN-` prefix, own namespace (deliberately distinct
from the journal's `ACT-` prefix so the two are never visually confused).

Status vocabulary (`data/action_statuses.json`): `open` (default), `blocked`,
`deferred`, `completed`, `cancelled`. `completed`/`cancelled` are terminal —
excluded from overdue/due-soon calculation and from the default `list`/UI
filter (`open_all`). Direct `edit` can only move an action between
`open`/`blocked`; every other transition goes through its own command
(`complete`/`cancel`/`defer`) so the required side effects (timestamp,
reason, or note) always happen — see `scripts/actions.py`'s
`EDITABLE_STATUSES`.

Key fields: `description`, `owner` (defaults to `app_config.json`'s
`user_display_name`), `source_activity` (an `ACT-` id, optional — set
automatically when an action is created as a linked follow-up, see below),
`related_metric` (a `MET-` id, optional), `related_opportunity` (reserved,
free text until R3-T03's opportunities register exists), `due_date`,
`original_due_date` (set once at creation, never overwritten except that
`defer` copies the pre-defer `due_date` into it if it was still blank —
this is what lets a completed action "retain its original due date" even
after being deferred one or more times before completion), `priority`
(`low`/`medium`/`high`/`critical`), `expected_impact`, `dependency` (free
text — who/what this is blocked on), `evidence_required` (boolean; if true,
`complete` refuses without a `completion_note` or `completion_evidence`),
`completion_note`/`completion_evidence`/`completed_at`,
`cancelled_reason`/`cancelled_at`, `deferred_reason`/`deferred_at`, `vendor`
(defaults to `app_config.json`'s `default_vendor`), `visibility`, plus the
canonical `created_at`/`updated_at`/`created_by`/`updated_by`/`notes`.

**Overdue / due-soon are calculated, not stored.** `scripts/actions.py`'s
`is_overdue()`/`is_due_soon()` compare `due_date` against "today" in the
**Europe/London** timezone specifically — hardcoded, independent of whatever
`app_config.json`'s own `timezone` field is set to — per R1-T05's acceptance
criterion that these states be "calculated consistently from Europe/London
dates." `scripts/build_dashboard.py`/`build_web.py` compute both flags once
at build time and inject them into each action row as `is_overdue`/
`is_due_soon` so the Cowork dashboard and the public site never disagree
about which actions are overdue.

**Opt-in linked-action creation (R1-T05 instruction #31 — "automatic action
generation only when explicitly selected").** The Add Activity modal (both
`dashboard.html` and `web/index_template.html`) has an unchecked-by-default
"Also create a follow-up action" box. Only when checked does the submitted
change request gain an `action` object alongside `activity`:

```json
{
  "request_id": "CR-<opaque>",
  "type": "activity_create",
  "activity": { "...": "..." },
  "action": { "description": "...", "due_date": "...", "priority": "...", "evidence_required": false }
}
```

`scripts/journal.py`'s `_import_one_request()` creates the journal entry
first, then — only if `action` is present — calls
`scripts/actions.py`'s `create_from_fields()` with `source_activity` set to
the new `activity_id`, so the two registers are linked from creation. There
is no other path that creates an action without this explicit opt-in; a
plain activity submission never generates one implicitly.

### `web_snapshot.json`'s `homepage` key (Daily Alliance Manager homepage, R1-T06)
Public-site-only — this key does not exist in the Cowork dashboard's own
`scores_snapshot.json`/embedded snapshot, since R1-T06's own "Primary
files/components" list scopes the feature to the public site. Computed by
`scripts/build_web.py`'s `compute_homepage_aggregates()` at every build, from
`actions.csv`, `value_journal.jsonl`, and `evidence_index.csv` — never
hand-edited, never a source of truth itself.

Shape:

```
homepage: {
  generated_at_london: "YYYY-MM-DD",
  overdue_actions: [ {action_id, description, owner, due_date, priority, status, vendor}, ... ],
  due_soon_actions: [ same slim shape ],
  followups_due: [ slim journal entries whose next_action has no linked action yet ],
  per_vendor: { "<vendor>": { metrics_at_risk: [...], missing_evidence: [...] }, ... },
  by_period: {
    week|month|quarter|year: {
      period_start: "YYYY-MM-DD",
      recent_journal: [ up to 8 slim journal entries ],
      recent_journal_total: int,
      unrecognised_value: [ slim journal entries with value.amount and recognition_status=="unrecognised" ],
    }
  }
}
```

Design notes:
- Only `personal_only`-visibility rows are excluded (`_visible_for_homepage()`)
  — the rest of the `visibility` scale is a Release 2 enforcement concern
  (see the canonical-fields note above); this is a deliberately narrow,
  literal reading of R1-T06's own acceptance criteria, not full visibility
  support.
- "Metrics at risk" requires a sub-metric to have `actual != 0` (something
  measured) *and* `score < 70` — a merely unstarted sub-metric is not "at
  risk," it just hasn't begun, and treating it as such flooded this section
  with noise on a freshly-reset scorecard.
- `week`/`month`/`quarter`/`year` are calendar-based (Monday-of-week,
  1st-of-month, etc.), computed by `scripts/actions.py`'s `period_start()` —
  the same function `impact`'s period buckets below use, so the period
  selector means exactly the same date range everywhere it appears on the
  site.
- Pre-bucketed for all four periods at build time (not just the default) so
  the client-side period selector is a lookup, not a re-fetch — see R1-T06
  instruction #39 ("publish only the calculated view data needed by the
  page").

### `web_snapshot.json`'s `impact` key (My Impact dashboard, R1-T07)
Also public-site-only, same literal-scope reasoning as `homepage` above.
Computed by `scripts/impact.py`'s `compute_impact_aggregates()`, called from
`scripts/build_web.py`'s `main()`, from `value_journal.jsonl` alone —
deliberately never `actions.csv`. An activity and its optional linked
follow-up action describe the same underlying event; counting both as
separate "contributions" would double-count, so `actions.csv` is treated
purely as a follow-up-tracking register here, never a source of impact
figures.

Shape:

```
impact: {
  generated_at_london: "YYYY-MM-DD",
  by_period: {
    week|month|quarter|year: {
      period_start: "YYYY-MM-DD",
      total_contributions: int,
      organisations: [ "...", ... ],
      distinct_participants: int,
      categories: {
        relationship|commercial|strategic|operational: {
          count: int,
          evidence_coverage_pct: float,
          contribution_type_counts: { "led": n, "supported": n, ... },
          confidence_counts: { "verified": n, "unverified": n, ... },
          organisations: [ "...", ... ],
          entries: [ slim journal entries, newest first ],
        }
      },
      financial: {
        by_status: { confirmed: {currency: amount}, estimated: {...}, protected: {...}, potential: {...} },
        counts_by_status: { confirmed: n, estimated: n, protected: n, potential: n },
        awaiting_validation: { currency: amount },
        awaiting_validation_count: int,
      },
      recognition: {
        by_status: { unrecognised: {count, entries}, logged: {...}, shared: {...}, acknowledged: {...} }
      },
      narrative: "plain-language paragraph, generated deterministically",
    }
  }
}
```

Design decisions worth calling out explicitly, since none of them are
obvious from the schema alone:

- **Category mapping is a fixed partition, not a tag.** Every journal
  `type` maps to exactly one of `relationship` (`qbr`, `meeting`,
  `executive_briefing`), `commercial` (`deal_support`, `co_sell`,
  `marketplace_activity`), `strategic` (`campaign`, `workshop`), or
  `operational` (`enablement`, `escalation_support`, `program_admin`,
  `other`) via `ACTIVITY_TYPE_TO_IMPACT_CATEGORY` in `scripts/impact.py` —
  so the four category counts always sum to `total_contributions`, with no
  double-counting or gaps. `Recognition` is a fifth, orthogonal section:
  the same entries re-grouped by `recognition_status` instead.
- **"Awaiting validation" reuses the existing `confidence` field**, not a
  new one. It is the total `value.amount` across entries where the
  journal's own `confidence` field (already part of the R1-T03 schema) is
  `"unverified"` — cutting across whichever `value.status` the entry was
  filed under. This was chosen over inventing a new field because
  `confidence` already exists and already means "how sure are we this
  claim is right," which is exactly what "awaiting validation" needs to
  express.
- **Financial totals are never combined** — not across `value.status`
  (confirmed/estimated/protected/potential stay in separate buckets, per
  R1-T07's acceptance criterion) and not across currency (each status
  bucket is itself a `{currency: amount}` map, summed only when the
  currency matches). The UI (`web/assets/impact.js`) renders one row per
  status × currency combination and never sums across rows.
- **The narrative is template-generated, not AI-generated** — see
  `generate_narrative()` in `scripts/impact.py`. It only ever states figures
  already present in the same period's aggregate, so every sentence is
  traceable back to a field the UI also renders directly.
- **Joint contributions never read as sole ownership.** `contribution_type`
  values `influenced`/`supported`/`connected`/`accelerated`/`protected` are
  phrased as "contributed to" in the narrative; only `initiated`/`led` use
  "drove." `distinct_participants` (count of unique named participants
  across in-period entries) is surfaced directly in the narrative whenever
  non-zero, specifically so a solo-sounding sentence doesn't imply solo work
  when others were logged as involved.
- Same `personal_only` exclusion and calendar-based `period_start()` sharing
  as `homepage` above.

### `objectives.csv` (Objectives register, R1-T08)
Quarterly and annual role objectives, connecting daily activity to what the
role is actually meant to accomplish. One plain CSV row per objective (like
`actions.csv`, no field here is deeply nested — the two multi-value fields,
`linked_activities` and `linked_evidence`, are semicolon-separated ID lists
within a single cell rather than needing JSONL). `scripts/objectives.py` is
the only writer; the Cowork dashboard's Objectives tab and the public site's
My Impact "Objectives" section both render from the `objectives` array
injected into the snapshot by `scripts/build_dashboard.py`/`build_web.py`'s
shared `load_objectives_snapshot()` (see "Generated files" below).

Stable ID: `objective_id`, `OBJ-` prefix, own namespace.

**`period` is a single string, not a separate type + value.** Either a
quarter (`2026-Q3`) or a full year (`2026`) — `scripts/objectives.py`'s
`period_type()` infers which from the string's own format (same pattern the
category sub-metric CSVs already use for their own `quarter` column), so
there's no redundant `period_type` field to keep in sync.

**Progress is either stored or computed, never both at once** —
`progress_method` (`manual` / `count_linked` / `sum_linked_value`)
determines which:
- `manual`: `progress_pct` is set directly via `objectives.py set-progress`
  and may exceed 100 to record genuine overachievement.
- `count_linked`: progress = (number of IDs in `linked_activities`) / `target`
  × 100. `target` must be a positive number (a count).
- `sum_linked_value`: progress = (sum of `value.amount` across the linked
  activities in `value_journal.jsonl`, regardless of `value.status`) /
  `target` × 100. `target` must be a positive number (an amount, in whatever
  currency `target_unit` says). Currency consistency across the linked
  entries is not cross-checked — a deliberate R1 simplification, since
  `target_unit` itself also isn't cross-checked against each entry's
  `value.currency`. Revisit if objectives start mixing currencies in
  practice.

Either way, `scripts/objectives.py`'s `compute_progress()` always returns
both a `raw_pct` (uncapped — can exceed 100) and an `official_pct`
(`min(100, raw_pct)`), plus `overachievement_pct` (`max(0, raw_pct - 100)`).
**The UI must always display both** — R1-T08's acceptance criterion is
explicit that overachievement above 100% is never silently hidden behind a
capped progress bar. `compute_progress()` is never called client-side; it
runs once at build time (`load_objectives_snapshot()`, shared by both
`build_dashboard.py` and `build_web.py`) and the result is injected onto
each row as a `progress` object, so the Cowork dashboard and the public
site always agree on a given objective's percentage without either
recomputing it.

Status vocabulary: `on_track` (default), `at_risk`, `completed`, `missed`.
`completed`/`missed` are terminal. Same discipline as `actions.csv`: direct
`edit` can only move an objective between `on_track`/`at_risk` — every other
transition goes through its own command (`at-risk`/`resolve-risk`/
`complete`/`miss`) so required side effects always happen. Marking an
objective `at_risk` requires both `at_risk_reason` and `recovery_action`
(R1-T08 acceptance criterion) — `scripts/validate_data.py` rejects a
hand-edited row that sets `status=at_risk` without both fields present, the
same way it already does for `actions.csv`'s status-consistency rules.

Key fields: `objective` (the statement itself), `success_measure` (how
you'll know it was achieved — free text, not enforced against
`progress_method`), `target`/`target_unit`/`target_date`,
`communardo_priority`/`atlassian_priority` (`low`/`medium`/`high`, or blank
— how important this objective is to each side of the alliance,
independently), `linked_activities`/`linked_evidence` (semicolon-separated
`ACT-`/`EVD-` ids — attached via `objectives.py link-activity`/
`link-evidence`, or set in bulk at `create`/`edit` time), `at_risk_reason`/
`recovery_action`, `completed_at`/`completion_note`, `missed_at`/
`missed_reason`, `vendor` (defaults to `app_config.json`'s `default_vendor`),
`visibility` (defaults to `communardo_internal`, not `personal_only` —
objectives are role-level commitments, not private journal notes, so the
more sharing-friendly default was a deliberate choice distinct from
`actions.csv`'s `personal_only` default), plus the canonical
`created_at`/`updated_at`/`created_by`/`updated_by`/`notes`.

**Objective review export (instruction #52).** `objectives.py export
[--period <period>]` writes a deterministic Markdown file to
`reports/Objective_Review_<period>.md` — plain string templates over
already-computed data (same no-AI discipline as `impact.py`'s narrative),
listing every objective's statement, status, progress (official % plus any
overachievement, never hidden), priorities, linked activities, and any
at-risk/completion/miss detail. Triggered from the Cowork dashboard's
Objectives tab via an "Export review" button (same "stage locally, confirm
via chat" pattern as every other Objectives action).

### Contacts register (Contacts Phase 1 / R3-T01)
Stakeholder identity resolution and profile history — Steve requested this
pulled forward ahead of its original roadmap sequence position (it was
reserved as a future R3 task; see the `participants` field note above).
Three files, each with one job, mirroring the "current view vs. append-only
evidence trail" split R2-T01 established for `metric_results_history.csv`:

- `contacts.csv` — one row per contact, the CURRENT profile view only.
- `contact_aliases.csv` — known name spellings/variants per contact.
- `contact_evidence.jsonl` — append-only. One row per extracted fact or
  observation, ever. Never edited or deleted.
- `contact_evidence_fields.json` — config, not a register. Controlled
  vocabulary for evidence `field` values, grouped for the summary (see
  below): `identity` (title, company, email, ...), `engagement` (topics,
  priorities, concerns, objectives, blockers, interests), `personal`
  (likes, dislikes, preferences, communication style, personality cues),
  `relationship` (influence level, stakeholder role, relationship strength
  signals, key dates), `actions` (commitments, follow-ups), `system`
  (system-generated audit/review entries, never extracted content —
  `merge_event`, `possible_duplicate`; see the Phase 2 section below).
  Add a field by editing this file — no code change needed.

**Why a contact's "current value" for a field is derived, not stored
directly.** `contacts.csv`'s columns (title, company, email, ...) are a
*cache*, refreshed by `contacts.py add-evidence` — the actual source of
truth is always the most recent non-`superseded_by` evidence row for that
`(contact_id, field)` in `contact_evidence.jsonl`. This is what makes
"preserve all prior evidence... even when the current profile view
changes" true by construction rather than by discipline: nothing in this
codebase ever deletes or rewrites an evidence row, it only marks an older
one's `superseded_by` when a newer, at-least-as-well-supported piece of
evidence for the same field arrives (`CONFIDENCE_RANK`:
`low_confidence` < `probable` < `confirmed`). A lower-confidence update
never overwrites a higher-confidence existing value.

`contacts.csv` columns: `contact_id, status, canonical_name,
raw_extracted_name, title, seniority, department, business_unit, company,
affiliation, region, country, location, email, phone, relationship_owner,
stakeholder_role, influence_level, relationship_strength, vendor,
visibility, merged_into, first_seen_at, last_interaction_at, summary,
summary_updated_at, created_at, updated_at, created_by, updated_by, notes`

- `status`: `provisional` (created via `find-or-create` when no confident
  match exists) → `confirmed` (via `confirm`) → terminal `merged` (via
  `merge`/`resolve-match`, `merged_into` set) or `archived`. Same
  discipline as `actions.csv`/`objectives.csv`: `edit` can only move a
  contact between `provisional`/`confirmed`; every other transition goes
  through its own command.
- `affiliation`: `communardo`, `atlassian`, `customer`, `partner`, `other`,
  or blank.
- `influence_level`: `low`/`medium`/`high`/`critical`, or blank.
- `relationship_strength`: `weak`/`developing`/`strong`/`at_risk`, or blank.
- A merged contact's row is **never deleted or rewritten** — `merged_into`
  points at the surviving `contact_id`, and every evidence/alias row that
  referenced the merged-away id keeps doing so unchanged.
  `contacts.py`'s `resolve_canonical()` follows the `merged_into` chain to
  find where a given id's history now lives.

`contact_evidence.jsonl` fields: `evidence_id, contact_id, extracted_at,
source_type, source_ref, field, value, confidence, sensitivity,
reviewer_status, superseded_by, rationale, meeting_ref, created_by`

- `source_type`: `meeting_note`, `transcript`, `audio_summary`, `document`,
  `slide_deck`, `pdf`, `spreadsheet`, `email_summary`, `manual_note`.
- `confidence`: `confirmed`, `probable`, `low_confidence` — this is a
  three-way split, deliberately simpler than `value_journal.jsonl`'s
  four-value `confidence` scale (`confirmed`/`supported`/`estimated`/
  `unverified`), because it needs to double as an ordered rank
  (`CONFIDENCE_RANK`) for the supersession comparison above; a fourth tier
  would need a judgement call about where it ranks that isn't obviously
  correct either way.
- `sensitivity`: `standard`, `subjective`, `sensitive`. `subjective` is
  what separates an opinion/observation ("prefers concise updates") from a
  fact ("title: VP Partnerships") in the generated summary — see the
  Profile Summary section below. `sensitive` is a placeholder for
  governance policy to act on; nothing in Phase 1 auto-restricts a
  `sensitive`-flagged row yet, this is future review-queue/redaction work.
- `reviewer_status`: `unreviewed` (default on every new evidence row —
  nothing is auto-confirmed), `confirmed`, `rejected`. Phase 1 has no UI
  for a human to change this yet (that's Phase 3's Contacts tab); the
  field exists now so Phase 3 has somewhere to write to.
- `superseded_by`: blank, or another row's `evidence_id` — set
  automatically by `add-evidence` when a new value for the same field
  displaces the previous current value. `validate_data.py` checks this
  points at a real `evidence_id` that exists somewhere in the file.

**Identity resolution (`scripts/contacts.py find_candidate_matches()` /
`match_contact()`).** Plain-stdlib name similarity
(`difflib.SequenceMatcher`, no external fuzzy-matching dependency — this
project has near-zero third-party Python dependencies and this didn't
seem worth breaking that for) combined with corroborating signals:

- An exact `email` match auto-matches on its own (score 1.0) regardless of
  name similarity — the strongest possible signal.
- A name match alone auto-matches only at/above `AUTO_MATCH_THRESHOLD`
  (0.90) — in practice this means a near-exact name spelling PLUS a
  matching company or title pushing the combined score over the bar, not
  fuzzy name similarity by itself.
- Anything at/above `REVIEW_THRESHOLD` (0.55) but below the auto-match bar
  is `needs_review` — surfaced for a human decision (`resolve-match`),
  never silently merged.
- Below `REVIEW_THRESHOLD`, or no name-similar contact at all, becomes a
  new provisional contact via `find-or-create`.

This is the concrete mechanism behind two acceptance rules that could
otherwise pull in opposite directions: "must not treat spelling
differences alone as a new person when other evidence suggests the same
identity" (handled by the corroborating-signal boost) and — the necessary
corollary neither rule states explicitly but that any identity-resolution
system has to get right — ambiguous evidence must not be silently treated
as the *same* person either (handled by `needs_review` never auto-acting).

**Profile summary (`compute_profile_summary()`).** Deterministic,
template-generated from already-computed evidence — no AI call, same
discipline as `impact.py`'s narrative and `objectives.py`'s export.
Explicitly separates confirmed facts, probable/unconfirmed evidence, and
`subjective`-flagged observations into three distinct lists (never
blended into one paragraph), states the "originally extracted as X, later
confirmed as Y" alias history when `raw_extracted_name` and
`canonical_name` differ, lists open `commitment`/`action`/`follow_up`
evidence as open actions, and flags which of `title`/`company`/`email`
are still missing. `contacts.py summary --contact-id <id> --save` writes
the rendered text to `contacts.csv`'s `summary` column.

**Privacy / data minimisation.** No field is hard-excluded in Phase 1 —
Steve's explicit direction was that the `sensitivity`/`reviewer_status`
flag-for-review mechanism above is sufficient for now rather than
hard-blocking specific categories of personal information (health,
family, beliefs, etc.) at extraction time. `visibility` reuses the
existing platform-wide scale (`personal_only` through `public`) so
contacts participate in whatever centralised visibility enforcement
R2-T04 ("Implement controlled visibility and redaction rules") ends up
building, rather than inventing a parallel scheme.

**What Phase 1 deliberately did NOT include** (now built in Phase 2 unless
noted): a "read this document and extract everyone in it" ingestion
command. Still not built: a Contacts tab in the Cowork dashboard or public
site (Phase 3); an org chart / influence map view (Phase 4); and wiring
`value_journal.jsonl`'s `participants` field to real `contact_id`s (noted
above, a natural Phase 2/3 follow-on, not committed to a specific phase
yet). Raw audio transcription is still out of scope end-to-end — `ingest`
needs already-transcribed text (a summary, a transcript export, etc.), not
a raw audio file, since no speech-to-text tool is available in this
environment.

### Contacts register — batch document ingestion (Contacts Phase 2)
The `ingest` command lets a whole document's worth of extracted people and
facts be recorded in one call, instead of one `add-evidence` call per
fact. It reuses Phase 1's identity-resolution and evidence-recording logic
directly — `scripts/contacts.py`'s `record_evidence_row()` is the same
pure, file-I/O-free function `add-evidence` calls, and `cmd_ingest` reads
`contacts.csv`/`contact_evidence.jsonl` once per batch rather than once
per fact.

**Practical workflow.** When Steve shares a meeting note, transcript,
slide deck, PDF, or other document in a Cowork session, Claude reads it,
identifies every person mentioned plus whatever facts/observations were
said about them, builds a JSON payload matching the schema below, and runs
`python3 scripts/contacts.py ingest --file <payload>.json` (with
`--dry-run` first to preview, matching this project's usual
draft-then-apply discipline). This is the concrete implementation of
"automatic" extraction promised in the original spec — automatic in the
sense that Claude does the reading/structuring/CLI call, not that an
unattended background job watches for new files (this platform has no
backend server to run one).

**Payload schema** (JSON file passed via `--file`):

```json
{
  "source_type": "meeting_note",
  "source_ref": "2026-07-21 QBR notes",
  "extracted_at": "2026-07-21",
  "people": [
    {
      "name": "Jamie Chen",
      "company": "Acme", "title": "VP Partnerships", "email": "...",
      "vendor": "...", "visibility": "...",
      "evidence": [
        {
          "field": "priority", "value": "Wants a joint QBR next quarter",
          "confidence": "probable", "sensitivity": "standard",
          "rationale": "...", "meeting_ref": "..."
        }
      ]
    }
  ]
}
```

`source_type` and top-level `source_ref`/`extracted_at` are defaults every
evidence fact inherits unless it sets its own. `company`/`title`/`email`
on a person are used only for identity resolution and (if a new contact is
created) the initial profile row — they are not themselves recorded as
evidence facts; log them explicitly under `evidence` too (field `title`,
`company`, etc.) if they should also appear in the evidence trail.

**Validation is all-or-nothing.** `validate_ingest_payload()` checks the
*entire* payload — every person's name, every evidence item's `field`/
`value`/`confidence` (must be one of `VALID_CONFIDENCE`), every
`source_type`/`visibility`/`sensitivity` against their controlled
vocabularies — before `cmd_ingest` writes anything. One malformed fact
anywhere in a document rejects the whole batch rather than silently
applying part of it; a completion report/error list is printed instead.

**Identity resolution per person** (`resolve_or_create_for_ingest()`):
unlike `find-or-create` — which only *reports* on an ambiguous match and
waits for a human — `ingest` always assigns a usable `contact_id` to every
person, since a whole document's worth of facts must not be dropped or
blocked by one ambiguous name:
- `matched` (score ≥ `AUTO_MATCH_THRESHOLD`): reuses the existing
  `contact_id`, no new row.
- `needs_review` (score ≥ `REVIEW_THRESHOLD` but below auto-match): gets
  its **own new provisional contact** — never silently merged into the
  candidate — plus a `possible_duplicate` evidence row on the new contact
  naming the candidate `contact_id`, score, and reasons. This is how the
  "never drop the ambiguity, never silently resolve it either way" rule is
  implemented for batch ingest specifically.
- `new`: an ordinary new provisional contact, same as `find-or-create`.

Run `contacts.py resolve-match --contact-id <new> --matched-contact-id
<candidate> --verdict same|different` once a `needs_review` flag has been
checked — `same` merges the two (via the existing `merge` logic), keeping
both records' evidence history; `different` just records the verdict.

**`possible_duplicate` evidence field** (added to
`contact_evidence_fields.json`'s `system` group, alongside `merge_event`):
a system-generated review flag, not extracted content. `compute_profile_summary()`
lists any *unresolved* (`superseded_by` blank) `possible_duplicate`
evidence as a `NEEDS REVIEW` line near the top of the rendered summary —
right after the identity line, before aliases/confirmed/probable/
subjective — and returns it separately as `possible_duplicates` in the
structured result, so a provisional contact's ambiguous-match status is
never buried under ordinary profile content. It is excluded from the
confirmed/probable/subjective evidence lists (same treatment as
`merge_event`) since it isn't a fact about the person.

**`--dry-run`**: runs the full identity-resolution and evidence-recording
logic in memory (so the preview shows the actual `contact_id`s/decisions
that would result) but skips the final `write_contacts()`/`write_evidence()`
calls — nothing is persisted. Provisional `contact_id`s shown in a dry run
are a preview, not a reservation; running for real afterward assigns the
next available id at that time.

### Contacts register — Cowork dashboard tab (Contacts Phase 3)
`scripts/build_dashboard.py`'s `load_contacts_snapshot()` embeds every
contact row plus its precomputed `compute_profile_summary()` result and
`possible_duplicate_flags()` (structured `{evidence_id, value,
candidate_id}` — the candidate id is parsed out of the evidence log's free
text so the UI can link to it without re-parsing) into `SNAPSHOT.contacts`;
`SNAPSHOT.contact_evidence_fields` (the controlled vocabulary minus the
`system` group) populates the Add Evidence form's field dropdown. The
dashboard never reimplements the summary/matching logic in JS — it only
renders what `contacts.py` already computed.

The Contacts tab lists/searches/filters contacts and expands a row into
its profile summary, any unresolved `possible_duplicate` review flags
(with one-click "same person — merge" / "different person" actions), and
inline forms for set-canonical-name, add-evidence, and merge-into. Every
write action follows the same "stage locally, confirm via chat" pattern
as the Actions/Objectives tabs (`sendPrompt()` composes a message asking
Claude to run the matching `contacts.py` CLI command, then rebuild and
push) — nothing is written to `data/` until that message is sent. "+ Add
Contact" opens a modal for `contacts.py create` (skips identity
resolution — for an unsure case, ask Claude in chat to run
`find-or-create` instead, which checks for a match first).

### Contacts register — public-site mirror (Contacts Phase 4)
The GitHub Pages site is a genuinely public URL — a categorically bigger
exposure surface than the Steve-only Cowork dashboard, and contacts carry
real people's PII. Confirmed with Steve before building this: the public
mirror uses a **stricter, separate, allow-list policy**, not the
`_visible_for_homepage()`/`_visible_for_impact()` bar the rest of the
public site uses (which only excludes `personal_only` — fine for Steve's
own activity log, not fine for third parties' profile data).

`scripts/contacts.py`'s `PUBLIC_VISIBILITY_TIERS = {"atlassian_shareable",
"customer_approved", "anonymised", "public"}` / `is_public_visible(row)`:
a contact only appears on the public site once someone deliberately sets
its `visibility` to one of those four values — every contact's real
default (`communardo_internal`, set by `create`/`find-or-create`) stays
internal-only unless explicitly changed via `edit --visibility`. Terminal
contacts (`merged`/`archived`) never appear regardless of visibility.

`public_contact_view(row, evidence_rows)` then strips even a cleared
contact down further before it's published: no `email`/`phone` (business-
card details aren't published without a separate, explicit ask), no
evidence with `sensitivity` = `sensitive` or `subjective` (opinions about
a real person have no place on a public page), no `merge_event`/
`possible_duplicate` system rows, and none of Steve's internal working
fields (`relationship_owner`, `notes`, `raw_extracted_name`/alias history).
What remains is business-card identity plus objective relationship
signals — `canonical_name`, `title`, `company`, `affiliation`, `region`,
`country`, `stakeholder_role`, `influence_level`, `relationship_strength`,
and any non-sensitive/non-subjective evidence facts — the minimum needed
for an org/influence map.

`scripts/build_web.py`'s `compute_public_contacts()` calls both functions
and writes the result to `web_snapshot.json`'s `contacts` key (a
completely different, much slimmer payload than the Cowork dashboard's
`SNAPSHOT.contacts` — same key name, two different files, never confused
at runtime since the dashboard embeds its own snapshot directly and the
public site fetches `web_snapshot.json` separately). `web/index_template.html`'s
Contacts tab renders this read-only: an org/influence map (contacts
grouped into cards by company, each entry showing an influence-coloured
dot and a relationship-strength badge) plus a flat table. There are no
write actions here — the public mirror has no `sendPrompt`-equivalent (no
chat context exists on a plain public webpage); to change what's visible,
edit a contact's `visibility` from the Cowork dashboard or CLI.

### Generated files (not sources of truth — do not hand-edit)
- `scores_snapshot.json` — output of `scripts/scoring.py`. `scripts/build_dashboard.py` loads this and augments it in memory (adding `actions`, `objectives`, `app_config`, etc.) before embedding the result as the Cowork dashboard artifact's `SNAPSHOT` — the augmented version is never written back to `scores_snapshot.json` on disk.
- `web_snapshot.json` — output of `scripts/build_web.py`, fetched at runtime by the public GitHub Pages site. Includes the `homepage` (R1-T06), `impact` (R1-T07), and `objectives` (R1-T08) keys documented above.
- `embedded_snapshot.json` — orphaned/stale artifact from an earlier build approach, no longer read by any script. Excluded from `git push` (`scripts/git_push.sh`). Left in place because the sandbox cannot delete files; safe to ignore.

### Deprecated/orphaned files
- `coselling.csv`, `third_party_vendors.csv` — merged into `third_party_coselling.csv`. Each file's only content is a one-line deprecation notice. Not read by any script. Left in place because the sandbox cannot delete files.

## Backups

`scripts/migrations/run_migrations.py` copies the entire `data/` directory to
`backups/<timestamp>/` before applying any pending migration. `backups/` is
git-ignored (see `.gitignore`) — it is a local safety net, not something
pushed to GitHub, to keep the repository from accumulating full historical
data snapshots on every schema change.
