"use client";

import { useState, useCallback } from "react";
import { recColor, upsideClass, upsideLabel, safeNum, scoreColor, convictionStars } from "@/lib/utils";
import TabMemo      from "./TabMemo";
import TabValuation from "./TabValuation";
import TabMacro     from "./TabMacro";
import TabRisk      from "./TabRisk";
import TabQuality   from "./TabQuality";
import { Download, Printer } from "lucide-react";
import { downloadMemoPdf } from "@/lib/api";

const TABS = ["📋 Memo", "📊 Bewertung", "📰 Makro", "⚠️ Risiken", "✅ Qualität"];

function RecBadge({ rec }: { rec: string }) {
  return (
    <span className={`inline-flex px-3 py-1 rounded-full text-xs font-bold border ${recColor(rec)}`}>
      {rec}
    </span>
  );
}

interface KPI { label: string; val: string; cls: string }

export default function MemoViewer({ data, histId }: { data: Record<string, unknown>; histId?: string }) {
  const [tab, setTab] = useState(0);

  // All fields extracted as strings/primitives to avoid unknown-in-JSX TS errors
  const rec        = String(data.final_recommendation ?? "HALTEN");
  const conv       = String(data.conviction_level ?? "-");
  const ccy        = String(data.currency ?? "");
  const company    = String(data.company ?? "");
  const sector     = String(data.sector ?? "");
  const ticker     = String(data.ticker ?? "");
  const date       = String(data.date ?? "");
  const mktcapBn   = data.market_cap_bn as number | undefined;
  const mktcap     = mktcapBn != null ? `${mktcapBn.toFixed(1)} Mrd.` : "n/v";

  const handleDownloadJson = useCallback(() => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `${ticker}_${date}_memo.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [data, ticker, date]);

  const handleDownloadPdf = useCallback(() => {
    if (!histId) return;
    downloadMemoPdf(histId, `${ticker}_${date}_memo.pdf`).catch(console.error);
  }, [histId, ticker, date]);
  const incomplete = Boolean(data.analysis_incomplete);
  const missing    = (data.missing_components as string[] | undefined) ?? [];
  const bottomLine = data.summary_bottom_line ? String(data.summary_bottom_line) : "";
  const execSum    = data.executive_summary   ? String(data.executive_summary)   : "";
  const updn       = data.upside_downside_pct as number | undefined;
  const score      = data.data_consistency_score as number | undefined;
  const pt         = data.price_target;
  const price      = data.current_price;

  const kpis: KPI[] = [
    { label: "Aktueller Kurs",      val: `${ccy} ${safeNum(price)}`, cls: "" },
    { label: "Kursziel (12M)",       val: `${ccy} ${safeNum(pt)}`,   cls: "" },
    { label: "Upside / DW",          val: upsideLabel(updn),         cls: upsideClass(updn) },
    { label: "Marktkapitalisierung", val: mktcap,                    cls: "" },
    { label: "Analyse-Datum",        val: date,                      cls: "" },
  ];

  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">

      {/* ── Header ── */}
      <div className="px-6 py-5 border-b border-slate-100">

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="font-serif text-2xl font-bold text-slate-800">{company}</h2>
              <RecBadge rec={rec} />
            </div>
            <div className="text-sm text-slate-400 mt-1">
              {ticker} · {sector} · {date}
            </div>
            <div className="text-sm text-slate-600 mt-0.5">
              Conviction: <strong>{conv}</strong>{" "}
              <span className="text-amber-500">{convictionStars(conv)}</span>
            </div>
          </div>
          <div className="flex items-start gap-4">
            <div className="flex gap-2">
              <button
                onClick={handleDownloadJson}
                title="Als JSON herunterladen"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200
                           text-xs font-medium text-slate-600 hover:bg-slate-50 hover:border-slate-300
                           transition-colors"
              >
                <Download size={13} /> JSON
              </button>
              {histId && (
                <button
                  onClick={handleDownloadPdf}
                  title="Investment Memo als PDF herunterladen"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border
                             text-xs font-medium transition-colors"
                  style={{ borderColor: "#c9a84c", color: "#8a6820", background: "rgba(201,168,76,0.08)" }}
                >
                  <Printer size={13} /> PDF
                </button>
              )}
            </div>
            <div className="text-right">
              <div className="text-xs text-slate-400 mb-1 tracking-widest uppercase">Konsistenz</div>
              <div className={`font-serif text-4xl font-bold leading-none ${scoreColor(score)}`}>
                {score ?? "-"}
                <span className="text-base font-normal text-slate-400">/10</span>
              </div>
            </div>
          </div>
        </div>

        {/* Unvollständige Analyse */}
        {incomplete && (
          <div className="mt-3 flex items-center gap-2 px-4 py-2.5 rounded-lg border border-red-200
                          bg-red-50 text-sm text-red-700 font-medium">
            ⚠️ Analyse unvollständig — fehlende Komponenten: {missing.join(", ") || "unbekannt"}.
            Empfehlung hat reduzierte Aussagekraft (Conviction begrenzt).
          </div>
        )}

        {/* KPI row */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-5">
          {kpis.map(({ label, val, cls }) => (
            <div key={label} className="bg-slate-50 rounded-lg px-3 py-2.5">
              <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">{label}</div>
              <div className={`font-semibold text-sm text-slate-800 ${cls}`}>{val}</div>
            </div>
          ))}
        </div>

        {/* Executive summary */}
        {(bottomLine || execSum) && (
          <div className="mt-4 p-4 rounded-lg border-l-4 bg-blue-50 border-blue-200">
            {bottomLine && (
              <div className="font-semibold text-sm text-blue-800 mb-1">💡 {bottomLine}</div>
            )}
            {execSum && (
              <div className="text-sm text-slate-600 leading-relaxed">{execSum}</div>
            )}
          </div>
        )}
      </div>

      {/* ── Tabs ── */}
      <div className="flex border-b border-slate-100 overflow-x-auto">
        {TABS.map((t, i) => (
          <button
            key={t}
            onClick={() => setTab(i)}
            className={`px-5 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${
              tab === i
                ? "border-[#c9a84c] text-slate-800"
                : "border-transparent text-slate-400 hover:text-slate-600"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Tab content ── */}
      <div className="p-6">
        {tab === 0 && <TabMemo      data={data} />}
        {tab === 1 && <TabValuation data={data} />}
        {tab === 2 && <TabMacro     data={data} />}
        {tab === 3 && <TabRisk      data={data} />}
        {tab === 4 && <TabQuality   data={data} />}
      </div>
    </div>
  );
}
