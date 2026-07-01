/**
 * Orbit2 PowerPoint generator.
 * Reads ../data/scores_snapshot.json + ../data/news_log.csv, writes
 * ../reports/Orbit2_Deck_<vendor>_<quarter>.pptx
 *
 * Usage: node generate_pptx.js [vendor]   (default vendor: Atlassian)
 * After writing, recompress: python ../../../.claude/skills/pptx/scripts/rezip.py <file>.pptx
 * (handled automatically by this script if the skill path is found)
 */
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");
const pptxgen = require("pptxgenjs");

const DATA_DIR = path.join(__dirname, "..", "data");
const REPORTS_DIR = path.join(__dirname, "..", "reports");
const vendor = process.argv[2] || "Atlassian";

const snapshot = JSON.parse(fs.readFileSync(path.join(DATA_DIR, "scores_snapshot.json")));
const vendorData = snapshot.vendors[vendor];
if (!vendorData) {
  console.error(`No data for vendor "${vendor}" in scores_snapshot.json`);
  process.exit(1);
}

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
const deals = vendorData.deals || [];

// Palette: Midnight Executive
const NAVY = "1E2761";
const ICE = "CADCFC";
const WHITE = "FFFFFF";
const INK = "1E293B";
const MUTED = "64748B";
const GREEN = "059669";
const AMBER = "B45309";
const RED = "DC2626";

function bandColor(score) {
  if (score === null || score === undefined) return MUTED;
  if (score >= 85) return GREEN;
  if (score >= 70) return AMBER;
  return RED;
}
function bandLabel(score) {
  if (score === null || score === undefined) return "No data";
  if (score >= 85) return "Strong";
  if (score >= 70) return "On track";
  return "Needs attention";
}
function money(v, currency) {
  const n = Number(v);
  if (!v || Number.isNaN(n)) return "—";
  return (currency || "EUR") + " " + n.toLocaleString();
}

const categories = Object.entries(vendorData.categories);
const allQuarters = categories.map(([, c]) => c.quarter).filter(Boolean).sort();
const quarter = allQuarters[allQuarters.length - 1] || "current";

let pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "Orbit2";
pres.title = `Orbit2 Performance Deck — ${vendor} ${quarter}`;

// ---------- Slide 1: Title ----------
{
  const slide = pres.addSlide();
  slide.background = { color: NAVY };
  slide.addText("Orbit2", { x: 0.7, y: 2.0, w: 8, h: 1, fontSize: 44, bold: true, color: WHITE, fontFace: "Calibri" });
  slide.addText(`${vendor} Partner Performance — ${quarter}`, { x: 0.7, y: 2.9, w: 10, h: 0.7, fontSize: 24, color: ICE, fontFace: "Calibri" });
  slide.addText(`Prepared for Steve Mojsak, Atlassian Alliance Manager, Communardo\nGenerated ${new Date().toISOString().slice(0, 10)}`,
    { x: 0.7, y: 6.4, w: 10, h: 0.7, fontSize: 13, color: ICE, fontFace: "Calibri" });
  slide.addShape(pres.shapes.OVAL, { x: 10.6, y: -1.2, w: 4, h: 4, fill: { color: "2C3A8C", transparency: 40 }, line: { type: "none" } });
  slide.addShape(pres.shapes.OVAL, { x: 11.8, y: 4.3, w: 2.6, h: 2.6, fill: { color: "2C3A8C", transparency: 40 }, line: { type: "none" } });
}

