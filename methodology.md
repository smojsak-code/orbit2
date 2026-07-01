# Orbit2 Scoring Methodology

## How the overall score is built

Every sub-metric is scored 0–100 as `min(100, actual / target * 100)`. Sub-metric scores are combined into a category score using the weights in each CSV's `weight_pct_in_category` column (must sum to 100 within a category). Category scores are combined into the overall score using the weights in `data/weights.json` (must sum to 100 per vendor). Everything is recalculated by running `scripts/scoring.py`, which writes `data/scores_snapshot.json` — the file the dashboard reads.

Nothing is a black box: every number on the dashboard traces back to a row in a CSV with a target, an actual, a source, and a weight.

## Keeping metrics aligned with the vendor (when Atlassian — or another vendor — changes their program)

Vendors change their partner programs regularly: a registration type gets renamed, a metric gets retired, a new incentive gets added. Orbit2 is built so this never means a rebuild:

- **The category list itself is a config file, not code.** `data/categories.json` is the registry of every category (label + which CSV backs it). Add a whole new category by adding an entry there — no code changes.
- **Sub-metrics are just CSV rows per quarter.** Each quarter you add rows is a clean slate for that category: leave a sub-metric out and it stops counting (but its history stays in the file); add a new sub-metric name and it starts counting; change a weight/target for a name that already exists and it's amended.
- **`scripts/metric_manager.py` is the tool for making these changes deliberately and with a paper trail.** Commands: `add-category`, `deprecate-category`, `set-category-weight`, `add-submetric`, `amend-submetric`, `deprecate-submetric`, and `diff-quarter` (which auto-detects everything that changed between two quarters of a category and logs it for you — this is the fastest path when you've just entered a new quarter's numbers and want the changelog to write itself).
- **Every change is logged to `data/metric_changelog.csv`** with a reason and source, and shown on the dashboard's Metric Changelog panel — so months later you can see not just that your registrations score moved, but that it moved because Atlassian retired PVR and introduced two new registration types.
- **On the dashboard**, the "Manage Metrics" panel lets you view and edit every category's sub-metrics (weights, targets, add/remove rows) and stage the change; clicking "Submit changes to Claude" sends the exact diff to chat so Claude can apply it with `metric_manager.py` and confirm anything ambiguous with you first. A separate "Import vendor program update" drop zone is for documents that describe a *change to the metrics themselves* (a program guide, a partner terms update) — distinct from the Evidence Library drop zone, which is for evidence behind an *existing* metric's score.
- **Weight sums are always checked, never silently allowed to drift.** `scripts/scoring.py` reports a `weight_check` per category and overall; if it isn't 100, that's flagged on the console and worth fixing before you trust the score.

## Category weights (Atlassian, default — edit in `data/weights.json`)

| Category | Weight | What it captures |
|---|---|---|
| Sales Performance | 18% | Pipeline growth, bookings vs quota, win rate on registered deals |
| Registrations | 12% | Deal Registration, PVR (Partner Value Registration), Service Registration volume & approval |
| Business Planning & QBRs | 12% | QBR cadence, joint business plan attainment, action item closure |
| 3rd Party Vendors & Co-selling | 12% | Joint engagements with SIs/ISVs, revenue influenced via referrals, AWS ACE deals, Google co-sell engagements, GSI joint pipeline — merged into one category since both measure the same thing: revenue and pipeline generated *with* another party rather than solo |
| Solutions | 12% | Number of solutions created, number sold, revenue generated, and breadth of solution verticals (Finance, Automotive, Pharmaceutical, etc.) |
| Services | 10% | Services revenue sold to clients, number of clients who purchased services |
| Marketing | 8% | Co-marketing campaigns, MDF utilization, marketing-sourced leads |
| Market Visibility | 8% | Marketplace rating, directory profile, press/analyst mentions, case studies |
| AI Adoption | 8% | Internal AI tool adoption, AI-related engagements delivered, AI certifications |

These weights are a starting point reflecting what typically matters most to an Alliance Manager (revenue and registration health first, visibility and ecosystem signals second). **Change them any time** — there's no "correct" weighting, only the one that matches what your leadership actually cares about this year.

### Solutions category detail

`data/solutions.csv` scores four sub-metrics (created, sold, revenue, vertical coverage). Vertical coverage is a ratio of verticals actively served vs. a target count — the *which verticals* detail (Finance, Automotive, Pharmaceutical, etc.) lives separately in `data/solution_verticals.csv` as a per-vertical breakdown (solutions count, solutions sold, revenue) so the dashboard can show a vertical-by-vertical table without that detail distorting the weighted score.

## Evidence Library

`evidence_library/` stores every piece of source material — screenshots, CSV/Excel exports, docs, saved articles — that a metric's "actual" value was taken from. `data/evidence_index.csv` is the ledger: one row per file, tagged with vendor, category, sub-metric, quarter, and a `dedupe_key` (`vendor|category|sub_metric|quarter`).

**Deduplication rule:** when a new piece of evidence is filed for a `dedupe_key` that already has an `active` row, `scripts/evidence_ingest.py` automatically marks the old row `superseded` (pointing at the new evidence_id) and the new row becomes `active`. Nothing is deleted — superseded evidence stays in its folder for audit history — but only the active row's data feeds the scorecard, so you never end up averaging an old screenshot with a new one for the same quarter.

