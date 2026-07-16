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
| `financial_currency` | no | `"EUR"` | One of `EUR, USD, GBP, CHF, SEK, NOK, DKK` — extend the list in `scripts/config.py` as needed |
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
of free-text names — there's no contacts register yet, see R3-T01),
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

### Generated files (not sources of truth — do not hand-edit)
- `scores_snapshot.json` — output of `scripts/scoring.py`, consumed by the Cowork dashboard artifact.
- `web_snapshot.json` — output of `scripts/build_web.py`, fetched at runtime by the public GitHub Pages site. Includes the `homepage` (R1-T06) and `impact` (R1-T07) keys documented above.
- `embedded_snapshot.json` — orphaned/stale artifact from an earlier build approach, no longer read by any script. Excluded from `git push` (`scripts/git_push.sh`). Left in place because the sandbox cannot delete files; safe to ignore.

### Deprecated/orphaned files
- `coselling.csv`, `third_party_vendors.csv` — merged into `third_party_coselling.csv`. Each file's only content is a one-line deprecation notice. Not read by any script. Left in place because the sandbox cannot delete files.

## Backups

`scripts/migrations/run_migrations.py` copies the entire `data/` directory to
`backups/<timestamp>/` before applying any pending migration. `backups/` is
git-ignored (see `.gitignore`) — it is a local safety net, not something
pushed to GitHub, to keep the repository from accumulating full historical
data snapshots on every schema change.