// ---------- Slide 2: Overall score ----------
{
  const slide = pres.addSlide();
  slide.background = { color: WHITE };
  slide.addText("Overall Score", { x: 0.6, y: 0.4, w: 8, h: 0.6, fontSize: 28, bold: true, color: INK, fontFace: "Calibri" });

  const score = vendorData.overall_score ?? 0;
  const color = bandColor(vendorData.overall_score);
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.6, y: 1.3, w: 3.6, h: 3.4, rectRadius: 0.12, fill: { color: "F8FAFC" },
    shadow: { type: "outer", color: "000000", blur: 8, offset: 3, angle: 90, opacity: 0.10 },
  });
  slide.addText(String(vendorData.overall_score ?? "—"), { x: 0.6, y: 1.5, w: 3.6, h: 1.6, align: "center", fontSize: 72, bold: true, color, fontFace: "Calibri" });
  slide.addText("/ 100", { x: 0.6, y: 2.95, w: 3.6, h: 0.4, align: "center", fontSize: 16, color: MUTED, fontFace: "Calibri" });
  slide.addText(bandLabel(vendorData.overall_score), { x: 0.6, y: 3.5, w: 3.6, h: 0.5, align: "center", fontSize: 18, bold: true, color, fontFace: "Calibri" });
  slide.addText("85+ Strong · 70–84 On track · below 70 Needs attention", { x: 0.6, y: 4.9, w: 3.6, h: 0.7, align: "center", fontSize: 10.5, color: MUTED, fontFace: "Calibri" });

  slide.addChart(pres.charts.BAR, [{
    name: `${vendor} category scores`,
    labels: categories.map(([, c]) => c.label.split(" ").slice(0, 3).join(" ")),
    values: categories.map(([, c]) => c.category_score ?? 0),
  }], {
    x: 4.5, y: 1.2, w: 8.3, h: 5.6, barDir: "bar",
    chartColors: [NAVY],
    chartArea: { fill: { color: "FFFFFF" } },
    catAxisLabelColor: MUTED, valAxisLabelColor: MUTED, catAxisLabelFontSize: 10,
    valGridLine: { color: "E2E8F0", size: 0.5 }, catGridLine: { style: "none" },
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: INK, dataLabelFontSize: 10,
    showLegend: false, valAxisMaxVal: 100, valAxisMinVal: 0,
  });

  const zeroCount = categories.filter(([, c]) => !c.category_score).length;
  if (zeroCount >= categories.length - 1) {
    slide.addText("Most categories are still at 0 pending real Q3 data entry — this is a clean-slate scorecard, not an error.",
      { x: 4.5, y: 6.9, w: 8.3, h: 0.4, fontSize: 10.5, italics: true, color: MUTED, fontFace: "Calibri" });
  }
}

// ---------- Slide 3: Category detail cards (2 rows x up to 5 cols) ----------
{
  const slide = pres.addSlide();
  slide.background = { color: WHITE };
  slide.addText("Category Breakdown", { x: 0.6, y: 0.35, w: 10, h: 0.6, fontSize: 26, bold: true, color: INK, fontFace: "Calibri" });
  const zeroCountS3 = categories.filter(([, c]) => !c.category_score).length;
  const subtitleS3 = zeroCountS3 >= categories.length - 1
    ? "Weighted % shown under each score. Most categories are at 0 — clean-slate scorecard awaiting real Q3 data, not an error."
    : "Weighted % shown under each score — see the full report for sub-metric detail.";
  slide.addText(subtitleS3, { x: 0.6, y: 0.9, w: 12, h: 0.4, fontSize: 12, color: MUTED, fontFace: "Calibri" });

  const cols = 5;
  const cardW = 2.42, cardH = 2.6, gap = 0.12;
  const startX = 0.6, startY = 1.55;
  categories.forEach(([key, c], i) => {
    const row = Math.floor(i / cols), col = i % cols;
    const x = startX + col * (cardW + gap);
    const y = startY + row * (cardH + gap);
    const color = bandColor(c.category_score);
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w: cardW, h: cardH, rectRadius: 0.08, fill: { color: "F8FAFC" },
      shadow: { type: "outer", color: "000000", blur: 5, offset: 2, angle: 90, opacity: 0.08 },
    });
    slide.addText(c.label, { x: x + 0.12, y: y + 0.15, w: cardW - 0.24, h: 0.75, fontSize: 10.5, bold: true, color: INK, fontFace: "Calibri" });
    slide.addText(String(c.category_score ?? "—"), { x: x + 0.12, y: y + 0.95, w: cardW - 0.24, h: 0.8, fontSize: 30, bold: true, color, fontFace: "Calibri" });
    slide.addText(`weight ${c.weight_pct}%`, { x: x + 0.12, y: y + 1.75, w: cardW - 0.24, h: 0.35, fontSize: 10, color: MUTED, fontFace: "Calibri" });
    slide.addText(bandLabel(c.category_score), { x: x + 0.12, y: y + 2.1, w: cardW - 0.24, h: 0.35, fontSize: 10.5, bold: true, color, fontFace: "Calibri" });
  });
}

