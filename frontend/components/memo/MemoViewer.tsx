"use client";

import { useState } from "react";
import { downloadMemoPdf } from "@/lib/api";
import { safeNum, upsideClass, upsideLabel, recLabel, convictionBars, capitalize } from "@/lib/utils";
import { type Memo, asObj, asList, str, num, textOf } from "./ui";
import TabOverview  from "./TabOverview";
import TabMemo      from "./TabMemo";
import TabValuation from "./TabValuation";
import TabRisk      from "./TabRisk";
import TabMacro     from "./TabMacro";
import TabQuality   from "./TabQuality";

const TABS = ["Übersicht", "Memo", "Bewertung", "Risiken", "Makro & News", "Qualität"];

const BMT_LABEL: Record<string, string> = {
  mature_cashflow: "Reifer Cashflow",
  growth_with_revenue: "Wachstum",
  optionality_play: "Optionality",
  cyclical: "Zyklisch",
  financial_institution: "Finanzinstitut",
};

/** "Muster Robotics AG" → ["Muster Robotics ", "AG"] (Rechtsform kursiv/gold wie im Entwurf). */
function splitCompany(name: string): [string, string] {
  const m = name.match(/^(.*\s)(AG|SA|Ltd\.?|Inc\.?|plc|N\.V\.|SE|Corp\.?|Holding|Group|GmbH)$/i);
  return m ? [m[1], m[2]] : [name, ""];
}

