/**
 * Orbit2 report generator.
 * Reads ../data/scores_snapshot.json (scores, deals, evidence, changelog) and
 * ../data/news_log.csv, writes a Word report to
 * ../reports/Orbit2_Report_<vendor>_<quarter>.docx
 *
 * Usage: node generate_report.js [vendor]   (default vendor: Atlassian)
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType, PageNumber,
  Header, Footer,
} = require("docx");

const DATA_DIR = path.join(__dirname, "..", "data");
const REPORTS_DIR = path.join(__dirname, "..", "reports");
const vendor = process.argv[2] || "Atlassian";

const snapshot = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "scores_snapshot.json")));
const vendorData = snapshot.vendors[vendor];
if (!vendorData) {
  console.error(`No data for vendor "${vendor}" in scores_snapshot.json`);
  process.exit(1);
}

// R1-T02: app_config.json is the source of truth for who/what this report is
// "prepared for" — falls back to the pre-R1-T02 hard-coded values if the
// file is missing or unreadable, so report generation never breaks on this.
function loadAppConfig() {
  const fallback = { user_display_name: "Steve Mojsak", job_title: "Atlassian Alliance Manager", company: "Communardo" };
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "app_config.json"), "utf8"));
    delete raw._comment;
    return Object.assign({}, fallback, raw);
  } catch (e) {
    return fallback;
  }
}
const appConfig = loadAppConfig();
const preparedForLine = `Prepared for ${appConfig.user_display_name}${appConfig.job_title ? ", " + appConfig.job_title : ""}, ${appConfig.company}`;

function parseCsv(text) {
  const lines = text.trim().split("\n");
  if (lines.length < 2) return [];
  const headers = lines[0].split(",");
  return lines.slice(1).map(line => {
    const cells = [];
    let cur = "", inQuotes = false;
    for (const ch of line) {
      if (ch === '"') inQuotes = !inQuotes;
      else if (ch === "," && !inQuotes) { cells.push(cur); cur = ""; }
      else cur += ch;
    }
    cells.push(cur);
    const obj = {};
    headers.forEach((h, i) => obj[h] = cells[i]);
    return obj;
  });
}
let news = [];
const newsPath = path.join(DATA_DIR, "news_log.csv");
if (fs.existsSync(newsPath)) news = parseCsv(fs.readFileSync(newsPath, "utf8"));

const deals = (vendorData.deals || []);

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const TABLE_WIDTH = 9360;

function bandLabel(score) {
  if (score === null || score === undefined) return "No data";
  if (score >= 85) return "Strong";
  if (score >= 70) return "On track";
  return "Needs attention";
}
function money(v, currency) {
  if (v === undefined || v === null || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return (currency || "EUR") + " " + n.toLocaleString();
}

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
function descriptionRow(text, span) {
  return new TableRow({ children: [
    new TableCell({
      borders, columnSpan: span, width: { size: TABLE_WIDTH, type: WidthType.DXA },
      shading: { fill: "F8FAFC", type: ShadingType.CLEAR },
      margins: { top: 60, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({ children: [new TextRun({ text: text || "No description on file.", italics: true, size: 17, color: "64748B" })] })],
    }),
  ]});
}

// ---- Category summary table ----
const categoryRows = Object.entries(vendorData.categories).map(([key, c]) => new TableRow({ children: [
  cell(c.label, 3600),
  cell(c.category_score ?? "—", 1400, { bold: true }),
  cell(bandLabel(c.category_score), 1560),
  cell(`${c.weight_pct}%`, 1200),
  cell(c.quarter || "—", 1600),
]}));

const categoryTable = new Table({
  width: { size: TABLE_WIDTH, type: WidthType.DXA },
  columnWidths: [3600, 1400, 1560, 1200, 1600],
  rows: [
    new TableRow({ children: [
      headerCell("Category", 3600), headerCell("Score", 1400),
      headerCell("Status", 1560), headerCell("Weight", 1200), headerCell("Quarter", 1600),
    ]}),
    ...categoryRows,
  ],
});

// ---- Category detail: sub-metric table + explanation row under each ----
const subMetricSections = Object.entries(vendorData.categories).flatMap(([key, c]) => {
  const dataRows = (c.sub_metrics || []).flatMap(s => ([
    new TableRow({ children: [
      cell(s.sub_metric, 2600),
      cell(`${s.actual} / ${s.target} ${s.unit || ""}`.trim(), 1900),
      cell(`${s.weight_pct_in_category}%`, 1000),
      cell(s.score ?? "—", 900, { bold: true }),
      cell(s.source || "—", 1560),
    ]}),
    descriptionRow(s.description, 5),
  ]));
  const table = dataRows.length ? new Table({
    width: { size: TABLE_WIDTH, type: WidthType.DXA },
    columnWidths: [2600, 1900, 1000, 900, 1560],
    rows: [
      new TableRow({ children: [
        headerCell("Sub-metric", 2600), headerCell("Actual / Target", 1900),
        headerCell("Weight", 1000), headerCell("Score", 900), headerCell("Source", 1560),
      ]}),
      ...dataRows,
    ],
  }) : new Paragraph({ children: [new TextRun({ text: "No data entered yet for this category.", italics: true, size: 18 })] });

  return [
    new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 60 }, children: [new TextRun(c.label + " — " + (c.category_score ?? "—") + " / 100")] }),
    new Paragraph({ spacing: { after: 100 }, children: [new TextRun({ text: `Weighted ${c.weight_pct}% of the overall score.`, italics: true, size: 17, color: "6B7280" })] }),
    table,
  ];
});

// ---- Metric glossary appendix (every sub-metric, every category, one place) ----
const glossaryRows = Object.entries(vendorData.categories).flatMap(([key, c]) =>
  (c.sub_metrics || []).map(s => new TableRow({ children: [
    cell(c.label, 2200),
    cell(s.sub_metric, 2600),
    cell(s.description || "—", 4560),
  ]}))
);
const glossaryTable = glossaryRows.length ? new Table({
  width: { size: TABLE_WIDTH, type: WidthType.DXA },
  columnWidths: [2200, 2600, 4560],
  rows: [
    new TableRow({ children: [headerCell("Category", 2200), headerCell("Sub-metric", 2600), headerCell("What it measures", 4560)] }),
    ...glossaryRows,
  ],
}) : new Paragraph({ children: [new TextRun({ text: "No metrics defined yet.", italics: true, size: 18 })] });

// ---- Key deals ----
const dealRows = deals.map(d => new TableRow({ children: [
  cell(d.company_name, 1700),
  cell(d.close_date || "—", 1000),
  cell(`${money(d.tcv, d.currency)} TCV\n${money(d.acv, d.currency)} ACV`, 1400),
  cell(d.products_sold || "—", 1500),
  cell(d.services_sold || "—", 1500),
  cell(d.vertical || "—", 1100),
  cell(d.atlassian_category || "—", 1160),
]}));
const dealsTable = dealRows.length ? new Table({
  width: { size: TABLE_WIDTH, type: WidthType.DXA },
  columnWidths: [1700, 1000, 1400, 1500, 1500, 1100, 1160],
  rows: [
    new TableRow({ children: [
      headerCell("Company", 1700), headerCell("Closed", 1000), headerCell("TCV / ACV", 1400),
      headerCell("Products sold", 1500), headerCell("Services sold", 1500),
      headerCell("Vertical", 1100), headerCell("Atlassian category", 1160),
    ]}),
    ...dealRows,
  ],
}) : new Paragraph({ children: [new TextRun({ text: "No deals logged yet. Add rows to data/deals.csv, or drag a deal sheet into the Evidence Library and Claude will file it here.", italics: true, size: 18 })] });

const dealTotals = deals.reduce((acc, d) => {
  acc.tcv += Number(d.tcv) || 0;
  acc.acv += Number(d.acv) || 0;
  return acc;
}, { tcv: 0, acv: 0 });

// ---- Sentiment / news ----
const sentimentCounts = news.reduce((acc, n) => { acc[n.sentiment] = (acc[n.sentiment] || 0) + 1; return acc; }, {});
const newsRows = news.slice(-10).reverse().map(n => new TableRow({ children: [
  cell(n.date_found, 1500),
  cell(n.sentiment, 1300),
  cell(n.headline, 4200),
  cell(n.summary || "", 2360),
]}));
const newsTable = newsRows.length ? new Table({
  width: { size: TABLE_WIDTH, type: WidthType.DXA },
  columnWidths: [1500, 1300, 4200, 2360],
  rows: [
    new TableRow({ children: [
      headerCell("Date", 1500), headerCell("Sentiment", 1300),
      headerCell("Headline", 4200), headerCell("Summary", 2360),
    ]}),
    ...newsRows,
  ],
}) : new Paragraph({ children: [new TextRun({ text: "No news items logged yet.", italics: true, size: 18 })] });

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
    ],
  },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } },
    },
    headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: `Orbit2 — ${appConfig.company} Partner Performance Report`, size: 16, color: "9CA3AF" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Page ", size: 16 }), new TextRun({ children: [PageNumber.CURRENT], size: 16 })] })] }) },
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(`Orbit2 Performance Report — ${vendor}`)] }),
      new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: `Generated ${new Date().toISOString().slice(0,10)} · ${preparedForLine}`, size: 18, color: "6B7280" })] }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Overall Score")] }),
      new Paragraph({ spacing: { after: 100 }, children: [
        new TextRun({ text: `${vendorData.overall_score ?? "—"} / 100`, bold: true, size: 44, color: "2563EB" }),
        new TextRun({ text: `   (${bandLabel(vendorData.overall_score)})`, size: 22, color: "6B7280" }),
      ]}),
      new Paragraph({ spacing: { after: 100 }, children: [new TextRun({ text: "85+ Strong · 70–84 On track · below 70 Needs attention. Weighted average of the categories below, per docs/methodology.md.", size: 17, color: "6B7280" })] }),
      new Paragraph({ spacing: { after: 260 }, children: [new TextRun({ text: "Every score traces back to a target/actual pair sourced from a CRM export, portal screenshot, or finance report — see the description under each sub-metric in the Category Detail section for exactly what it measures and why it matters.", size: 18, italics: true, color: "6B7280" })] }),

      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun("Category Summary")] }),
      categoryTable,

      new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Category Detail & Explanation")] }),
      new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "Every sub-metric behind every category score, with what it measures, its target vs actual, its weight, and its source.", size: 18, color: "6B7280" })] }),
      ...subMetricSections,

      new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Key Deals")] }),
      new Paragraph({ spacing: { after: 160 }, children: [new TextRun({
        text: deals.length
          ? `${deals.length} deal(s) on file. Total TCV ${money(dealTotals.tcv, "EUR")} · Total ACV ${money(dealTotals.acv, "EUR")}.`
          : "Deal-level detail (company, contract value, products/services sold, vertical, Atlassian account category) will appear here once entered in data/deals.csv.",
        size: 18,
      })] }),
      dealsTable,

      new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Market Visibility & Sentiment (most recent)")] }),
      new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: `Logged mentions: ${news.length} total — ${sentimentCounts.positive || 0} positive, ${sentimentCounts.neutral || 0} neutral, ${sentimentCounts.negative || 0} negative.`, size: 20 })] }),
      newsTable,

      new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun("Appendix: Full Metric Glossary")] }),
      new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "Every sub-metric tracked across the entire scorecard, in one place, for quick reference.", size: 18, color: "6B7280" })] }),
      glossaryTable,
    ],
  }],
});

if (!fs.existsSync(REPORTS_DIR)) fs.mkdirSync(REPORTS_DIR, { recursive: true });
// Categories can now be on different quarters (e.g. you just updated one category but not others),
// so use the most recent quarter seen across all categories for the filename, not just the first one.
const allQuarters = Object.values(vendorData.categories).map(c => c.quarter).filter(Boolean).sort();
const quarter = allQuarters[allQuarters.length - 1] || "current";
const outPath = path.join(REPORTS_DIR, `Orbit2_Report_${vendor}_${quarter}.docx`);
Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outPath, buf);
  console.log("Wrote " + outPath);
});
