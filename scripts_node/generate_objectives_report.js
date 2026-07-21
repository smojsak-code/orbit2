/**
 * Orbit2 Objectives Progress Report generator.
 *
 * Reads a pre-computed objectives snapshot (a JSON file containing
 * {objectives: [...], app_config: {...}}, where each objective row already
 * carries a `detail` object produced by scripts/objectives.py's
 * compute_objective_detail() — progress, linked evidence, linked
 * activities, action points, and an auto-updating narrative summary).
 * This script only renders that pre-computed data into a Word document; it
 * never recomputes progress or narrative itself, so the report can never
 * disagree with the dashboard's Objectives tab or the public My Impact
 * tab's click-through detail view — same "compute once in Python, node
 * only renders" discipline generate_report.js already uses for
 * scores_snapshot.json.
 *
 * Every run is timestamped (both in the filename and inside the document
 * body/header), so Steve can regenerate this at any time to get a fresh,
 * dated record of progress — this is the whole point of the feature: an
 * on-demand, always-current progress report with dates and time stamps,
 * grouped by the five objective categories (Relationship, Commercial,
 * Strategic, Operational, Recognition), with evidence/example references
 * and action points for each objective.
 *
 * Usage: node generate_objectives_report.js <path-to-objectives-snapshot.json>
 * Writes: ../reports/Orbit2_Objectives_Progress_Report_<YYYY-MM-DD_HHMM>.docx
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType, PageNumber,
  Header, Footer,
} = require("docx");

const REPORTS_DIR = path.join(__dirname, "..", "reports");
const snapshotPath = process.argv[2];
if (!snapshotPath || !fs.existsSync(snapshotPath)) {
  console.error("Usage: node generate_objectives_report.js <path-to-objectives-snapshot.json>");
  process.exit(1);
}
const input = JSON.parse(fs.readFileSync(snapshotPath, "utf8"));
const objectives = input.objectives || [];

const fallbackConfig = { user_display_name: "Steve Mojsak", job_title: "Atlassian Alliance Manager", company: "Communardo" };
const appConfig = Object.assign({}, fallbackConfig, input.app_config || {});
const preparedForLine = `Prepared for ${appConfig.user_display_name}${appConfig.job_title ? ", " + appConfig.job_title : ""}, ${appConfig.company}`;

const now = new Date();
const generatedDate = now.toISOString().slice(0, 10);
const generatedTime = now.toTimeString().slice(0, 5);
const generatedStamp = `${generatedDate} ${generatedTime}`;
const filenameStamp = `${generatedDate}_${generatedTime.replace(":", "")}`;

// Fixed section order — matches CATEGORY_LABELS in scripts/objectives.py,
// so the report's structure always mirrors the dashboard/public-site
// category filters. Any objective missing a category (pre-migration_004
// rows) falls into "Uncategorised" at the end rather than being dropped.
const CATEGORY_ORDER = ["relationship", "commercial", "strategic", "operational", "recognition"];
const CATEGORY_LABELS = {
  relationship: "Relationship", commercial: "Commercial", strategic: "Strategic",
  operational: "Operational", recognition: "Recognition",
};
const STATUS_LABELS = { on_track: "On track", at_risk: "At risk", completed: "Completed", missed: "Missed" };
const STATUS_COLORS = { on_track: "16A34A", at_risk: "D97706", completed: "2563EB", missed: "DC2626" };

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const TABLE_WIDTH = 9360;

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: "1E293B", type: ShadingType.CLEAR },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", size: 18 })] })],
  });
}
function cell(text, width, opts = {}) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    children: [new Paragraph({ children: [new TextRun({ text: String(text ?? "—"), size: 18, ...opts })] })],
  });
}
function emptyNote(text) {
  return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, italics: true, size: 18, color: "6B7280" })] });
}

// ---- Executive summary ----
const statusCounts = objectives.reduce((acc, r) => { const s = r.status || "on_track"; acc[s] = (acc[s] || 0) + 1; return acc; }, {});
const categoryCounts = objectives.reduce((acc, r) => { const c = r.category || "uncategorised"; acc[c] = (acc[c] || 0) + 1; return acc; }, {});
const avgProgress = objectives.length
  ? Math.round(objectives.reduce((sum, r) => sum + ((r.detail && r.detail.progress && r.detail.progress.official_pct) || 0), 0) / objectives.length)
  : 0;

const summaryRows = [
  new TableRow({ children: [headerCell("Metric", 4680), headerCell("Value", 4680)] }),
  new TableRow({ children: [cell("Total objectives", 4680), cell(String(objectives.length), 4680, { bold: true })] }),
  new TableRow({ children: [cell("On track", 4680), cell(String(statusCounts.on_track || 0), 4680)] }),
  new TableRow({ children: [cell("At risk", 4680), cell(String(statusCounts.at_risk || 0), 4680)] }),
  new TableRow({ children: [cell("Completed", 4680), cell(String(statusCounts.completed || 0), 4680)] }),
  new TableRow({ children: [cell("Missed", 4680), cell(String(statusCounts.missed || 0), 4680)] }),
  new TableRow({ children: [cell("Average progress across all objectives", 4680), cell(`${avgProgress}%`, 4680, { bold: true })] }),
];
const summaryTable = new Table({ width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [4680, 4680], rows: summaryRows });

const categoryOverviewRows = CATEGORY_ORDER
  .filter(c => categoryCounts[c])
  .map(c => new TableRow({ children: [cell(CATEGORY_LABELS[c], 4680), cell(String(categoryCounts[c]), 4680)] }));
if (categoryCounts.uncategorised) {
  categoryOverviewRows.push(new TableRow({ children: [cell("Uncategorised", 4680), cell(String(categoryCounts.uncategorised), 4680)] }));
}
const categoryOverviewTable = categoryOverviewRows.length ? new Table({
  width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [4680, 4680],
  rows: [new TableRow({ children: [headerCell("Category", 4680), headerCell("Objectives", 4680)] }), ...categoryOverviewRows],
}) : emptyNote("No objectives on file yet.");

// ---- Per-objective detail block ----
function objectiveBlock(r) {
  const d = r.detail || {};
  const progress = d.progress || {};
  const status = d.status || "on_track";
  const overNote = progress.overachievement_pct > 0 ? ` (+${progress.overachievement_pct}% overachievement)` : "";

  const infoRows = [
    new TableRow({ children: [cell("Period", 2200), cell(d.period || "—", 3160), cell("Status", 1900), cell(STATUS_LABELS[status] || status, 2100, { bold: true, color: STATUS_COLORS[status] || "111827" })] }),
    new TableRow({ children: [cell("Progress", 2200), cell(`${progress.official_pct ?? 0}%${overNote}`, 3160, { bold: true }), cell("Target", 1900), cell(`${d.target || "—"}${d.target_unit ? " " + d.target_unit : ""}`, 2100)] }),
    new TableRow({ children: [cell("Target date", 2200), cell(d.target_date || "—", 3160), cell("Communardo priority", 1900), cell(d.communardo_priority || "—", 2100)] }),
    new TableRow({ children: [cell("Success measure", 2200), cell(d.success_measure || "—", 3160, {}), cell("Atlassian priority", 1900), cell(d.atlassian_priority || "—", 2100)] }),
  ];
  const infoTable = new Table({ width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [2200, 3160, 1900, 2100], rows: infoRows });

  const summaryPara = new Paragraph({
    spacing: { before: 120, after: 160 },
    children: (d.summary_text || "").split("\n").flatMap((line, i) => i === 0
      ? [new TextRun({ text: line, size: 19 })]
      : [new TextRun({ text: "", break: 1 }), new TextRun({ text: line, size: 19 })]),
  });

  // Evidence — "reference to documents and information" per Steve's request:
  // every linked evidence item's filename, category, date, and description.
  const evidence = (d.linked_evidence || []).filter(e => e.found);
  const evidenceHeading = new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 160, after: 60 }, children: [new TextRun(`Evidence (${evidence.length})`)] });
  const evidenceTable = evidence.length ? new Table({
    width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [1500, 1700, 2200, 3960],
    rows: [
      new TableRow({ children: [headerCell("Date added", 1500), headerCell("Evidence ID", 1700), headerCell("Document / file", 2200), headerCell("Description", 3960)] }),
      ...evidence.map(e => new TableRow({ children: [
        cell(e.date_added || "—", 1500), cell(e.evidence_id || "—", 1700),
        cell(e.filename || "—", 2200), cell(e.description || "—", 3960),
      ]})),
    ],
  }) : emptyNote("No evidence linked yet.");

  // Linked activities / examples
  const activities = (d.linked_activities || []).filter(a => a.found);
  const activitiesHeading = new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 160, after: 60 }, children: [new TextRun(`Linked activities / examples (${activities.length})`)] });
  const activitiesTable = activities.length ? new Table({
    width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [1300, 1600, 3560, 2900],
    rows: [
      new TableRow({ children: [headerCell("Date", 1300), headerCell("Type", 1600), headerCell("Title / outcome", 3560), headerCell("Organisation", 2900)] }),
      ...activities.map(a => new TableRow({ children: [
        cell(a.date || "—", 1300), cell(a.type || "—", 1600),
        cell(`${a.title || "—"}${a.outcome ? " — " + a.outcome : ""}`, 3560), cell(a.organisation || "—", 2900),
      ]})),
    ],
  }) : emptyNote("No linked activities yet.");

  // Action points
  const actionPoints = d.action_points || [];
  const actionHeading = new Paragraph({ heading: HeadingLevel.HEADING_3, spacing: { before: 160, after: 60 }, children: [new TextRun(`Action points (${actionPoints.length})`)] });
  const actionTable = actionPoints.length ? new Table({
    width: { size: TABLE_WIDTH, type: WidthType.DXA }, columnWidths: [1500, 2500, 5360],
    rows: [
      new TableRow({ children: [headerCell("Date", 1500), headerCell("Source", 2500), headerCell("Action point", 5360)] }),
      ...actionPoints.map(a => new TableRow({ children: [cell(a.date || "—", 1500), cell(a.source || "—", 2500), cell(a.text || "—", 5360)] })),
    ],
  }) : emptyNote("No open action points.");

  return [
    new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 320, after: 60 }, children: [
      new TextRun({ text: `${d.objective_id ? d.objective_id + " — " : ""}${d.objective || r.objective || "Untitled objective"}` }),
    ]}),
    infoTable,
    summaryPara,
    evidenceHeading, evidenceTable,
    activitiesHeading, activitiesTable,
    actionHeading, actionTable,
  ];
}

const categorySections = CATEGORY_ORDER.filter(c => categoryCounts[c]).flatMap(c => {
  const rows = objectives.filter(r => (r.category || "") === c);
  return [
    new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun(`${CATEGORY_LABELS[c]} Objectives`)] }),
    new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: `${rows.length} objective${rows.length === 1 ? "" : "s"} in this section.`, size: 18, color: "6B7280" })] }),
    ...rows.flatMap(objectiveBlock),
  ];
});
if (categoryCounts.uncategorised) {
  const rows = objectives.filter(r => !r.category);
  categorySections.push(
    new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Uncategorised Objectives")] }),
    ...rows.flatMap(objectiveBlock),
  );
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: "1E293B" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: "2563EB" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 20, bold: true, font: "Arial", color: "334155" },
        paragraph: { spacing: { before: 140, after: 80 }, outlineLevel: 2 } },
    ],
  },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: `Orbit2 — Objectives Progress Report — generated ${generatedStamp}`, size: 16, color: "9CA3AF" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Page ", size: 16 }), new TextRun({ children: [PageNumber.CURRENT], size: 16 })] })] }) },
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Objectives Progress Report")] }),
      new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: `Generated ${generatedStamp} · ${preparedForLine}`, size: 18, color: "6B7280" })] }),
      new Paragraph({ spacing: { after: 260 }, children: [new TextRun({
        text: "Every objective below shows its current progress, the evidence and examples behind that progress (with references back to the underlying documents), and any open action points — regenerate this report at any time to get a fresh, dated snapshot.",
        size: 18, italics: true, color: "6B7280",
      })] }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Executive Summary")] }),
      summaryTable,
      new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 260 }, children: [new TextRun("Objectives by Category")] }),
      categoryOverviewTable,

      ...categorySections,
    ],
  }],
});

if (!fs.existsSync(REPORTS_DIR)) fs.mkdirSync(REPORTS_DIR, { recursive: true });
const outPath = path.join(REPORTS_DIR, `Orbit2_Objectives_Progress_Report_${filenameStamp}.docx`);
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("Wrote " + outPath);
});
