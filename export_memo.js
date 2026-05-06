/**
 * export_memo.js
 * Reads output_memo.json and generates a professional two-page Investment Memo (.docx)
 *
 * Usage: node export_memo.js
 * Requires: npm install docx
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, Header, Footer, LevelFormat, PageBreak,
} = require("docx");
const fs = require("fs");

// ── Colour palette ────────────────────────────────────────────────────────────
const C = {
  primary:     "1F3864",
  secondary:   "2E75B6",
  accent:      "C00000",   // VERKAUFEN / Bear
  accentBuy:   "375623",   // KAUFEN / Bull
  accentHold:  "7F6000",   // HALTEN / neutral
  lightBlue:   "D6E4F0",
  lightGray:   "F2F2F2",
  lightRed:    "FFDFD6",
  lightGreen:  "DFF0D8",
  lightYellow: "FFF8D6",
  warningBg:   "FFF3CD",
  warningBdr:  "FF8C00",
  diaboliGray: "E8E8E8",
  white:       "FFFFFF",
  black:       "000000",
  darkGray:    "404040",
  midGray:     "808080",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function recColor(rec) {
  if (rec === "KAUFEN")    return C.accentBuy;
  if (rec === "VERKAUFEN") return C.accent;
  return C.accentHold;
}

function signalColor(signal) {
  if (signal === "positiv") return C.accentBuy;
  if (signal === "negativ") return C.accent;
  return C.accentHold;
}

function signalEmoji(signal) {
  if (signal === "positiv") return "🟢";
  if (signal === "negativ") return "🔴";
  return "🟡";
}

function assessmentColor(a) {
  if (a === "DISCOUNT")  return C.accentBuy;
  if (a === "ELEVATED")  return C.accent;
  return C.midGray;
}

function convictionLabel(level) {
  const map = { "hoch": "★★★ HOCH", "mittel": "★★☆ MITTEL", "niedrig": "★☆☆ NIEDRIG" };
  return map[level] || level;
}

function border1(color = "CCCCCC") {
  const b = { style: BorderStyle.SINGLE, size: 1, color };
  return { top: b, bottom: b, left: b, right: b };
}

function cellMargins(v = 100, h = 120) {
  return { top: v, bottom: v, left: h, right: h };
}

function sectionHeader(text) {
  return new Paragraph({
    spacing: { before: 240, after: 80 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.secondary, space: 1 } },
    children: [new TextRun({ text: text.toUpperCase(), bold: true, size: 21, color: C.secondary, font: "Arial" })],
  });
}

function bodyText(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text: text || "", size: 18, font: "Arial", color: C.darkGray, ...opts })],
  });
}

function italicBox(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    indent: { left: 360, right: 360 },
    shading: { fill: C.diaboliGray, type: ShadingType.CLEAR },
    children: [new TextRun({ text: text || "", size: 18, font: "Arial", italics: true, color: C.darkGray })],
  });
}

function bullet(parts) {
  // parts: array of { text, bold?, color? }
  const runs = parts.map(p => new TextRun({
    text: p.text, bold: !!p.bold, color: p.color || C.darkGray, size: 18, font: "Arial",
  }));
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { before: 30, after: 30 },
    children: runs,
  });
}

function checkboxItem(text) {
  return new Paragraph({
    spacing: { before: 30, after: 30 },
    children: [
      new TextRun({ text: "□ ", size: 18, font: "Arial", color: C.secondary }),
      new TextRun({ text: text || "", size: 18, font: "Arial", color: C.darkGray }),
    ],
  });
}

function emptyLine(size = 80) {
  return new Paragraph({ spacing: { before: size, after: 0 }, children: [] });
}

function hCell(text, width, shading = C.primary, textColor = C.white) {
  return new TableCell({
    borders: border1(),
    width: { size: width, type: WidthType.DXA },
    shading: { fill: shading, type: ShadingType.CLEAR },
    margins: cellMargins(),
    children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text, bold: true, color: textColor, size: 17, font: "Arial" })],
    })],
  });
}

function vCell(text, width, opts = {}) {
  const { color = C.darkGray, bold = false, align = AlignmentType.CENTER, bg = C.white } = opts;
  return new TableCell({
    borders: border1(),
    width: { size: width, type: WidthType.DXA },
    shading: { fill: bg, type: ShadingType.CLEAR },
    margins: cellMargins(80, 100),
    verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({
      alignment: align,
      children: [new TextRun({ text: String(text ?? ""), color, bold, size: 18, font: "Arial" })],
    })],
  });
}

// ── Section 1: Header KPI table ───────────────────────────────────────────────

function buildHeaderTable(data) {
  const rc = recColor(data.final_recommendation);
  const upside = data.upside_downside_pct;
  const upsideStr = upside >= 0 ? `+${upside}%` : `${upside}%`;
  const upsideColor = upside >= 0 ? C.accentBuy : C.accent;
  const currency = data.currency || "";
  const W = [1440, 1620, 1620, 1620, 1620, 1440]; // 6 cols, total 9360

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: W,
    rows: [
      new TableRow({ children: [
        hCell("EMPFEHLUNG",   W[0]),
        hCell("CONVICTION",   W[1]),
        hCell("PRICE TARGET", W[2]),
        hCell("AKT. KURS",    W[3]),
        hCell("UPSIDE/DOWN.", W[4]),
        hCell("WÄHRUNG",      W[5]),
      ]}),
      new TableRow({ children: [
        vCell(data.final_recommendation || "N/A", W[0], { color: rc, bold: true }),
        vCell(convictionLabel(data.conviction_level), W[1], { color: C.primary, bold: true }),
        vCell(`${currency} ${data.price_target}`, W[2], { color: C.primary, bold: true }),
        vCell(`${currency} ${data.current_price}`, W[3]),
        vCell(upsideStr, W[4], { color: upsideColor, bold: true }),
        vCell(currency, W[5], { color: C.darkGray }),
      ]}),
    ],
  });
}

// ── Section 2: Valuation table ────────────────────────────────────────────────

function buildValuationTable(rows) {
  if (!rows || !rows.length) return bodyText("Keine Bewertungsdaten verfügbar.");
  const W = [1800, 1620, 1980, 1980, 1380, 1600];

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: W,
    rows: [
      new TableRow({ children: [
        hCell("Kennzahl",    W[0], C.secondary),
        hCell("Aktuell",     W[1], C.secondary),
        hCell("Peer Ø",      W[2], C.secondary),
        hCell("Hist. Ø",     W[3], C.secondary),
        hCell("Einschätz.",  W[4], C.secondary),
        hCell("Quelle",      W[5], C.secondary),
      ]}),
      ...rows.map((r, i) => new TableRow({ children: [
        vCell(r.metric,             W[0], { align: AlignmentType.LEFT,   bg: i % 2 ? C.white : C.lightGray }),
        vCell(r.current_value,      W[1], { bg: i % 2 ? C.white : C.lightGray }),
        vCell(r.peer_average,       W[2], { bg: i % 2 ? C.white : C.lightGray }),
        vCell(r.historical_average, W[3], { bg: i % 2 ? C.white : C.lightGray }),
        vCell(r.assessment,         W[4], { color: assessmentColor(r.assessment), bold: true, bg: i % 2 ? C.white : C.lightGray }),
        vCell(r.source,             W[5], { color: C.midGray, bg: i % 2 ? C.white : C.lightGray }),
      ]})),
    ],
  });
}

// ── Section 3: Consensus estimates ───────────────────────────────────────────

function buildConsensusTable(years) {
  if (!years || !years.length) return bodyText("Keine Konsensschätzungen verfügbar.");
  const colW = [1560, ...Array(years.length).fill(Math.floor((9360 - 1560) / years.length))];

  function isActual(y) { return y.type === "A"; }

  const headerCells = [
    hCell("Kennzahl", colW[0], C.secondary),
    ...years.map((y, i) => hCell(
      `${y.year}${y.type}`,
      colW[i + 1],
      isActual(y) ? C.lightGray : C.lightBlue,
      isActual(y) ? C.darkGray : C.primary,
    )),
  ];

  function dataRow(label, field, bold = false, i = 0) {
    return new TableRow({ children: [
      vCell(label, colW[0], { align: AlignmentType.LEFT, bold, bg: i % 2 ? C.white : C.lightGray }),
      ...years.map((y, j) => vCell(
        y[field] ?? "n/v",
        colW[j + 1],
        {
          bold,
          bg: isActual(y) ? C.lightGray : C.lightBlue,
        }
      )),
    ]});
  }

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: colW,
    rows: [
      new TableRow({ children: headerCells }),
      dataRow("Umsatz (Mrd.)",    "revenue_bn",        true,  0),
      dataRow("EBITDA-Marge %",   "ebitda_margin_pct", false, 1),
      dataRow("EPS",              "eps",               true,  2),
      dataRow("EV/EBITDA",        "ev_ebitda",         false, 3),
      dataRow("KGV (P/E)",        "pe_ratio",          false, 4),
      dataRow("# Analysten",      "number_of_analysts",false, 5),
    ],
  });
}

// ── Section 4: Scenario table ────────────────────────────────────────────────

function buildScenarioTable(scenarios) {
  if (!scenarios || !scenarios.length) return bodyText("Keine Szenarien verfügbar.");
  const W = [1440, 1200, 1320, 2760, 2640];

  function scenarioBg(name) {
    if (name === "Bear Case") return C.lightRed;
    if (name === "Bull Case") return C.lightGreen;
    return C.lightGray;
  }

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: W,
    rows: [
      new TableRow({ children: [
        hCell("Szenario",    W[0], C.secondary),
        hCell("Wahrsch.",    W[1], C.secondary),
        hCell("Kursziel",    W[2], C.secondary),
        hCell("Kernannahme", W[3], C.secondary),
        hCell("Trigger",     W[4], C.secondary),
      ]}),
      ...scenarios.map(s => {
        const bg = scenarioBg(s.name);
        return new TableRow({ children: [
          vCell(s.name,            W[0], { bold: true, bg }),
          vCell(`${s.probability_pct}%`, W[1], { bg }),
          vCell(s.price_target,    W[2], { bold: true, bg }),
          vCell(s.key_assumption,  W[3], { align: AlignmentType.LEFT, bg }),
          vCell(s.trigger,         W[4], { align: AlignmentType.LEFT, bg }),
        ]});
      }),
    ],
  });
}

// ── Section 5: Macro Ampel ────────────────────────────────────────────────────

function buildMacroAmpel(items) {
  if (!items || !items.length) return bodyText("Keine Makro-Ampel verfügbar.");
  // 2x2 grid
  const W = [2340, 2340, 2340, 2340];

  function ampelCell(item, width) {
    const sc = signalColor(item.signal);
    const emoji = signalEmoji(item.signal);
    return new TableCell({
      borders: border1(C.lightGray),
      width: { size: width, type: WidthType.DXA },
      shading: { fill: C.lightGray, type: ShadingType.CLEAR },
      margins: cellMargins(120, 160),
      children: [
        new Paragraph({
          spacing: { before: 0, after: 40 },
          children: [
            new TextRun({ text: `${emoji} `, size: 20, font: "Arial" }),
            new TextRun({ text: item.category, bold: true, size: 20, font: "Arial", color: sc }),
          ],
        }),
        new Paragraph({
          spacing: { before: 0, after: 0 },
          children: [new TextRun({ text: item.key_point || "", size: 17, font: "Arial", color: C.darkGray })],
        }),
      ],
    });
  }

  const rows = [];
  for (let i = 0; i < items.length; i += 2) {
    const cells = [ampelCell(items[i], W[0] + W[1])];
    if (items[i + 1]) cells.push(ampelCell(items[i + 1], W[2] + W[3]));
    rows.push(new TableRow({ children: cells }));
  }

  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [4680, 4680],
    rows,
  });
}

// ── Section 6: Conviction Killers ────────────────────────────────────────────

function buildConvictionKillers(killers) {
  if (!killers || !killers.length) return [];
  const result = [];
  result.push(new Paragraph({
    spacing: { before: 200, after: 80 },
    border: {
      top:    { style: BorderStyle.SINGLE, size: 6, color: C.warningBdr, space: 1 },
      bottom: { style: BorderStyle.SINGLE, size: 6, color: C.warningBdr, space: 1 },
      left:   { style: BorderStyle.THICK,  size: 12, color: C.warningBdr, space: 1 },
      right:  { style: BorderStyle.SINGLE, size: 6, color: C.warningBdr, space: 1 },
    },
    shading: { fill: C.warningBg, type: ShadingType.CLEAR },
    children: [new TextRun({ text: "⚠  CONVICTION KILLERS", bold: true, size: 19, color: C.warningBdr, font: "Arial" })],
  }));
  killers.forEach(k => {
    result.push(new Paragraph({
      spacing: { before: 60, after: 20 },
      shading: { fill: C.warningBg, type: ShadingType.CLEAR },
      border: {
        left:  { style: BorderStyle.THICK, size: 12, color: C.warningBdr, space: 1 },
        right: { style: BorderStyle.SINGLE, size: 6, color: C.warningBdr, space: 1 },
      },
      indent: { left: 200 },
      children: [new TextRun({ text: `⚠ ${k.description}`, size: 18, font: "Arial", color: C.darkGray })],
    }));
    result.push(new Paragraph({
      spacing: { before: 20, after: 60 },
      shading: { fill: C.warningBg, type: ShadingType.CLEAR },
      border: {
        left:  { style: BorderStyle.THICK,  size: 12, color: C.warningBdr, space: 1 },
        right: { style: BorderStyle.SINGLE, size: 6,  color: C.warningBdr, space: 1 },
        bottom: { style: BorderStyle.SINGLE, size: 6, color: C.warningBdr, space: 1 },
      },
      indent: { left: 360 },
      children: [new TextRun({ text: `→ Monitor: ${k.monitoring_indicator}`, size: 17, italics: true, color: C.midGray, font: "Arial" })],
    }));
  });
  return result;
}

// ── Section 7a: Full Financial Overview ──────────────────────────────────────

function buildFullFinancialsTable(years) {
  if (!years || !years.length) return bodyText("Keine Finanzübersicht verfügbar.");

  const FIELDS = [
    { label: "Umsatz (Mrd.)",  key: "revenue_bn" },
    { label: "EBITDA (Mrd.)",  key: "ebitda_bn" },
    { label: "EBITDA-%",       key: "ebitda_margin_pct" },
    { label: "EBIT-%",         key: "ebit_margin_pct" },
    { label: "EPS (adj.)",     key: "eps_adj" },
    { label: "DPS",            key: "dps" },
    { label: "FCF (Mrd.)",     key: "fcf_bn" },
    { label: "ND/EBITDA",      key: "nd_ebitda" },
    { label: "ROIC-%",         key: "roic_pct" },
    { label: "CapEx (Mrd.)",   key: "capex_bn" },
    { label: "Quelle",         key: "source" },
  ];

  const labelColW = 1400;
  const dataColW  = Math.floor((9360 - labelColW) / years.length);
  const colWidths = [labelColW, ...Array(years.length).fill(dataColW)];

  function isEstimate(y) { return y.type === "E"; }

  const headerCells = [
    hCell("Kennzahl", labelColW, C.secondary),
    ...years.map((y, i) => hCell(
      y.year,
      dataColW,
      isEstimate(y) ? C.lightYellow : C.lightGray,
      isEstimate(y) ? C.accentHold  : C.darkGray,
    )),
  ];

  const dataRows = FIELDS.map((f, ri) =>
    new TableRow({ children: [
      vCell(f.label, labelColW, { align: AlignmentType.LEFT, bold: ri === 0, bg: ri % 2 ? C.white : C.lightGray }),
      ...years.map(y => {
        const bg = isEstimate(y) ? C.lightYellow : (ri % 2 ? C.white : C.lightGray);
        const val = y[f.key] ?? "n/v";
        return vCell(String(val), dataColW, { bg, bold: f.key === "revenue_bn" });
      }),
    ]}),
  );

  const footnote = new Paragraph({
    spacing: { before: 60, after: 0 },
    children: [new TextRun({
      text: "A = Istzahlen (IR / yfinance)  |  📊 E = Schätzung (Consensus / Guidance / LLM-Ableitung)  |  Kein Ersatz für Bloomberg/FactSet",
      size: 14, italics: true, color: C.midGray, font: "Arial",
    })],
  });

  return [
    new Table({
      width: { size: 9360, type: WidthType.DXA },
      columnWidths: colWidths,
      rows: [new TableRow({ children: headerCells }), ...dataRows],
    }),
    footnote,
  ];
}

// ── Section 7b: Peer Comparison ───────────────────────────────────────────────

function buildPeerComparisonTable(pc) {
  if (!pc || !pc.peers || !pc.peers.length) return bodyText("Kein Peer-Vergleich verfügbar.");

  const allRows = [
    ...(pc.peers || []),
    pc.sector_averages,
    pc.subject_company,
  ].filter(Boolean);

  const W = [2200, 600, 1000, 900, 900, 900, 900, 900, 960];

  const header = new TableRow({ children: [
    hCell("Unternehmen",      W[0], C.secondary),
    hCell("Land",             W[1], C.secondary),
    hCell("EV/EBITDA",        W[2], C.secondary),
    hCell("Fwd. P/E",         W[3], C.secondary),
    hCell("EBIT-%",           W[4], C.secondary),
    hCell("ND/EBITDA",        W[5], C.secondary),
    hCell("Div.-Yield",       W[6], C.secondary),
    hCell("Umsatz-Wachst.",   W[7], C.secondary),
    hCell("ROIC-%",           W[8], C.secondary),
  ]});

  const today = new Date().toLocaleDateString("de-CH");
  const subjectTicker = pc.subject_company && pc.subject_company.ticker;

  const dataRows = allRows.map(p => {
    const isSubject = p.ticker === subjectTicker;
    const isAvg     = p.ticker === "AVG";
    const bg = isSubject ? C.lightBlue : (isAvg ? C.lightGray : C.white);
    const label = (isSubject ? "⭐ " : isAvg ? "Ø " : "") + (p.company || "");

    return new TableRow({ children: [
      vCell(label,                      W[0], { align: AlignmentType.LEFT, bold: isSubject || isAvg, bg }),
      vCell(p.country || "",            W[1], { bg }),
      vCell(String(p.ev_ebitda ?? "n/v"),     W[2], { bg, bold: isSubject }),
      vCell(String(p.forward_pe ?? "n/v"),    W[3], { bg }),
      vCell(String(p.ebit_margin_pct ?? "n/v"), W[4], { bg }),
      vCell(String(p.nd_ebitda ?? "n/v"),     W[5], { bg }),
      vCell(String(p.dividend_yield_pct ?? "n/v"), W[6], { bg }),
      vCell(String(p.revenue_growth_pct ?? "n/v"), W[7], { bg }),
      vCell(String(p.roic_pct ?? "n/v"),      W[8], { bg }),
    ]});
  });

  const footnote = new Paragraph({
    spacing: { before: 60, after: 0 },
    children: [new TextRun({
      text: `⭐ = analysiertes Unternehmen  |  Ø = Sektor-Durchschnitt (Ausreisser >3× Median bereinigt)  |  Quelle: yfinance  |  Stand: ${today}`,
      size: 14, italics: true, color: C.midGray, font: "Arial",
    })],
  });

  const vsAvg = pc.subject_vs_avg || {};
  const vsEntries = Object.entries(vsAvg).filter(([, v]) => v !== "n/v");
  const vsPara = vsEntries.length ? new Paragraph({
    spacing: { before: 60, after: 0 },
    children: [
      new TextRun({ text: "Subject vs. Sektor-Ø: ", bold: true, size: 16, font: "Arial", color: C.primary }),
      new TextRun({
        text: vsEntries.map(([k, v]) => `${k}: ${v}`).join("  |  "),
        size: 16, font: "Arial", color: C.darkGray,
      }),
    ],
  }) : null;

  return [
    new Table({
      width: { size: 9360, type: WidthType.DXA },
      columnWidths: W,
      rows: [header, ...dataRows],
    }),
    footnote,
    ...(vsPara ? [vsPara] : []),
  ];
}

// ── Section 7: Sources table ──────────────────────────────────────────────────

function buildSourcesTable(sources) {
  const rows = (sources || []).map((src, i) =>
    new TableRow({ children: [
      new TableCell({
        borders: border1(),
        width: { size: 560, type: WidthType.DXA },
        shading: { fill: i % 2 ? C.white : C.lightGray, type: ShadingType.CLEAR },
        margins: cellMargins(60, 100),
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: `${i + 1}`, size: 16, font: "Arial", color: C.darkGray })],
        })],
      }),
      new TableCell({
        borders: border1(),
        width: { size: 8800, type: WidthType.DXA },
        shading: { fill: i % 2 ? C.white : C.lightGray, type: ShadingType.CLEAR },
        margins: cellMargins(60, 100),
        children: [new Paragraph({
          children: [new TextRun({ text: src, size: 16, font: "Arial", color: C.darkGray })],
        })],
      }),
    ]})
  );
  if (!rows.length) return bodyText("Keine Quellen angegeben.");
  return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [560, 8800], rows });
}

// ── Main document builder ─────────────────────────────────────────────────────

async function buildMemo(data) {
  const today = new Date().toLocaleDateString("de-CH", { year: "numeric", month: "long", day: "numeric" });

  // ── Extract and normalise fields ─────────────────────────────────────────
  const investmentCase    = Array.isArray(data.investment_case)    ? data.investment_case    : [];
  const keyRisks          = Array.isArray(data.key_risks)          ? data.key_risks          : [];
  const monitoringList    = Array.isArray(data.monitoring_checklist)? data.monitoring_checklist : [];
  const sources           = Array.isArray(data.sources)            ? data.sources            : [];
  const valTable          = Array.isArray(data.valuation_table)    ? data.valuation_table    : [];
  const consensusYears    = Array.isArray(data.consensus_estimates) ? data.consensus_estimates : [];
  const scenarioList      = Array.isArray(data.scenarios)          ? data.scenarios          : [];
  const macroAmpelList    = Array.isArray(data.macro_ampel)        ? data.macro_ampel        : [];
  const convKillers       = Array.isArray(data.conviction_killers) ? data.conviction_killers : [];
  const fullFinancials    = Array.isArray(data.full_financials)    ? data.full_financials    : [];
  const peerComparison    = data.peer_comparison                   || null;

  function headerParagraph() {
    return [
      new Paragraph({
        spacing: { before: 0, after: 120 },
        children: [
          new TextRun({ text: data.company || "", bold: true, size: 52, color: C.primary, font: "Arial" }),
        ],
      }),
      new Paragraph({
        spacing: { before: 0, after: 60 },
        children: [
          new TextRun({ text: `${data.ticker}  |  ${data.sector || ""}  |  Datum: ${data.date || today}`, size: 20, color: C.darkGray, font: "Arial" }),
        ],
      }),
    ];
  }

  function headerAndFooter() {
    return {
      headers: {
        default: new Header({
          children: [new Paragraph({
            border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C.primary, space: 1 } },
            spacing: { after: 100 },
            children: [new TextRun({ text: "KI-Co-Portfolio-Manager  |  Investment Memo  |  Vertraulich", size: 15, color: C.primary, font: "Arial", italics: true })],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            border: { top: { style: BorderStyle.SINGLE, size: 6, color: C.primary, space: 1 } },
            spacing: { before: 100 },
            children: [
              new TextRun({ text: `Erstellt: ${today}  |  KI-Co-Portfolio-Manager  |  Seite `, size: 15, color: C.primary, font: "Arial" }),
              new TextRun({ children: [PageNumber.CURRENT], size: 15, color: C.primary, font: "Arial" }),
              new TextRun({ text: " von ", size: 15, color: C.primary, font: "Arial" }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 15, color: C.primary, font: "Arial" }),
            ],
          })],
        }),
      },
    };
  }

  // ── PAGE 1 children ───────────────────────────────────────────────────────
  const page1 = [
    // Title
    ...headerParagraph(),
    emptyLine(60),

    // 1. KPI header table
    buildHeaderTable(data),
    emptyLine(80),

    // 2. Unternehmensbeschreibung
    sectionHeader("Unternehmensbeschreibung"),
    new Paragraph({
      spacing: { before: 40, after: 40 },
      children: [new TextRun({ text: data.company_description || "", size: 18, font: "Arial", color: C.darkGray, italics: true })],
    }),
    emptyLine(60),

    // 3. Investment Case
    sectionHeader("Investment Case"),
    ...investmentCase.map(pt => {
      // Bold the first number-like token for visual emphasis
      const match = pt.match(/^(.*?)(\d[\d.,x%]*)(.*?)(\(Quelle:[^)]*\))?(.*)/i);
      if (match && match[2]) {
        return bullet([
          { text: match[1] || "" },
          { text: match[2], bold: true, color: C.primary },
          { text: (match[3] || "") + (match[4] ? ` ${match[4]}` : "") + (match[5] || "") },
        ]);
      }
      return bullet([{ text: pt }]);
    }),
    emptyLine(60),

    // 4. Bewertungstabelle
    sectionHeader("Bewertung"),
    buildValuationTable(valTable),
    emptyLine(60),

    // 5. Konsensschätzungen
    sectionHeader("Konsensschätzungen"),
    buildConsensusTable(consensusYears),
    emptyLine(60),

    // 5a. Vollständige Finanzübersicht
    sectionHeader("Finanzübersicht (6 Jahre)"),
    ...buildFullFinancialsTable(fullFinancials),
    emptyLine(60),

    // 5b. Peer-Vergleich
    sectionHeader("Peer-Vergleich"),
    ...buildPeerComparisonTable(peerComparison),
    emptyLine(60),
  ];

  // ── PAGE 2 children ───────────────────────────────────────────────────────
  const page2 = [
    // Page break
    new Paragraph({ children: [new PageBreak()] }),

    // 6. Szenario-Tabelle
    sectionHeader("Szenarien"),
    buildScenarioTable(scenarioList),
    emptyLine(60),

    // 7. Risiken
    sectionHeader("Risiken"),
    ...keyRisks.map(r => {
      const parts = r.split("→");
      if (parts.length > 1) {
        const runs = [];
        runs.push({ text: parts[0].trim() });
        runs.push({ text: " → ", color: C.secondary, bold: true });
        runs.push({ text: parts.slice(1).join("→").trim() });
        return bullet(runs);
      }
      return bullet([{ text: r }]);
    }),
    emptyLine(60),

    // 8. Makro & Sentiment Ampel
    sectionHeader("Makro & Sentiment Ampel"),
    buildMacroAmpel(macroAmpelList),
    emptyLine(60),

    // 9. Conviction Killers
    sectionHeader("Conviction Killers"),
    ...buildConvictionKillers(convKillers),
    emptyLine(60),

    // 10. Advocatus Diaboli
    sectionHeader("Advocatus Diaboli — Gegenposition"),
    italicBox(data.advocatus_diaboli_summary || ""),
    emptyLine(60),

    // 11. Monitoring Checklist
    sectionHeader("Monitoring Checklist"),
    ...monitoringList.map(item => checkboxItem(item)),
    emptyLine(60),

    // 12. Finale Begründung
    sectionHeader("Finale Begründung & Empfehlung"),
    bodyText(data.final_reasoning || ""),
    emptyLine(60),

    // 13. Quellen
    sectionHeader("Quellen & Datengrundlage"),
    emptyLine(40),
    buildSourcesTable(sources),
    emptyLine(60),

    // 14. Disclaimer
    new Paragraph({
      spacing: { before: 160, after: 0 },
      border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.lightBlue, space: 1 } },
      children: [new TextRun({
        text: "Disclaimer: Dieses Dokument wurde automatisch durch das KI-Co-Portfolio-Manager System generiert " +
              "und dient ausschliesslich zu Informationszwecken. Es stellt keine Anlageberatung dar. " +
              "Alle Angaben basieren auf öffentlich verfügbaren Daten (yfinance, Yahoo Finance) zum Zeitpunkt der Analyse. " +
              "Eine Haftung für die Richtigkeit der Angaben wird nicht übernommen.",
        size: 14,
        italics: true,
        color: C.midGray,
        font: "Arial",
      })],
    }),
  ];

  const doc = new Document({
    numbering: {
      config: [{
        reference: "bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 560, hanging: 280 } } },
        }],
      }],
    },
    styles: {
      default: {
        document: { run: { font: "Arial", size: 18, color: C.darkGray } },
      },
    },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838 }, // A4
          margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 }, // ~2 cm
        },
      },
      ...headerAndFooter(),
      children: [...page1, ...page2],
    }],
  });

  return doc;
}

// ── Entry point ───────────────────────────────────────────────────────────────

async function main() {
  const inputFile  = "output_memo.json";
  const outputFile = `investment_memo_${new Date().toISOString().slice(0, 10)}.docx`;

  if (!fs.existsSync(inputFile)) {
    console.error(`Fehler: ${inputFile} nicht gefunden.`);
    console.error("Bitte zuerst 'python graph/supervisor.py' ausführen.");
    process.exit(1);
  }

  console.log(`Lese ${inputFile}...`);
  const data = JSON.parse(fs.readFileSync(inputFile, "utf8"));

  console.log("Erstelle Word-Dokument...");
  const doc = await buildMemo(data);

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputFile, buffer);

  console.log(`\n✓ Investment Memo gespeichert: ${outputFile}`);
  console.log(`  Empfehlung: ${data.final_recommendation} | Conviction: ${data.conviction_level} | Price Target: ${data.currency || ""} ${data.price_target}`);
}

main().catch(console.error);