// ---------- Slide 4: Key deals ----------
{
  const slide = pres.addSlide();
  slide.background = { color: WHITE };
  slide.addText("Key Deals", { x: 0.6, y: 0.35, w: 10, h: 0.6, fontSize: 26, bold: true, color: INK, fontFace: "Calibri" });

  if (!deals.length) {
    slide.addText("No deals logged yet.", { x: 0.6, y: 1.4, w: 8, h: 0.5, fontSize: 16, bold: true, color: INK, fontFace: "Calibri" });
    slide.addText("Add rows to data/deals.csv (company, TCV/ACV, products, services, vertical, Atlassian account category) or drop a deal sheet into the Evidence Library, and this slide will populate automatically the next time the deck is generated.",
      { x: 0.6, y: 1.9, w: 9.5, h: 1.2, fontSize: 13, color: MUTED, fontFace: "Calibri" });
  } else {
    const totalTcv = deals.reduce((a, d) => a + (Number(d.tcv) || 0), 0);
    const totalAcv = deals.reduce((a, d) => a + (Number(d.acv) || 0), 0);
    slide.addText(`${deals.length} deal(s) · Total TCV ${money(totalTcv, "EUR")} · Total ACV ${money(totalAcv, "EUR")}`,
      { x: 0.6, y: 0.95, w: 11, h: 0.4, fontSize: 13, color: MUTED, fontFace: "Calibri" });

    const rows = [[
      { text: "Company", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
      { text: "Closed", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
      { text: "TCV / ACV", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
      { text: "Products / Services", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
      { text: "Vertical", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
      { text: "Atlassian category", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
    ]];
    deals.slice(0, 8).forEach(d => rows.push([
      d.company_name || "—", d.close_date || "—",
      `${money(d.tcv, d.currency)} / ${money(d.acv, d.currency)}`,
      `${d.products_sold || "—"}${d.services_sold ? " / " + d.services_sold : ""}`,
      d.vertical || "—", d.atlassian_category || "—",
    ]));
    slide.addTable(rows, {
      x: 0.6, y: 1.5, w: 12.1, colW: [2.2, 1.2, 2.2, 3.3, 1.6, 1.6],
      fontSize: 10, border: { pt: 0.5, color: "E2E8F0" }, autoPage: false,
    });
  }
}

// ---------- Slide 5: Market visibility & sentiment ----------
{
  const slide = pres.addSlide();
  slide.background = { color: WHITE };
  slide.addText("Market Visibility & Sentiment", { x: 0.6, y: 0.35, w: 10, h: 0.6, fontSize: 26, bold: true, color: INK, fontFace: "Calibri" });

  const counts = news.reduce((acc, n) => { acc[n.sentiment] = (acc[n.sentiment] || 0) + 1; return acc; }, {});
  const pieData = [
    { name: "Sentiment", labels: ["Positive", "Neutral", "Negative"], values: [counts.positive || 0, counts.neutral || 0, counts.negative || 0] },
  ];
  if (news.length) {
    slide.addChart(pres.charts.PIE, pieData, {
      x: 0.6, y: 1.2, w: 4.6, h: 4.6, showPercent: true,
      chartColors: [GREEN, "94A3B8", RED],
      showLegend: true, legendPos: "b", legendColor: MUTED, legendFontSize: 11,
      dataLabelColor: WHITE, dataLabelFontSize: 11,
    });
  } else {
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.2, w: 4.6, h: 4.6, rectRadius: 0.1, fill: { color: "F8FAFC" } });
    slide.addText("No mentions logged yet", { x: 0.9, y: 3.2, w: 4, h: 0.8, fontSize: 14, color: MUTED, align: "center", fontFace: "Calibri" });
  }

  slide.addText(`${news.length} mention(s) found by the automated 12h web scan`, { x: 5.5, y: 1.2, w: 7.2, h: 0.4, fontSize: 13, bold: true, color: INK, fontFace: "Calibri" });
  const items = news.slice(-6).reverse();
  items.forEach((n, i) => {
    const y = 1.75 + i * 0.75;
    const c = n.sentiment === "positive" ? GREEN : n.sentiment === "negative" ? RED : MUTED;
    slide.addText(n.sentiment.toUpperCase(), { x: 5.5, y, w: 1.1, h: 0.3, fontSize: 9, bold: true, color: c, fontFace: "Calibri" });
    slide.addText(n.headline, { x: 6.7, y, w: 6.0, h: 0.65, fontSize: 11, color: INK, fontFace: "Calibri", valign: "top" });
  });
  if (!items.length) {
    slide.addText("The dashboard's Market Visibility & Sentiment feed will populate this list as mentions are found.", { x: 5.5, y: 1.8, w: 7.0, h: 0.8, fontSize: 12, color: MUTED, fontFace: "Calibri" });
  }
}

// ---------- Slide 6: Methodology / next steps ----------
{
  const slide = pres.addSlide();
  slide.background = { color: NAVY };
  slide.addText("How this score is built", { x: 0.7, y: 0.6, w: 10, h: 0.6, fontSize: 26, bold: true, color: WHITE, fontFace: "Calibri" });
  slide.addText([
    { text: "Every sub-metric scores 0–100 as actual ÷ target × 100.", options: { bullet: true, breakLine: true, color: ICE } },
    { text: "Sub-metric scores combine into a category score using each row's weight.", options: { bullet: true, breakLine: true, color: ICE } },
    { text: "Category scores combine into the overall score using data/weights.json.", options: { bullet: true, breakLine: true, color: ICE } },
    { text: "Full detail, every formula, every source: docs/methodology.md in the Orbit2 project folder.", options: { bullet: true, color: ICE } },
  ], { x: 0.7, y: 1.5, w: 11, h: 2.2, fontSize: 15, fontFace: "Calibri" });

  slide.addText("Next steps", { x: 0.7, y: 4.0, w: 10, h: 0.5, fontSize: 20, bold: true, color: WHITE, fontFace: "Calibri" });
  slide.addText([
    { text: "Replace any zeroed sub-metrics with real Q3 data via the Evidence Library or CSVs.", options: { bullet: true, breakLine: true, color: ICE } },
    { text: "Log key deals in data/deals.csv as they close so this deck stays current.", options: { bullet: true, breakLine: true, color: ICE } },
    { text: "Re-generate this deck any time from the Orbit2 dashboard's Reports page.", options: { bullet: true, color: ICE } },
  ], { x: 0.7, y: 4.6, w: 11, h: 1.8, fontSize: 15, fontFace: "Calibri" });
}

if (!fs.existsSync(REPORTS_DIR)) fs.mkdirSync(REPORTS_DIR, { recursive: true });
const outPath = path.join(REPORTS_DIR, `Orbit2_Deck_${vendor}_${quarter}.pptx`);
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("Wrote " + outPath);
  try {
    const rezip = path.join(__dirname, "..", "..", "..", ".claude", "skills", "pptx", "scripts", "rezip.py");
    // Try the known skill path; if not found, try relative to common mount point.
    const candidates = [
      rezip,
      "/sessions/fervent-great-lovelace/mnt/.claude/skills/pptx/scripts/rezip.py",
    ];
    const found = candidates.find(p => fs.existsSync(p));
    if (found) {
      execSync(`python3 "${found}" "${outPath}"`, { stdio: "inherit" });
      console.log("Recompressed with rezip.py");
    } else {
      console.log("rezip.py not found at expected paths — file written but not recompressed (still valid, just larger).");
    }
  } catch (e) {
    console.log("rezip step skipped: " + e.message);
  }
});