**Workflow (automatic — no confirmation step):**
1. Drop the file onto the dashboard's Evidence Library panel (or `evidence_library/inbox/` via Finder, or attach it in chat), optionally add a note, then click **Submit for analysis**.
2. Claude processes it immediately, without pausing to ask clarifying questions: relevance check first — is this actually about Communardo's performance as the vendor's partner? If not, it's **rejected**: nothing is filed or changed, and you're told why. If it is relevant, Claude extracts the number, picks the best-fit category/sub-metric/quarter, updates the `actual` value in the relevant CSV, and runs `scripts/evidence_ingest.py` to file it and apply the dedupe rule above.
3. `scripts/scoring.py` is re-run and the dashboard refreshed automatically as part of the same step.

The only time this stops to ask you something is if a file is genuinely ambiguous between two categories — otherwise it's a one-click, one-response action. This is still a Claude-in-the-loop process rather than a deterministic OCR pipeline (reading a screenshot and judging relevance is inherently a judgment call), but the loop happens in a single turn, not a back-and-forth.

**Searching past evidence:** the Evidence Library panel has a search box (filename, category, sub-metric, quarter, status, description — matches active and superseded evidence). The same search is available from the terminal: `python3 scripts/evidence_ingest.py search "<text>"` (add `--status active` or `--status superseded` to narrow it).

## Why sub-metrics, not one raw number, per category

A single "sales score" hides whether you're behind on pipeline, quota, or win rate — three different problems needing three different fixes. Each category is broken into 2–4 sub-metrics so a low score always points to a specific, actionable gap.

## Data sources and how they get in

Every row cites a `source` (CRM export, portal screenshot, finance report, etc.) because the data will mostly arrive as CSVs, Excel exports, or screenshots of Atlassian/AWS/Google partner portals — Communardo doesn't have API access to Atlassian's own partner data. When you hand over a screenshot or spreadsheet, the update is: extract the numbers → append/update the relevant CSV row → re-run `scoring.py` → refresh the dashboard. That extraction step is manual-by-necessity (no vendor exposes a partner-scoring API), which is the main limiting factor on how "real-time" this can ever be — see the honest assessment in the main reply.

## Adding a new vendor (AWS, Google, GSI, etc.)

1. Add a new entry to `data/weights.json` with category weights that sum to 100 for that vendor.
2. Add rows to each category CSV with that vendor's name — same schema, same files, just a new `vendor` value.
3. Re-run `scripts/scoring.py`. The dashboard vendor selector will pick it up automatically once the artifact is refreshed with the new snapshot.

## Market visibility & news sentiment

`data/news_log.csv` is appended to automatically every 12 hours by the scheduled news-monitoring task, which searches the web for Communardo mentions and tags each one `positive` / `neutral` / `negative` with a confidence level. This log feeds the "Press/analyst mentions volume" sub-metric and is shown as a standalone feed on the dashboard — sentiment classification is a judgment call (made by Claude reading each article), not a deterministic algorithm, so treat borderline calls as a prompt, not a verdict.

## Sub-metric descriptions

Every row in every category CSV has a `description` column — a plain-language explanation of what that sub-metric measures and why it matters (e.g. "Closed-won bookings this quarter against the quota set with Atlassian/leadership. The single clearest signal of commercial performance."). These are curated by hand when a sub-metric is added, and are what powers the explanations in the dashboard's Reports tab and generated reports — nobody has to remember what "PVR approval rate" means six months from now.

## Key deals register

`data/deals.csv` is a supporting detail table, separate from the weighted score: one row per closed deal, with company name, close date, TCV/ACV, currency, products sold, services sold, vertical, and Atlassian partner tier (Strategic / Enterprise / Midmarket / SMB). It's not part of any category's weighted calculation — it exists purely so reports can show *which specific deals* are behind the Sales Performance and Solutions/Services numbers. Add rows directly, or submit deal evidence (a closed-won notification, CRM export, etc.) through the Evidence Library and Claude will extract the deal detail into this file.

## Reports: in-dashboard view + Word / PDF / PowerPoint export

The dashboard has a **Reports** tab (next to **Dashboard**) that renders a live report page — the same explanation-per-sub-metric detail described above, the key deals table, and a full metric glossary (every category and sub-metric, in one place) — always current, since it reads straight from the same snapshot as the main dashboard.

Three download buttons generate an actual file on demand, each re-running `scripts/scoring.py` first so the export always matches the CSVs at the moment you click:

- **Word (.docx)** — `scripts_node/generate_report.js <vendor>`, built with the `docx` npm package. Includes a title page, category-by-category detail tables with description rows, the key deals table with totals, and the full glossary appendix.
- **PDF** — the same Word document, converted with LibreOffice headless (`soffice.py --headless --convert-to pdf`) via the docx skill's bundled conversion script. No separate PDF template to maintain — one source of truth.
- **PowerPoint (.pptx)** — `scripts_node/generate_pptx.js <vendor>`, built with `pptxgenjs`: a 6-slide deck (title, overall score with a bar chart of all categories, category breakdown score cards, key deals, market visibility & sentiment with a pie chart, and a methodology/next-steps close). When most categories are still at zero (a clean-slate scorecard awaiting real data), the deck adds an explanatory caption rather than presenting an oddly empty chart.

All three are wired to the dashboard buttons via `sendPrompt()`, same pattern as the original Generate Report button — clicking gives immediate visual feedback (button disables, text changes to "Requested — check chat ↓") while Claude runs the pipeline and posts the finished file back in chat.
