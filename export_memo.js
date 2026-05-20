/**
 * export_memo.js — KI-Co-Analyst Word Export
 * Basiert auf dem Alcon-Memo Format (ALC.SW_20260519)
 * Layout: A4, Ränder 0.5cm oben/unten, 1cm links/rechts
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType,
  VerticalAlign, PageNumber, PageBreak, LevelFormat, Header, Footer,
} = require('docx');
const fs = require('fs');

// A4: 11906 DXA breit, Ränder L/R 567 → nutzbar 10772
const PAGE_W = 10772;
const MARGIN_TOP = 284, MARGIN_BOTTOM = 284;
const MARGIN_LEFT = 567, MARGIN_RIGHT = 567;

const C = {
  DARK_BLUE: "1F3864", HEADER_BG: "0D2137", GOLD: "C9A84C",
  LIGHT_GRAY: "F5F5F5", WHITE: "FFFFFF",
  GREEN_BG: "E8F5E9", YELLOW_BG: "FFF8E1", RED_BG: "FFEBEE", BLUE_BG: "E3F2FD",
  GREEN_TXT: "2E7D32", RED_TXT: "C62828", BLUE_TXT: "1565C0",
  GOLD_TXT: "B8860B", GRAY_TXT: "757575", LIGHT_BLUE: "B0BEC5",
};

const borderLine = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders    = { top: borderLine, bottom: borderLine, left: borderLine, right: borderLine };
const noBorders  = {
  top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
  left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
};

function safeStr(v) {
  if (v === null || v === undefined || v === "") return "n/v";
  return String(v);
}

function txt(text, opts = {}) {
  return new TextRun({
    text: safeStr(text), font: "Arial",
    size: opts.size || 18, bold: opts.bold || false,
    italics: opts.italic || false, color: opts.color || "000000",
  });
}

function para(children, opts = {}) {
  return new Paragraph({
    spacing: { before: opts.before || 0, after: opts.after !== undefined ? opts.after : 60 },
    alignment: opts.align || AlignmentType.LEFT,
    children: Array.isArray(children) ? children : [children],
    ...(opts.numbering ? { numbering: opts.numbering } : {}),
    ...(opts.border    ? { border: opts.border }       : {}),
  });
}

function cell(children, opts = {}) {
  return new TableCell({
    borders: opts.noBorder ? noBorders : borders,
    width: { size: opts.width || 1000, type: WidthType.DXA },
    shading: opts.bg ? { fill: opts.bg, type: ShadingType.CLEAR } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    columnSpan: opts.span || 1,
    children: Array.isArray(children) ? children : [children],
  });
}

function sectionHead(title) {
  return new Paragraph({
    spacing: { before: 180, after: 80 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: C.GOLD, space: 2 } },
    children: [txt(title, { size: 19, bold: true, color: C.DARK_BLUE })],
  });
}

function ratingColor(r) {
  const v = (r || "").toUpperCase();
  if (v === "KAUFEN" || v === "ÜBERGEWICHTEN") return C.GREEN_TXT;
  if (v === "VERKAUFEN" || v === "UNTERGEWICHTEN") return C.RED_TXT;
  return C.GOLD_TXT;
}

function assessBg(a) {
  if (a === "DISCOUNT") return C.BLUE_BG;
  if (a === "ELEVATED") return C.RED_BG;
  return C.GREEN_BG;
}
function assessColor(a) {
  if (a === "DISCOUNT") return C.BLUE_TXT;
  if (a === "ELEVATED") return C.RED_TXT;
  return C.GREEN_TXT;
}
function signalBg(s) {
  const v = (s || "").toUpperCase();
  if (v.includes("POSITIV") || v.includes("TAILWIND")) return C.GREEN_BG;
  if (v.includes("NEGATIV") || v.includes("HEADWIND")) return C.RED_BG;
  return C.YELLOW_BG;
}
function signalColor(s) {
  const v = (s || "").toUpperCase();
  if (v.includes("POSITIV") || v.includes("TAILWIND")) return C.GREEN_TXT;
  if (v.includes("NEGATIV") || v.includes("HEADWIND")) return C.RED_TXT;
  return C.GOLD_TXT;
}

function buildMemo(DATA) {
  const ticker  = safeStr(DATA.ticker);
  const company = safeStr(DATA.company || DATA.company_name || ticker);
  const sector  = safeStr(DATA.sector || DATA.industry || "");
  const dateStr = safeStr(DATA.date || new Date().toISOString().slice(0,10));
  const rating  = safeStr(DATA.final_recommendation || DATA.recommendation || "HALTEN");
  const pt      = safeStr(DATA.price_target || "n/v");
  const price   = safeStr(DATA.current_price || "n/v");
  const upsideV = DATA.upside_downside_pct;
  const upside  = upsideV != null
    ? ((parseFloat(upsideV) > 0 ? "+" : "") + parseFloat(upsideV).toFixed(2) + "%")
    : safeStr(DATA.upside || "n/v");
  const ccy     = safeStr(DATA.currency || "CHF");
  const conv    = safeStr(DATA.conviction_level || "n/v");
  const mktcap  = safeStr(DATA.market_cap || "n/v");
  const desc    = safeStr(DATA.company_description || "");
  const finalR  = safeStr(DATA.final_reasoning || "");

  const children = [];

  // ══════════════════════════════════════════════════════
  // HEADER: Firmenname | Rating
  // ══════════════════════════════════════════════════════
  children.push(new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [6200, 4572],
    rows: [new TableRow({
      children: [
        cell([
          para([txt(company, { size: 34, bold: true, color: C.WHITE })], { after: 60 }),
          para([txt(`${ticker}  ·  ${sector}  ·  ${dateStr}`, { size: 14, color: C.LIGHT_BLUE })], { after: 40 }),
          para([txt("KI-Co-Analyst  ·  BFH Bachelor Thesis 2025/26  ·  Luca Lüdi",
            { size: 12, color: "78909C", italic: true })], { after: 0 }),
        ], { width: 6200, bg: C.DARK_BLUE, noBorder: true }),
        cell([
          para([txt("Empfehlung", { size: 13, color: C.LIGHT_BLUE })],
            { align: AlignmentType.CENTER, after: 40 }),
          para([txt(rating, { size: 26, bold: true, color: ratingColor(rating) })],
            { align: AlignmentType.CENTER, after: 0 }),
        ], { width: 4572, bg: C.HEADER_BG, noBorder: true }),
      ]
    })]
  }));

  // Key Metrics: 5 Kacheln
  const metrics = [
    { label: "Aktueller Kurs",      value: `${ccy} ${price}` },
    { label: "Kursziel (12M)",      value: `${ccy} ${pt}` },
    { label: "Upside / Downside",   value: upside },
    { label: "Marktkapitalisierung",value: mktcap },
    { label: "Conviction Level",    value: conv },
  ];
  const mW = Math.floor(PAGE_W / metrics.length);
  children.push(new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: metrics.map(() => mW),
    rows: [new TableRow({
      children: metrics.map(m => cell([
        para([txt(m.label, { size: 12, color: C.GRAY_TXT })],
          { align: AlignmentType.CENTER, after: 20 }),
        para([txt(m.value, {
          size: 19, bold: true,
          color: m.value.includes("+") ? C.GREEN_TXT
               : (m.value.startsWith("-") && !m.value.startsWith("-n")) ? C.RED_TXT
               : C.DARK_BLUE,
        })], { align: AlignmentType.CENTER, after: 0 }),
      ], { width: mW, bg: C.LIGHT_GRAY }))
    })]
  }));

  // ══════════════════════════════════════════════════════
  // 1. UNTERNEHMENSBESCHREIBUNG
  // ══════════════════════════════════════════════════════
  children.push(sectionHead("1.  Unternehmensbeschreibung"));
  children.push(para([txt(desc, { size: 16 })], { after: 60 }));

  // ══════════════════════════════════════════════════════
  // 2. INVESTMENT CASE — Bulletpoints (keine Tabelle)
  // ══════════════════════════════════════════════════════
  children.push(sectionHead("2.  Investment Case"));

  const ic = DATA.investment_case || [];
  if (ic.length === 0) {
    children.push(para([txt("Kein Investment Case verfügbar.", { size: 16, color: C.GRAY_TXT })]));
  } else {
    ic.forEach(point => {
      const text = typeof point === "string"
        ? point
        : safeStr(point.text || point.point || point.reasoning || "");
      const src = typeof point === "object" ? safeStr(point.source || "") : "";
      children.push(new Paragraph({
        numbering: { reference: "bullets", level: 0 },
        spacing:   { before: 40, after: 40 },
        children:  [
          txt(text, { size: 16 }),
          ...(src && src !== "n/v"
            ? [txt(`  [${src}]`, { size: 13, color: C.GRAY_TXT, italic: true })]
            : []),
        ],
      }));
    });
  }

  // ══════════════════════════════════════════════════════
  // 3. FINANZÜBERSICHT
  // ══════════════════════════════════════════════════════
  children.push(sectionHead("3.  Finanzübersicht (in Mrd. Berichtswährung, ausser je Aktie)"));

  const fin = DATA.full_financials || DATA._full_financials || DATA.consensus_estimates || [];
  if (fin.length > 0) {
    const fH = ["Jahr","Umsatz","EBITDA","EBITDA-%","EBIT-%","EPS","DPS","FCF","ND/EBITDA","ROIC-%","Quelle"];
    const fC = [760, 840, 800, 760, 680, 620, 600, 680, 800, 680, 0];
    const fCBase = fC.slice(0,-1).reduce((a,b) => a+b, 0);
    fC[fC.length-1] = PAGE_W - fCBase;

    children.push(new Table({
      width: { size: PAGE_W, type: WidthType.DXA },
      columnWidths: fC,
      rows: [
        new TableRow({
          tableHeader: true,
          children: fH.map((h, i) => cell(
            [para([txt(h, { size: 13, bold: true, color: C.WHITE })],
              { align: AlignmentType.CENTER, after: 0 })],
            { width: fC[i], bg: C.DARK_BLUE }
          ))
        }),
        ...fin.map((row, ri) => {
          const isE = String(row.year || row.type || "").includes("E");
          const bg  = isE ? C.YELLOW_BG : (ri % 2 === 0 ? C.WHITE : C.LIGHT_GRAY);
          const vals = [
            (isE ? "📊 " : "") + safeStr(row.year),
            safeStr(row.revenue_bn   || row.umsatz),
            safeStr(row.ebitda_bn    || row.ebitda),
            safeStr(row.ebitda_margin_pct || row.ebitda_m),
            safeStr(row.ebit_margin_pct   || row.ebit_m),
            safeStr(row.eps_adj || row.eps),
            safeStr(row.dps),
            safeStr(row.fcf_bn  || row.fcf),
            safeStr(row.nd_ebitda || row.nd_ev),
            safeStr(row.roic_pct  || row.roic),
            safeStr(row.source || row.src || (isE ? "Schätzung" : "GBR")),
          ];
          return new TableRow({
            children: vals.map((v, i) => cell(
              [para([txt(v, { size: 13, bold: i === 0,
                color: i === 0 && isE ? "E65100" : "222222" })],
                { align: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER, after: 0 })],
              { width: fC[i], bg }
            ))
          });
        }),
        // Fussnote
        new TableRow({
          children: [
            cell([para([txt("ℹ", { size: 12, bold: true, color: C.GRAY_TXT })], { after: 0 })],
              { width: fC[0], bg: C.LIGHT_GRAY }),
            new TableCell({
              columnSpan: fH.length - 1,
              borders,
              shading: { fill: C.LIGHT_GRAY, type: ShadingType.CLEAR },
              margins: { top: 40, bottom: 40, left: 100, right: 100 },
              width: { size: PAGE_W - fC[0], type: WidthType.DXA },
              children: [para([txt(
                "A = Istzahlen (geprüft)  |  📊 E = Schätzwert  |  Forward-Schätzungen: Approximation — kein Ersatz für Bloomberg/FactSet",
                { size: 11, italic: true, color: C.GRAY_TXT }
              )], { after: 0 })]
            })
          ]
        })
      ]
    }));
  }

  // ══════════════════════════════════════════════════════
  // 4. BEWERTUNG gegenüber Peer und Historischen Kennzahlen
  // ══════════════════════════════════════════════════════
  children.push(sectionHead("4.  Bewertung gegenüber Peer und Historischen Kennzahlen"));

  const vt = DATA.valuation_table || [];
  if (vt.length > 0) {
    const vH = ["Kennzahl", "Aktuell", "Peer-Median", "Hist. Ø 5J", "Einschätzung"];
    const vC = [2200, 1400, 1400, 2400, 0];
    const vCBase = vC.slice(0,-1).reduce((a,b) => a+b, 0);
    vC[vC.length-1] = PAGE_W - vCBase;

    children.push(new Table({
      width: { size: PAGE_W, type: WidthType.DXA },
      columnWidths: vC,
      rows: [
        new TableRow({
          tableHeader: true,
          children: vH.map((h, i) => cell(
            [para([txt(h, { size: 13, bold: true, color: C.WHITE })],
              { align: AlignmentType.CENTER, after: 0 })],
            { width: vC[i], bg: C.DARK_BLUE }
          ))
        }),
        ...vt.map((row, ri) => {
          const assess = safeStr(row.assessment || "FAIR");
          const bg     = ri % 2 === 0 ? C.WHITE : C.LIGHT_GRAY;
          const histAvg = safeStr(row.historical_average || "-");
          return new TableRow({
            children: [
              cell([para([txt(safeStr(row.metric), { size: 14, bold: true })], { after: 0 })],
                { width: vC[0], bg }),
              cell([para([txt(safeStr(row.current_value), { size: 14, bold: true, color: C.DARK_BLUE })],
                { align: AlignmentType.CENTER, after: 0 })], { width: vC[1], bg }),
              cell([para([txt(safeStr(row.peer_average), { size: 14 })],
                { align: AlignmentType.CENTER, after: 0 })], { width: vC[2], bg }),
              cell([para([txt(histAvg, { size: 14 })],
                { align: AlignmentType.CENTER, after: 0 })], { width: vC[3], bg }),
              cell([para([txt(assess, { size: 13, bold: true, color: assessColor(assess) })],
                { align: AlignmentType.CENTER, after: 0 })],
                { width: vC[4], bg: assessBg(assess) }),
            ]
          });
        })
      ]
    }));
  }

  // ══════════════════════════════════════════════════════
  // 5. PEER-VERGLEICH
  // ══════════════════════════════════════════════════════
  const pc    = DATA.peer_comparison || DATA._peer_comparison || {};
  const peers = pc.peers || [];
  if (peers.length > 0 || pc.subject_company) {
    children.push(sectionHead("5.  Peer-Vergleich"));

    const pH = ["Unternehmen", "Land", "EV/EBITDA", "Fwd. P/E", "EBIT-%", "ND/EBITDA", "Div.-%", "Wachstum"];
    const pC = [2600, 800, 960, 880, 880, 960, 880, 0];
    const pCBase = pC.slice(0,-1).reduce((a,b) => a+b, 0);
    pC[pC.length-1] = PAGE_W - pCBase;

    const allPeers = [
      ...peers,
      ...(pc.sector_averages ? [{ ...pc.sector_averages, _avg: true }] : []),
      ...(pc.subject_company ? [{ ...pc.subject_company, _sub: true }] : []),
    ];

    children.push(new Table({
      width: { size: PAGE_W, type: WidthType.DXA },
      columnWidths: pC,
      rows: [
        new TableRow({
          tableHeader: true,
          children: pH.map((h, i) => cell(
            [para([txt(h, { size: 12, bold: true, color: C.WHITE })],
              { align: AlignmentType.CENTER, after: 0 })],
            { width: pC[i], bg: C.DARK_BLUE }
          ))
        }),
        ...allPeers.map((p, ri) => {
          const isSub = p._sub;
          const isAvg = p._avg;
          const bg    = isSub ? C.BLUE_BG : isAvg ? C.LIGHT_GRAY : (ri % 2 === 0 ? C.WHITE : "FAFAFA");
          const prefix = isSub ? "⭐ " : isAvg ? "Ø  " : "";
          // Div-Yield Plausibilitätsprüfung
          let divYield = safeStr(p.dividend_yield_pct || p.dividend_yield);
          if (divYield !== "n/v") {
            const dv = parseFloat(divYield);
            if (!isNaN(dv) && dv > 30) divYield = "n/v"; // ×100 Fehler abfangen
          }
          const vals = [
            prefix + safeStr(p.company),
            safeStr(p.country || ""),
            safeStr(p.ev_ebitda),
            safeStr(p.forward_pe),
            safeStr(p.ebit_margin_pct),
            safeStr(p.nd_ebitda),
            divYield,
            safeStr(p.revenue_growth_pct || p.revenue_growth),
          ];
          return new TableRow({
            children: vals.map((v, i) => cell(
              [para([txt(v, { size: 13, bold: isSub || isAvg,
                color: isSub && i > 1 ? C.BLUE_TXT : "222222" })],
                { align: i <= 1 ? AlignmentType.LEFT : AlignmentType.CENTER, after: 0 })],
              { width: pC[i], bg }
            ))
          });
        })
      ]
    }));
  }

  // ══════════════════════════════════════════════════════
  // 6. SZENARIEN
  // ══════════════════════════════════════════════════════
  const scenarios = DATA.scenarios || [];
  if (scenarios.length > 0) {
    children.push(sectionHead("6.  Szenarien — Bear / Base / Bull Case"));

    const nSc = Math.min(scenarios.length, 3);
    const scW = Math.floor(PAGE_W / nSc);
    const scWidths = Array(nSc).fill(scW);
    // Letztes nimmt Rest
    scWidths[nSc-1] = PAGE_W - scW * (nSc-1);

    children.push(new Table({
      width: { size: PAGE_W, type: WidthType.DXA },
      columnWidths: scWidths,
      rows: [new TableRow({
        children: scenarios.slice(0, nSc).map((sc, si) => {
          const name   = safeStr(sc.name || "");
          const isBull = name.toLowerCase().includes("bull");
          const isBear = name.toLowerCase().includes("bear");
          const bg     = isBull ? C.GREEN_BG : isBear ? C.RED_BG : C.YELLOW_BG;
          const bColor = isBull ? "43A047" : isBear ? "E53935" : "F9A825";
          const pColor = isBull ? C.GREEN_TXT : isBear ? C.RED_TXT : C.GOLD_TXT;
          const icon   = isBull ? "🐂" : isBear ? "🐻" : "⚖️";
          const ptVal  = safeStr(sc.price_target);
          const prob   = safeStr(sc.probability_pct);
          const key    = safeStr(sc.key_assumption || "");
          const trig   = safeStr(sc.trigger || "");

          return new TableCell({
            borders: {
              top:    { style: BorderStyle.SINGLE, size: 8, color: bColor },
              bottom: { style: BorderStyle.SINGLE, size: 2, color: bColor },
              left:   { style: BorderStyle.SINGLE, size: 8, color: bColor },
              right:  { style: BorderStyle.SINGLE, size: 2, color: bColor },
            },
            width:   { size: scWidths[si], type: WidthType.DXA },
            shading: { fill: bg, type: ShadingType.CLEAR },
            margins: { top: 100, bottom: 100, left: 120, right: 120 },
            children: [
              para([txt(`${icon}  ${name}`, { size: 16, bold: true, color: C.DARK_BLUE })], { after: 60 }),
              para([txt(ptVal, { size: 24, bold: true, color: pColor })],
                { align: AlignmentType.CENTER, after: 40 }),
              para([txt(`Wahrscheinlichkeit: ${prob}%`, { size: 13, bold: true, color: C.GRAY_TXT })],
                { align: AlignmentType.CENTER, after: 80 }),
              ...(key !== "n/v" ? [para([
                txt("Kernannahme: ", { size: 12, bold: true, color: C.DARK_BLUE }),
                txt(key, { size: 12 }),
              ], { after: 40 })] : []),
              ...(trig !== "n/v" ? [para([
                txt("Auslöser: ", { size: 12, bold: true, color: C.DARK_BLUE }),
                txt(trig, { size: 12 }),
              ], { after: 0 })] : []),
            ]
          });
        })
      })]
    }));
  }

  // ══════════════════════════════════════════════════════
  // 7. RISIKEN & CONVICTION KILLERS
  // ══════════════════════════════════════════════════════
  const risks = DATA.key_risks || [];
  const cks   = DATA.conviction_killers || [];

  children.push(sectionHead("7.  Quantifizierte Risiken & Conviction Killers"));

  const rW = Math.floor(PAGE_W / 2);
  children.push(new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [rW, PAGE_W - rW],
    rows: [new TableRow({
      children: [
        cell([
          para([txt("Quantifizierte Risiken", { size: 15, bold: true, color: C.DARK_BLUE })],
            { after: 60 }),
          ...(risks.length > 0
            ? risks.map(r => new Paragraph({
                numbering: { reference: "bullets", level: 0 },
                spacing:   { before: 30, after: 30 },
                children:  [txt(typeof r === "string" ? r
                  : safeStr(r.risk || r.description || r.point || ""), { size: 15 })],
              }))
            : [para([txt("Keine Risiken dokumentiert.", { size: 15, color: C.GRAY_TXT })], { after: 0 })]),
        ], { width: rW }),
        cell([
          para([txt("🚨  Conviction Killers", { size: 15, bold: true, color: C.RED_TXT })],
            { after: 40 }),
          para([txt("Datenpunkte die den Investment Case sofort entkräften:",
            { size: 12, italic: true, color: C.GRAY_TXT })], { after: 60 }),
          ...(cks.length > 0
            ? cks.map(ck => {
                const d = typeof ck === "string" ? ck
                  : safeStr(ck.description || ck.point || ck);
                const m = typeof ck === "object"
                  ? safeStr(ck.monitoring_indicator || "") : "";
                return new Paragraph({
                  numbering: { reference: "bullets", level: 0 },
                  spacing:   { before: 30, after: 30 },
                  children:  [
                    txt("⚠  " + d, { size: 15, bold: true, color: C.RED_TXT }),
                    ...(m && m !== "n/v"
                      ? [txt(`  → Monitor: ${m}`, { size: 12, italic: true, color: C.GRAY_TXT })]
                      : []),
                  ],
                });
              })
            : [para([txt("Keine Conviction Killers.", { size: 15, color: C.GRAY_TXT })], { after: 0 })]),
        ], { width: PAGE_W - rW }),
      ]
    })]
  }));

  // ══════════════════════════════════════════════════════
  // 8. MAKRO-AMPEL & SENTIMENT
  // ══════════════════════════════════════════════════════
  const macro = DATA.macro_ampel || [];
  if (macro.length > 0) {
    children.push(sectionHead("8.  Makro-Ampel & Sentiment"));

    const mH = ["Beobachtungsbereich", "Signal", "Einschätzung & Transmissionsmechanismus"];
    const mC = [1600, 1200, PAGE_W - 2800];

    children.push(new Table({
      width: { size: PAGE_W, type: WidthType.DXA },
      columnWidths: mC,
      rows: [
        new TableRow({
          tableHeader: true,
          children: mH.map((h, i) => cell(
            [para([txt(h, { size: 13, bold: true, color: C.WHITE })],
              { align: AlignmentType.CENTER, after: 0 })],
            { width: mC[i], bg: C.DARK_BLUE }
          ))
        }),
        ...macro.map((m, ri) => {
          const sig = safeStr(m.signal || m.direction || "NEUTRAL");
          const bg  = ri % 2 === 0 ? C.WHITE : C.LIGHT_GRAY;
          return new TableRow({
            children: [
              cell([para([txt(safeStr(m.category || m.label || m.indicator || ""),
                { size: 13, bold: true })], { after: 0 })], { width: mC[0], bg }),
              cell([para([txt(sig, { size: 13, bold: true, color: signalColor(sig) })],
                { align: AlignmentType.CENTER, after: 0 })], { width: mC[1], bg: signalBg(sig) }),
              cell([para([txt(safeStr(m.key_point || m.text || m.description || ""),
                { size: 13 })], { after: 0 })], { width: mC[2], bg }),
            ]
          });
        })
      ]
    }));
  }

  // ══════════════════════════════════════════════════════
  // 9. FINALE BEGRÜNDUNG
  // ══════════════════════════════════════════════════════
  children.push(sectionHead("9.  Finale Begründung"));
  children.push(new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [PAGE_W],
    rows: [new TableRow({
      children: [cell(
        [para([txt(finalR, { size: 15 })], { after: 0 })],
        { width: PAGE_W, bg: C.BLUE_BG }
      )]
    })]
  }));

  // ══════════════════════════════════════════════════════
  // 10. QUELLEN
  // ══════════════════════════════════════════════════════
  const sources = DATA.sources || [];
  if (sources.length > 0) {
    children.push(sectionHead("10.  Quellen & Literaturverzeichnis"));
    sources.forEach((src, i) => {
      children.push(para(
        [txt(`[${i+1}]  ${safeStr(src)}`, { size: 13, color: C.GRAY_TXT })],
        { before: 20, after: 20 }
      ));
    });
  }

  // DISCLAIMER
  children.push(new Table({
    width: { size: PAGE_W, type: WidthType.DXA },
    columnWidths: [PAGE_W],
    rows: [new TableRow({
      children: [cell(
        [para([txt(
          "DISCLAIMER: Dieses Dokument wurde automatisch durch den KI-Co-Analysten generiert " +
          "(Bachelor Thesis BFH 2025/26, Luca Lüdi) und dient ausschliesslich zu Forschungs- und " +
          "Demonstrationszwecken. Es stellt keine Anlageberatung dar (Art. 3 lit. c FIDLEG). " +
          "Forward-Schätzungen sind Approximationen — kein Ersatz für Bloomberg/FactSet.",
          { size: 12, italic: true, color: C.GRAY_TXT }
        )], { after: 0 })],
        { width: PAGE_W, bg: C.LIGHT_GRAY }
      )]
    })]
  }));

  // ── Dokument zusammenbauen ────────────────────────────────
  return new Document({
    numbering: {
      config: [{
        reference: "bullets",
        levels: [{
          level:     0,
          format:    LevelFormat.BULLET,
          text:      "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 560, hanging: 280 } } }
        }]
      }]
    },
    styles: {
      default: { document: { run: { font: "Arial", size: 18 } } }
    },
    sections: [{
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: {
            top:    MARGIN_TOP,
            bottom: MARGIN_BOTTOM,
            left:   MARGIN_LEFT,
            right:  MARGIN_RIGHT,
            header: 709,
            footer: 709,
            gutter: 0,
          }
        }
      },

      headers: {
        default: new Header({
          children: [new Paragraph({
            spacing: { before: 0, after: 60 },
            border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.GOLD, space: 1 } },
            children: [
              txt(`${company}  (${ticker})`, { size: 13, bold: true, color: C.DARK_BLUE }),
              txt("    KI-Co-Analyst  ·  BFH 2025/26", { size: 12, color: C.GRAY_TXT }),
            ],
          })]
        })
      },

      footers: {
        default: new Footer({
          children: [new Paragraph({
            spacing: { before: 60, after: 0 },
            border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.GOLD, space: 1 } },
            children: [
              txt(`${rating}  |  Kursziel ${ccy} ${pt}  |  Upside ${upside}`,
                { size: 12, bold: true, color: ratingColor(rating) }),
              txt("        Seite ", { size: 12, color: C.GRAY_TXT }),
              new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 12 }),
              txt(" / ", { size: 12, color: C.GRAY_TXT }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 12 }),
            ],
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
  if (process.argv[2] && process.argv[2] !== "-" && fs.existsSync(process.argv[2])) {
    data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  } else {
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