/**
 * export_memo.js — Professioneller Word-Export für den KI-Co-Analysten
 * Berner Fachhochschule | Bachelor Thesis 2025/26 | Luca Lüdi
 *
 * Usage: node export_memo.js <json_file> <output_file>
 * Oder:  node export_memo.js (liest von stdin)
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType, HeadingLevel,
  VerticalAlign, PageNumber, PageBreak, LevelFormat, Header, Footer,
} = require('docx');
const fs = require('fs');

// ── Farben ────────────────────────────────────────────────────
const C = {
  DARK_BLUE:  "1F3864",
  MID_BLUE:   "2E75B6",
  GOLD:       "C9A84C",
  LIGHT_GRAY: "F5F5F5",
  WHITE:      "FFFFFF",
  GREEN_BG:   "E8F5E9",
  YELLOW_BG:  "FFF8E1",
  RED_BG:     "FFEBEE",
  BLUE_BG:    "E3F2FD",
  GREEN_TXT:  "2E7D32",
  RED_TXT:    "C62828",
  BLUE_TXT:   "1565C0",
  GOLD_TXT:   "B8860B",
  GRAY_TXT:   "757575",
  HEADER_BG:  "0D2137",
};

// ── Hilfsfunktionen ───────────────────────────────────────────

function txt(text, opts = {}) {
  return new TextRun({
    text: String(text ?? "n/v"),
    font: "Arial",
    size: opts.size || 18,
    bold: opts.bold || false,
    italics: opts.italic || false,
    color: opts.color || "000000",
  });
}

function para(children, opts = {}) {
  return new Paragraph({
    spacing: { before: opts.before || 0, after: opts.after || 80 },
    alignment: opts.align || AlignmentType.LEFT,
    children: Array.isArray(children) ? children : [children],
    ...(opts.numbering ? { numbering: opts.numbering } : {}),
    ...(opts.border ? { border: opts.border } : {}),
  });
}

const borderAll = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders   = { top: borderAll, bottom: borderAll, left: borderAll, right: borderAll };
const noBorders = {
  top:    { style: BorderStyle.NONE },
  bottom: { style: BorderStyle.NONE },
  left:   { style: BorderStyle.NONE },
  right:  { style: BorderStyle.NONE },
};

function cell(children, opts = {}) {
  return new TableCell({
    borders: opts.noBorder ? noBorders : borders,
    width: { size: opts.width || 1000, type: WidthType.DXA },
    shading: opts.bg ? { fill: opts.bg, type: ShadingType.CLEAR } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    columnSpan: opts.span || 1,
    children: Array.isArray(children) ? children : [children],
  });
}

function sectionHeader(title) {
  return new Paragraph({
    spacing: { before: 280, after: 140 },
    border: {
      bottom: { style: BorderStyle.SINGLE, size: 6, color: C.GOLD, space: 2 }
    },
    children: [txt(title, { size: 24, bold: true, color: C.DARK_BLUE })],
  });
}

function ratingColor(rating) {
  const r = (rating || "").toUpperCase();
  if (r === "KAUFEN" || r === "ÜBERGEWICHTEN") return C.GREEN_TXT;
  if (r === "VERKAUFEN" || r === "UNTERGEWICHTEN") return C.RED_TXT;
  return C.GOLD_TXT;
}

function assessColor(assess) {
  if (assess === "DISCOUNT") return C.BLUE_TXT;
  if (assess === "ELEVATED") return C.RED_TXT;
  return C.GREEN_TXT;
}

function assessBg(assess) {
  if (assess === "DISCOUNT") return C.BLUE_BG;
  if (assess === "ELEVATED") return C.RED_BG;
  return C.GREEN_BG;
}

function assessIcon(assess) {
  if (assess === "DISCOUNT") return "🔵 ";
  if (assess === "ELEVATED") return "🔴 ";
  return "🟢 ";
}

function signalColor(signal) {
  const s = (signal || "").toUpperCase();
  if (s === "POSITIV" || s === "TAILWIND") return C.GREEN_TXT;
  if (s === "NEGATIV" || s === "HEADWIND") return C.RED_TXT;
  return C.GOLD_TXT;
}

function signalIcon(signal) {
  const s = (signal || "").toUpperCase();
  if (s === "POSITIV" || s === "TAILWIND") return "🟢 ";
  if (s === "NEGATIV" || s === "HEADWIND") return "🔴 ";
  return "🟡 ";
}

function scenarioBorder(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("bull")) return { color: "43A047", bg: C.GREEN_BG };
  if (n.includes("bear")) return { color: "E53935", bg: C.RED_BG  };
  return { color: "F9A825", bg: C.YELLOW_BG };
}

function scenarioIcon(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("bull")) return "🐂";
  if (n.includes("bear")) return "🐻";
  return "⚖️";
}

function priceColor(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("bull")) return C.GREEN_TXT;
  if (n.includes("bear")) return C.RED_TXT;
  return C.GOLD_TXT;
}

function safeVal(v) {
  if (v === null || v === undefined || v === "" || v === "n/v") return "n/v";
  return String(v);
}

// ── Haupt-Export-Funktion ─────────────────────────────────────

function buildMemo(DATA) {
  const ticker  = safeVal(DATA.ticker);
  const company = safeVal(DATA.company || DATA.company_name || ticker);
  const sector  = safeVal(DATA.sector  || DATA.industry || "");
  const date    = safeVal(DATA.date    || new Date().toLocaleDateString("de-CH"));
  const rating  = safeVal(DATA.final_recommendation || DATA.recommendation || "HALTEN");
  const prevRating = safeVal(DATA.prev_rating || "");
  const pt      = safeVal(DATA.price_target || "n/v");
  const price   = safeVal(DATA.current_price || "n/v");
  const upside  = safeVal(DATA.upside_downside_pct
    ? (DATA.upside_downside_pct > 0 ? "+" : "") + DATA.upside_downside_pct + "%"
    : DATA.upside || "n/v");
  const ccy     = safeVal(DATA.currency || "CHF");
  const conviction = safeVal(DATA.conviction_level || "n/v");
  const mktCap  = safeVal(DATA.market_cap || "n/v");
  const score   = safeVal(DATA.data_consistency_score || "n/v");
  const desc    = safeVal(DATA.company_description || "");
  const finalReasoning = safeVal(DATA.final_reasoning || "");

  const children = [];

  // ══════════════════════════════════════════════════════════
  // HEADER BLOCK
  // ══════════════════════════════════════════════════════════
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [6200, 3160],
    rows: [new TableRow({
      children: [
        cell([
          para([txt(company, { size: 36, bold: true, color: C.WHITE })],
            { after: 80 }),
          para([txt(`${ticker}  ·  ${sector}  ·  ${date}`,
            { size: 16, color: "B0BEC5" })], { after: 60 }),
          para([txt("KI-Co-Analyst  ·  BFH Bachelor Thesis 2025/26  ·  Luca Lüdi",
            { size: 14, color: "78909C", italic: true })]),
        ], { width: 6200, bg: C.DARK_BLUE, noBorder: true }),

        cell([
          para([txt("Empfehlung", { size: 14, color: "B0BEC5" })],
            { align: AlignmentType.CENTER, after: 40 }),
          para([txt(rating, { size: 28, bold: true, color: ratingColor(rating) })],
            { align: AlignmentType.CENTER, after: 40 }),
          ...(prevRating ? [para([txt(`vorher: ${prevRating}`,
            { size: 14, color: "78909C" })],
            { align: AlignmentType.CENTER })] : []),
        ], { width: 3160, bg: C.HEADER_BG, noBorder: true }),
      ]
    })]
  }));

  // Key Metrics
  const metrics = [
    { label: "Aktueller Kurs",      value: `${ccy} ${price}` },
    { label: "Kursziel (12M)",      value: `${ccy} ${pt}` },
    { label: "Upside / Downside",   value: upside },
    { label: "Marktkapitalisierung",value: mktCap },
    { label: "Conviction Level",    value: conviction },
  ];
  const metricW = Math.floor(9360 / metrics.length);
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: metrics.map(() => metricW),
    rows: [new TableRow({
      children: metrics.map(m => cell([
        para([txt(m.label, { size: 13, color: C.GRAY_TXT })],
          { align: AlignmentType.CENTER, after: 30 }),
        para([txt(m.value, {
          size: 22, bold: true,
          color: m.value.includes("+") ? C.GREEN_TXT
               : m.value.startsWith("-") ? C.RED_TXT
               : C.DARK_BLUE
        })], { align: AlignmentType.CENTER }),
      ], { width: metricW, bg: C.LIGHT_GRAY }))
    })]
  }));

  children.push(para([]));

  // ══════════════════════════════════════════════════════════
  // 1. UNTERNEHMENSBESCHREIBUNG
  // ══════════════════════════════════════════════════════════
  children.push(sectionHeader("1.  Unternehmensbeschreibung"));
  children.push(para([txt(desc, { size: 18 })], { after: 160 }));

  // ══════════════════════════════════════════════════════════
  // 2. INVESTMENT CASE
  // ══════════════════════════════════════════════════════════
  children.push(sectionHeader("2.  Investment Case"));

  const ic = DATA.investment_case || [];
  if (ic.length === 0) {
    children.push(para([txt("Kein Investment Case verfügbar.", { size: 17, color: C.GRAY_TXT })]))
  } else {
    ic.forEach((point, i) => {
      const title = typeof point === "string" ? `${i+1}. Argument` : (point.title || point.point || `Argument ${i+1}`);
      const text  = typeof point === "string" ? point : (point.text || point.reasoning || "");
      const src   = typeof point === "object"  ? (point.source || "") : "";

      children.push(new Table({
        width: { size: 9360, type: WidthType.DXA },
        columnWidths: [140, 9220],
        rows: [new TableRow({
          children: [
            cell([para([txt("▌", { size: 22, bold: true, color: C.GOLD })])],
              { width: 140, noBorder: true }),
            cell([
              para([txt(title, { size: 19, bold: true, color: C.DARK_BLUE })], { after: 60 }),
              para([txt(text,  { size: 17 })], { after: src ? 40 : 0 }),
              ...(src ? [para([txt(`Quelle: ${src}`, { size: 14, italic: true, color: C.GRAY_TXT })])] : []),
            ], { width: 9220, bg: C.LIGHT_GRAY }),
          ]
        })]
      }));
      children.push(para([], { after: 80 }));
    });
  }

  // ══════════════════════════════════════════════════════════
  // 3. FINANZÜBERSICHT
  // ══════════════════════════════════════════════════════════
  children.push(new Paragraph({ children: [new PageBreak()] }));
  children.push(sectionHeader("3.  Finanzübersicht (in Mrd. Berichtswährung, ausser je Aktie)"));

  const fin = DATA.full_financials || DATA.consensus_estimates || [];
  if (fin.length > 0) {
    const finHeaders = ["Jahr","Umsatz","EBITDA","EBITDA-%","EBIT-%","EPS","DPS","FCF","ND/EBITDA","ROIC-%","Quelle"];
    const finCols    = [900,  900,    900,     800,      700,    680, 680, 680, 800,       700,     1420];
    const finTotal   = finCols.reduce((a,b) => a+b, 0);

    children.push(new Table({
      width: { size: finTotal, type: WidthType.DXA },
      columnWidths: finCols,
      rows: [
        // Header
        new TableRow({
          tableHeader: true,
          children: finHeaders.map((h, i) => cell(
            [para([txt(h, { size: 15, bold: true, color: C.WHITE })],
              { align: AlignmentType.CENTER })],
            { width: finCols[i], bg: C.DARK_BLUE }
          ))
        }),
        // Daten
        ...fin.map((row, ri) => {
          const isEst = (row.year || row.type || "").toString().includes("E");
          const bg = isEst ? C.YELLOW_BG : (ri % 2 === 0 ? C.WHITE : C.LIGHT_GRAY);
          const vals = [
            (isEst ? "📊 " : "") + safeVal(row.year),
            safeVal(row.revenue_bn  || row.umsatz),
            safeVal(row.ebitda_bn   || row.ebitda),
            safeVal(row.ebitda_margin_pct || row.ebitda_m),
            safeVal(row.ebit_margin_pct   || row.ebit_m),
            safeVal(row.eps_adj     || row.eps),
            safeVal(row.dps),
            safeVal(row.fcf_bn      || row.fcf),
            safeVal(row.nd_ebitda   || row.nd_ev),
            safeVal(row.roic_pct    || row.roic),
            safeVal(row.source      || row.src || (isEst ? "Schätzung" : "GBR")),
          ];
          return new TableRow({
            children: vals.map((v, i) => cell(
              [para([txt(v, {
                size: 15,
                bold: i === 0,
                color: i === 0 && isEst ? "E65100" : "222222"
              })], { align: i <= 0 ? AlignmentType.LEFT : AlignmentType.CENTER })],
              { width: finCols[i], bg }
            ))
          });
        }),
        // Fussnote
        new TableRow({
          children: [
            cell([para([txt("ℹ", { size: 15, bold: true, color: C.GRAY_TXT })])],
              { width: finCols[0], bg: C.LIGHT_GRAY }),
            new TableCell({
              columnSpan: finHeaders.length - 1,
              borders, shading: { fill: C.LIGHT_GRAY, type: ShadingType.CLEAR },
              margins: { top: 60, bottom: 60, left: 120, right: 120 },
              width: { size: finTotal - finCols[0], type: WidthType.DXA },
              children: [para([txt(
                "A = Istzahlen (geprüft)  |  📊 E = Schätzwert  |  " +
                "Forward-Schätzungen sind Approximationen — kein Ersatz für Bloomberg/FactSet Konsensdaten.",
                { size: 13, italic: true, color: C.GRAY_TXT }
              )])]
            })
          ]
        })
      ]
    }));
  } else {
    children.push(para([txt("Keine Finanzdaten verfügbar.", { size: 17, color: C.GRAY_TXT })]));
  }

  // ══════════════════════════════════════════════════════════
  // 4. BEWERTUNG
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("4.  Bewertung — ELEVATED / FAIR / DISCOUNT"));

  const vt = DATA.valuation_table || [];
  if (vt.length > 0) {
    const valCols = [1900, 1200, 1300, 1260, 1500, 2200];
    const valTotal = valCols.reduce((a,b) => a+b, 0);
    children.push(new Table({
      width: { size: valTotal, type: WidthType.DXA },
      columnWidths: valCols,
      rows: [
        new TableRow({
          tableHeader: true,
          children: ["Kennzahl","Aktuell","Peer-Median","Hist. Ø 5J","Einschätzung","Herleitung / Quelle"]
            .map((h, i) => cell(
              [para([txt(h, { size: 15, bold: true, color: C.WHITE })],
                { align: AlignmentType.CENTER })],
              { width: valCols[i], bg: C.DARK_BLUE }
            ))
        }),
        ...vt.map((row, ri) => {
          const assess = safeVal(row.assessment || "FAIR");
          const calcText = safeVal(row.calculation || row.source || "");
          return new TableRow({
            children: [
              cell([para([txt(safeVal(row.metric), { size: 16, bold: true })])],
                { width: valCols[0], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
              cell([para([txt(safeVal(row.current_value), { size: 16, bold: true, color: C.DARK_BLUE })],
                { align: AlignmentType.CENTER })],
                { width: valCols[1], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
              cell([para([txt(safeVal(row.peer_average), { size: 16 })],
                { align: AlignmentType.CENTER })],
                { width: valCols[2], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
              cell([para([txt(safeVal(row.historical_average), { size: 16 })],
                { align: AlignmentType.CENTER })],
                { width: valCols[3], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
              cell([para([txt(assessIcon(assess) + assess,
                { size: 15, bold: true, color: assessColor(assess) })],
                { align: AlignmentType.CENTER })],
                { width: valCols[4], bg: assessBg(assess) }),
              cell([para([txt(calcText, { size: 14, italic: true, color: C.GRAY_TXT })])],
                { width: valCols[5], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
            ]
          });
        })
      ]
    }));
  } else {
    children.push(para([txt("Keine Bewertungsdaten verfügbar.", { size: 17, color: C.GRAY_TXT })]));
  }

  // ══════════════════════════════════════════════════════════
  // 5. PEER-VERGLEICH
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("5.  Peer-Vergleich"));

  const pc = DATA.peer_comparison || {};
  const peers = pc.peers || [];
  const secAvg = pc.sector_averages;
  const subject = pc.subject_company;

  if (peers.length > 0 || secAvg || subject) {
    const peerCols = [2400, 900, 1100, 1100, 1100, 1100, 1100, 560];
    const peerTotal = peerCols.reduce((a,b) => a+b, 0);
    const allRows = [
      ...peers,
      ...(secAvg  ? [{ ...secAvg,  _isAvg: true }] : []),
      ...(subject ? [{ ...subject, _isSubject: true }] : []),
    ];

    children.push(new Table({
      width: { size: peerTotal, type: WidthType.DXA },
      columnWidths: peerCols,
      rows: [
        new TableRow({
          tableHeader: true,
          children: ["Unternehmen","Ticker","EV/EBITDA","Fwd. P/E","EBIT-%","ND/EBITDA","Div.-Yield","Wachstum"]
            .map((h,i) => cell(
              [para([txt(h, { size: 14, bold: true, color: C.WHITE })],
                { align: AlignmentType.CENTER })],
              { width: peerCols[i], bg: C.DARK_BLUE }
            ))
        }),
        ...allRows.map((p, ri) => {
          const isSub = p._isSubject;
          const isAvg = p._isAvg;
          const bg = isSub ? C.BLUE_BG : isAvg ? C.LIGHT_GRAY : (ri%2===0 ? C.WHITE : "FAFAFA");
          const prefix = isSub ? "⭐ " : isAvg ? "Ø  " : "";
          const vals = [
            prefix + safeVal(p.company),
            safeVal(p.ticker),
            safeVal(p.ev_ebitda),
            safeVal(p.forward_pe),
            safeVal(p.ebit_margin_pct),
            safeVal(p.nd_ebitda),
            safeVal(p.dividend_yield_pct || p.dividend_yield),
            safeVal(p.revenue_growth_pct || p.revenue_growth),
          ];
          return new TableRow({
            children: vals.map((v, i) => cell(
              [para([txt(v, {
                size: 15,
                bold: isSub || isAvg,
                color: isSub && i > 0 ? C.MID_BLUE : "222222"
              })], { align: i <= 1 ? AlignmentType.LEFT : AlignmentType.CENTER })],
              { width: peerCols[i], bg }
            ))
          });
        })
      ]
    }));

    // Abweichung Subject vs. Ø
    const vsAvg = pc.subject_vs_avg;
    if (vsAvg && Object.keys(vsAvg).length > 0) {
      children.push(para([], { before: 80 }));
      children.push(para([txt("Subject vs. Sektor-Ø:", { size: 16, bold: true, color: C.DARK_BLUE })]));
      const entries = Object.entries(vsAvg);
      const deltaW = Math.floor(9360 / Math.min(entries.length, 6));
      children.push(new Table({
        width: { size: deltaW * Math.min(entries.length, 6), type: WidthType.DXA },
        columnWidths: entries.slice(0,6).map(() => deltaW),
        rows: [new TableRow({
          children: entries.slice(0,6).map(([k, v]) => {
            const numVal = parseFloat(String(v).replace("%","").replace("+",""));
            const vColor = numVal < -10 ? C.GREEN_TXT : numVal > 10 ? C.RED_TXT : C.GOLD_TXT;
            return cell([
              para([txt(k, { size: 13, color: C.GRAY_TXT })],
                { align: AlignmentType.CENTER, after: 30 }),
              para([txt(String(v), { size: 18, bold: true, color: vColor })],
                { align: AlignmentType.CENTER }),
            ], { width: deltaW, bg: C.LIGHT_GRAY });
          })
        })]
      }));
    }
  } else {
    children.push(para([txt("Kein Peer-Vergleich verfügbar.", { size: 17, color: C.GRAY_TXT })]));
  }

  // ══════════════════════════════════════════════════════════
  // 6. SZENARIEN
  // ══════════════════════════════════════════════════════════
  children.push(new Paragraph({ children: [new PageBreak()] }));
  children.push(sectionHeader("6.  Szenarien — Bear / Base / Bull Case"));

  const scenarios = DATA.scenarios || [];
  if (scenarios.length > 0) {
    const nSc = Math.min(scenarios.length, 3);
    const scW = Math.floor(9200 / nSc);
    children.push(new Table({
      width: { size: scW * nSc + 160, type: WidthType.DXA },
      columnWidths: [...Array(nSc).fill(scW), 160],
      rows: [new TableRow({
        children: [
          ...scenarios.slice(0, nSc).map(sc => {
            const { color, bg } = scenarioBorder(sc.name || "");
            const name = safeVal(sc.name);
            const ptVal = safeVal(sc.price_target);
            const prob  = safeVal(sc.probability_pct);
            const key   = safeVal(sc.key_assumption);
            const trig  = safeVal(sc.trigger);
            return new TableCell({
              borders: {
                top:    { style: BorderStyle.SINGLE, size: 8,  color },
                bottom: { style: BorderStyle.SINGLE, size: 2,  color },
                left:   { style: BorderStyle.SINGLE, size: 8,  color },
                right:  { style: BorderStyle.SINGLE, size: 2,  color },
              },
              width: { size: scW, type: WidthType.DXA },
              shading: { fill: bg, type: ShadingType.CLEAR },
              margins: { top: 160, bottom: 160, left: 200, right: 200 },
              children: [
                para([txt(`${scenarioIcon(name)}  ${name}`,
                  { size: 20, bold: true, color: C.DARK_BLUE })], { after: 80 }),
                para([txt(ptVal,
                  { size: 30, bold: true, color: priceColor(name) })],
                  { align: AlignmentType.CENTER, after: 60 }),
                para([txt(`Wahrscheinlichkeit: ${prob}%`,
                  { size: 16, bold: true, color: C.GRAY_TXT })],
                  { align: AlignmentType.CENTER, after: 120 }),
                ...(key !== "n/v" ? [
                  para([txt("Kernannahme:", { size: 14, bold: true, color: C.DARK_BLUE })], { after: 40 }),
                  para([txt(key, { size: 15 })], { after: 80 }),
                ] : []),
                ...(trig !== "n/v" ? [
                  para([txt("Auslöser:", { size: 14, bold: true, color: C.DARK_BLUE })], { after: 40 }),
                  para([txt(trig, { size: 15 })]),
                ] : []),
              ]
            });
          }),
          // Spacer
          cell([para([txt("")])], { width: 160, noBorder: true }),
        ]
      })]
    }));
  } else {
    children.push(para([txt("Keine Szenarien verfügbar.", { size: 17, color: C.GRAY_TXT })]));
  }

  // ══════════════════════════════════════════════════════════
  // 7. RISIKEN & CONVICTION KILLERS
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("7.  Quantifizierte Risiken & Conviction Killers"));

  const risks = DATA.key_risks || [];
  const cks   = DATA.conviction_killers || [];

  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [4560, 4800],
    rows: [new TableRow({
      children: [
        cell([
          para([txt("Quantifizierte Risiken", { size: 18, bold: true, color: C.DARK_BLUE })],
            { after: 120 }),
          ...(risks.length > 0
            ? risks.map(r => new Paragraph({
                spacing: { before: 60, after: 60 },
                numbering: { reference: "bullets", level: 0 },
                children: [txt(typeof r === "string" ? r : safeVal(r.risk || r.description || r), { size: 16 })],
              }))
            : [para([txt("Keine Risiken dokumentiert.", { size: 16, color: C.GRAY_TXT })])]),
        ], { width: 4560 }),

        cell([
          para([txt("🚨  Conviction Killers", { size: 18, bold: true, color: C.RED_TXT })],
            { after: 80 }),
          para([txt("Datenpunkte die den Investment Case sofort entkräften:",
            { size: 14, italic: true, color: C.GRAY_TXT })], { after: 120 }),
          ...(cks.length > 0
            ? cks.map(ck => {
                const desc    = typeof ck === "string" ? ck : safeVal(ck.description || ck);
                const monitor = typeof ck === "object" ? safeVal(ck.monitoring_indicator || "") : "";
                return new Table({
                  width: { size: 4500, type: WidthType.DXA },
                  columnWidths: [4500],
                  rows: [new TableRow({ children: [
                    cell([
                      para([txt("⚠  " + desc, { size: 15, bold: true, color: C.RED_TXT })],
                        { after: monitor && monitor !== "n/v" ? 40 : 0 }),
                      ...(monitor && monitor !== "n/v"
                        ? [para([txt("→ Monitor: " + monitor, { size: 14, color: C.GRAY_TXT, italic: true })])]
                        : []),
                    ], { width: 4500, bg: C.RED_BG })
                  ]})]
                });
              })
            : [para([txt("Keine Conviction Killers identifiziert.",
                { size: 16, color: C.GRAY_TXT })])]),
        ], { width: 4800 }),
      ]
    })]
  }));

  // ══════════════════════════════════════════════════════════
  // 8. MAKRO & SENTIMENT
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("8.  Makro-Ampel & Sentiment"));

  const macro = DATA.macro_ampel || [];
  if (macro.length > 0) {
    const macCols = [1700, 1200, 6460];
    const macTotal = macCols.reduce((a,b) => a+b, 0);
    children.push(new Table({
      width: { size: macTotal, type: WidthType.DXA },
      columnWidths: macCols,
      rows: [
        new TableRow({
          tableHeader: true,
          children: ["Beobachtungsbereich","Signal","Einschätzung & Transmissionsmechanismus"]
            .map((h,i) => cell(
              [para([txt(h, { size: 15, bold: true, color: C.WHITE })],
                { align: AlignmentType.CENTER })],
              { width: macCols[i], bg: C.DARK_BLUE }
            ))
        }),
        ...macro.map((m, ri) => {
          const sig = safeVal(m.signal || m.direction || "NEUTRAL");
          const sigBg = sig.toUpperCase() === "POSITIV" || sig.toUpperCase() === "TAILWIND"
            ? C.GREEN_BG : sig.toUpperCase() === "NEGATIV" || sig.toUpperCase() === "HEADWIND"
            ? C.RED_BG : C.YELLOW_BG;
          return new TableRow({ children: [
            cell([para([txt(safeVal(m.category || m.label || m.indicator),
              { size: 16, bold: true })])],
              { width: macCols[0], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
            cell([para([txt(signalIcon(sig) + sig,
              { size: 15, bold: true, color: signalColor(sig) })],
              { align: AlignmentType.CENTER })],
              { width: macCols[1], bg: sigBg }),
            cell([para([txt(safeVal(m.key_point || m.text || m.description),
              { size: 16 })])],
              { width: macCols[2], bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
          ]});
        })
      ]
    }));
  } else {
    children.push(para([txt("Keine Makro-Daten verfügbar.", { size: 17, color: C.GRAY_TXT })]));
  }

  // Sentiment Score
  const sentScore = DATA.sentiment_score || DATA.overall_sentiment_score;
  const sentOutlook = DATA.sentiment_outlook || DATA.short_term_outlook;
  if (sentScore || sentOutlook) {
    children.push(para([], { before: 120 }));
    children.push(new Table({
      width: { size: 9360, type: WidthType.DXA },
      columnWidths: [2000, 7360],
      rows: [new TableRow({ children: [
        cell([
          para([txt("Sentiment-Score", { size: 14, color: C.GRAY_TXT })],
            { align: AlignmentType.CENTER, after: 30 }),
          para([txt(safeVal(sentScore) + "/10",
            { size: 28, bold: true, color: C.DARK_BLUE })],
            { align: AlignmentType.CENTER }),
        ], { width: 2000, bg: C.LIGHT_GRAY }),
        cell([
          para([txt("Kurzfrist-Outlook:", { size: 14, bold: true, color: C.DARK_BLUE })],
            { after: 40 }),
          para([txt(safeVal(sentOutlook), { size: 16 })]),
        ], { width: 7360 }),
      ]})]
    }));
  }

  // ══════════════════════════════════════════════════════════
  // 9. QUALITÄTSPRÜFUNG
  // ══════════════════════════════════════════════════════════
  children.push(new Paragraph({ children: [new PageBreak()] }));
  children.push(sectionHeader("9.  Qualitätsprüfung & Konsistenz-Score"));

  // Score Box + Checks nebeneinander
  const qcChecks = DATA.quality_checks || [];
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [2000, 7360],
    rows: [new TableRow({
      children: [
        // Score links
        cell([
          para([txt("Konsistenz-Score", { size: 14, color: C.GRAY_TXT, bold: true })],
            { align: AlignmentType.CENTER, after: 80 }),
          para([txt(safeVal(score) + "/10", {
            size: 56, bold: true,
            color: Number(score) >= 7 ? C.GREEN_TXT
                 : Number(score) >= 5 ? C.GOLD_TXT : C.RED_TXT
          })], { align: AlignmentType.CENTER, after: 80 }),
          para([txt(safeVal(DATA.consistency_notes || ""),
            { size: 14, italic: true, color: C.GRAY_TXT })],
            { align: AlignmentType.CENTER }),
        ], { width: 2000, bg: C.LIGHT_GRAY }),

        // Checks rechts
        cell([
          ...(qcChecks.length > 0
            ? qcChecks.map((qc, ri) => {
                const result = safeVal(qc.result || qc.status);
                const icon   = result === "bestanden" ? "✅" : result === "Warnung" ? "⚠️" : "❌";
                const bg     = result === "bestanden" ? C.GREEN_BG
                             : result === "Warnung"   ? C.YELLOW_BG : C.RED_BG;
                return new Table({
                  width: { size: 7100, type: WidthType.DXA },
                  columnWidths: [3200, 1000, 2900],
                  rows: [new TableRow({ children: [
                    cell([para([txt(safeVal(qc.check || qc.name), { size: 15 })])],
                      { width: 3200, bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
                    cell([para([txt(`${icon} ${result}`, { size: 14, bold: true })],
                      { align: AlignmentType.CENTER })],
                      { width: 1000, bg }),
                    cell([para([txt(safeVal(qc.comment || qc.note || ""),
                      { size: 14, italic: true, color: C.GRAY_TXT })])],
                      { width: 2900, bg: ri%2===0 ? C.WHITE : C.LIGHT_GRAY }),
                  ]})]
                });
              })
            : [para([txt("Keine Qualitätschecks verfügbar.", { size: 16, color: C.GRAY_TXT })])]),
        ], { width: 7360 }),
      ]
    })]
  }));

  // ══════════════════════════════════════════════════════════
  // 10. FINALE BEGRÜNDUNG
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("10. Finale Begründung"));
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({ children: [
      cell([para([txt(finalReasoning, { size: 17 })])],
        { width: 9360, bg: C.BLUE_BG })
    ]})]
  }));

  // ══════════════════════════════════════════════════════════
  // 11. QUELLEN & LITERATURVERZEICHNIS
  // ══════════════════════════════════════════════════════════
  children.push(para([], { before: 200 }));
  children.push(sectionHeader("11. Quellen & Literaturverzeichnis"));

  const sources = DATA.sources || [];
  if (sources.length > 0) {
    sources.forEach((src, i) => {
      children.push(para(
        [txt(`[${i+1}]  ${safeVal(src)}`, { size: 15, color: C.GRAY_TXT })],
        { before: 40, after: 40 }
      ));
    });
  } else {
    children.push(para([txt("Keine Quellenangaben verfügbar.", { size: 15, color: C.GRAY_TXT })]));
  }

  // DISCLAIMER
  children.push(para([], { before: 200 }));
  children.push(new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({ children: [
      cell([para([txt(
        "DISCLAIMER: Dieses Dokument wurde automatisch durch den KI-Co-Analysten generiert " +
        "(Bachelor Thesis BFH 2025/26, Luca Lüdi) und dient ausschliesslich zu Forschungs- und " +
        "Demonstrationszwecken. Es stellt keine Anlageberatung dar (Art. 3 lit. c FIDLEG). " +
        "Alle Angaben basieren auf öffentlich verfügbaren Daten. " +
        "Forward-Schätzungen sind Approximationen — kein Ersatz für Bloomberg/FactSet Konsensdaten. " +
        "Eine Haftung für die Richtigkeit der Angaben wird nicht übernommen.",
        { size: 14, italic: true, color: C.GRAY_TXT }
      )])], { width: 9360, bg: C.LIGHT_GRAY })
    ]})]
  }));

  // ── Routing-Log (optional, ausgeblendet) ─────────────────
  const routingLog = DATA.routing_log || [];
  if (routingLog.length > 0) {
    children.push(para([], { before: 200 }));
    children.push(sectionHeader("Anhang: LangGraph Routing-Log"));
    routingLog.forEach(entry => {
      children.push(para(
        [txt(safeVal(entry), { size: 14, color: C.GRAY_TXT })],
        { before: 20, after: 20 }
      ));
    });
  }

  // ── Dokument zusammenbauen ───────────────────────────────
  return new Document({
    numbering: {
      config: [{
        reference: "bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "▸",
          alignment: AlignmentType.LEFT,
          style: {
            paragraph: { indent: { left: 400, hanging: 280 } }
          }
        }]
      }]
    },
    styles: {
      default: {
        document: { run: { font: "Arial", size: 18 } }
      }
    },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: { top: 900, right: 800, bottom: 900, left: 800 }
        }
      },

      headers: {
        default: new Header({
          children: [new Table({
            width: { size: 10306, type: WidthType.DXA },
            columnWidths: [6000, 4306],
            rows: [new TableRow({ children: [
              cell([para([
                txt(`${company}  (${ticker})`, { size: 15, bold: true, color: C.DARK_BLUE })
              ])], { width: 6000, noBorder: true }),
              cell([para([
                txt("KI-Co-Analyst  ·  BFH 2025/26", { size: 14, color: C.GRAY_TXT })
              ], { align: AlignmentType.RIGHT })], { width: 4306, noBorder: true }),
            ]})]
          })]
        })
      },

      footers: {
        default: new Footer({
          children: [new Table({
            width: { size: 10306, type: WidthType.DXA },
            columnWidths: [6000, 4306],
            rows: [new TableRow({ children: [
              cell([para([
                txt(`${rating}  |  Kursziel ${ccy} ${pt}  |  Upside ${upside}`,
                  { size: 14, bold: true, color: ratingColor(rating) })
              ])], { width: 6000, noBorder: true }),
              cell([para([
                txt("Seite ", { size: 14, color: C.GRAY_TXT }),
                new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 14 }),
                txt(" / ", { size: 14, color: C.GRAY_TXT }),
                new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 14 }),
              ], { align: AlignmentType.RIGHT })], { width: 4306, noBorder: true }),
            ]})]
          })]
        })
      },

      children,
    }]
  });
}

// ── CLI Entry Point ───────────────────────────────────────────

async function main() {
  let data;

  // JSON aus Argument oder Stdin lesen
  if (process.argv[2] && fs.existsSync(process.argv[2])) {
    data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  } else {
    // Von stdin lesen (für Streamlit-Integration)
    const chunks = [];
    for await (const chunk of process.stdin) chunks.push(chunk);
    data = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  }

  const outputPath = process.argv[3] || "investment_memo.docx";

  const doc = buildMemo(data);
  const buf = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buf);
  console.log(`OK: ${buf.length} bytes → ${outputPath}`);
}

main().catch(e => {
  console.error("Fehler:", e.message);
  process.exit(1);
});