export default function MemoViewer({ data, histId }: { data: Memo; histId?: string }) {
  const [tab, setTab] = useState(0);

  const ticker  = str(data.ticker);
  const date    = str(data.date);
  const company = str(data.company, ticker);
  const ccy     = str(data.currency);
  const rec     = str(data.final_recommendation, "–");
  const conv    = str(data.conviction_level, "–");
  const bars    = convictionBars(conv);
  const score   = num(data.data_consistency_score);
  const dur     = num(data.analysis_duration_s);
  const updn    = num(data.upside_downside_pct);
  const mcap    = num(data.market_cap_bn);
  const agg     = asObj(data.aggregation);
  const aggScore = num(agg?.score);
  const bmc     = asObj(data.business_model_classification);
  const bmt     = str(bmc?.business_model_type);
  const incomplete = Boolean(data.analysis_incomplete);
  const missing = asList<unknown>(data.missing_components).map(textOf).filter(Boolean);
  const [head, suffix] = splitCompany(company);

  const onPdf = () => {
    if (histId) downloadMemoPdf(histId, `${ticker}_${date}_memo.pdf`).catch(console.error);
  };

  const onJson = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${ticker}_${date}_memo.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const kpis = [
    { label: "KURS", val: `${ccy} ${safeNum(data.current_price)}`, cls: "" },
    { label: "KURSZIEL 12M", val: `${ccy} ${safeNum(data.price_target)}`, cls: "" },
    { label: "UPSIDE", val: upsideLabel(updn), cls: upsideClass(updn) },
    { label: "MARKTKAP.", val: mcap != null ? `${mcap.toFixed(1)} Mrd` : "–", cls: "" },
    { label: "AGGREGATIONS-SCORE", val: aggScore != null ? `${aggScore > 0 ? "+" : ""}${aggScore.toFixed(1)}` : "–", cls: "" },
  ];

  return (
    <div className="flex flex-col">
      {/* ── Kopf ──────────────────────────────────────────────────────────── */}
      <section className="dot-grid border-b border-line px-5 md:px-14 pt-11 pb-9 flex flex-wrap justify-between items-end gap-10">
        <div className="flex flex-col gap-3 min-w-0">
          <div className="eyebrow">ANALYSE · {ticker} · {date}</div>
          <h1 className="m-0 font-display font-normal text-5xl md:text-[72px] leading-none tracking-[-0.02em] break-words">
            {head}{suffix && <em className="text-gold-dark">{suffix}</em>}
          </h1>
          <div className="text-[15px] text-muted">
            {[str(data.sector), bmt && `Klassifikation: ${BMT_LABEL[bmt] ?? bmt}`].filter(Boolean).join(" · ")}
          </div>
        </div>

        <div className="flex flex-wrap bg-card border border-line shadow-[0_30px_60px_-40px_rgba(60,45,10,0.35)]">
          <div className="px-7 py-5 flex flex-col gap-1.5 bg-ink text-cream">
            <div className="font-mono text-[11px] tracking-[0.12em] text-gold-dim">EMPFEHLUNG</div>
            <div className="font-display text-[40px] leading-none">{recLabel(rec)}</div>
          </div>
          <div className="px-7 py-5 flex flex-col gap-2.5 border-r border-line">
            <div className="label-mono">CONVICTION</div>
            <div className="flex items-center gap-3">
              <div className="font-display text-[30px] leading-none">{capitalize(conv)}</div>
              <div className="flex gap-1" role="img" aria-label={`Conviction ${bars} von 3`}>
                {[0, 1, 2].map(i => (
                  <span key={i} className="w-[18px] h-1.5" style={{ background: i < bars ? "#B08D3C" : "#E4DCC8" }} />
                ))}
              </div>
            </div>
          </div>
          <div className="px-7 py-5 flex flex-col gap-2.5 border-r border-line">
            <div className="label-mono">DATENKONSISTENZ</div>
            <div className="font-mono text-[26px] leading-none">
              {score ?? "–"}<span className="text-sm text-muted"> / 10</span>
            </div>
          </div>
          <div className="px-7 py-5 flex flex-col gap-2.5">
            <div className="label-mono">LAUFZEIT</div>
            <div className="font-mono text-[26px] leading-none">{dur != null ? `${Math.round(dur)} s` : "–"}</div>
          </div>
        </div>
      </section>

      {incomplete && (
        <div className="mx-5 md:mx-14 mt-6 px-5 py-3 border border-negative/40 bg-[#FBEFEF] text-sm text-negative">
          Analyse unvollständig — fehlende Komponenten: {missing.join(", ") || "unbekannt"}.
          Die Conviction ist deshalb auf «niedrig» begrenzt.
        </div>
      )}

      {/* ── Kennzahlen-Leiste ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-5 border-b border-line bg-card px-5 md:px-14">
        {kpis.map((k, i) => (
          <div key={k.label} className={`py-5 flex flex-col gap-1.5 ${i > 0 ? "md:pl-7 md:border-l md:border-line" : ""}`}>
            <div className="label-mono">{k.label}</div>
            <div className={`font-mono text-xl ${k.cls}`}>{k.val}</div>
          </div>
        ))}
      </div>

      {/* ── Tabs ──────────────────────────────────────────────────────────── */}
      <div role="tablist" aria-label="Memo-Bereiche" className="flex gap-8 px-5 md:px-14 border-b border-line overflow-x-auto">
        {TABS.map((t, i) => (
          <button key={t} type="button" role="tab" aria-selected={tab === i} onClick={() => setTab(i)}
            className={`h-14 whitespace-nowrap text-[15px] border-b-2 ${
              tab === i ? "border-gold text-ink font-semibold" : "border-transparent text-muted hover:text-ink"
            }`}>
            {t}
          </button>
        ))}
        <button type="button" onClick={onJson}
          className="ml-auto h-14 whitespace-nowrap font-mono text-[11px] tracking-[0.1em] text-muted hover:text-ink">
          JSON ↓
        </button>
      </div>

      <div className="px-5 md:px-14 pt-10 pb-12" role="tabpanel">
        {tab === 0 && <TabOverview d={data} histId={histId} onPdf={onPdf} />}
        {tab === 1 && <TabMemo d={data} />}
        {tab === 2 && <TabValuation d={data} />}
        {tab === 3 && <TabRisk d={data} />}
        {tab === 4 && <TabMacro d={data} />}
        {tab === 5 && <TabQuality d={data} />}
      </div>
    </div>
  );
}
