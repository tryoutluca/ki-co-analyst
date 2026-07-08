"use client";

import { safeNum } from "@/lib/utils";

function assessmentBadge(a: string) {
  const badges: Record<string, string> = {
    ELEVATED: "bg-red-100 text-red-700 border-red-200",
    FAIR:     "bg-emerald-100 text-emerald-700 border-emerald-200",
    DISCOUNT: "bg-blue-100 text-blue-700 border-blue-200",
  };
  const icons: Record<string, string> = { ELEVATED: "🔴", FAIR: "🟢", DISCOUNT: "🔵" };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold border ${badges[a] ?? "bg-slate-100 text-slate-600"}`}>
      {icons[a] ?? ""} {a}
    </span>
  );
}

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                   border-b border-slate-100 pb-2">{children}</h3>
  );
}

function MissingDataHint() {
  return (
    <div className="flex items-center gap-2 px-4 py-3 rounded-lg border border-amber-200
                    bg-amber-50 text-sm text-amber-700">
      ⚠️ Fundamentaldaten nicht verfügbar — Analyse unvollständig
    </div>
  );
}

export default function TabValuation({ data }: { data: Record<string, unknown> }) {
  const vt    = (data.valuation_table    as Record<string, unknown>[]) ?? [];
  const ce    = (data.consensus_estimates as Record<string, unknown>[]) ?? [];
  const ff    = (data.full_financials     as Record<string, unknown>[]) ?? [];
  const pc    = (data.peer_comparison     as Record<string, unknown>)   ?? {};
  const peers = (pc.peers                 as Record<string, unknown>[]) ?? [];
  const subj  = pc.subject_company        as Record<string, unknown> | undefined;
  const avg   = pc.sector_averages        as Record<string, unknown> | undefined;
  const tkr   = String(data.ticker ?? "");
  const incomplete = Boolean(data.analysis_incomplete);

  const th = "px-3 py-2 text-left text-xs font-semibold tracking-wide uppercase text-slate-400 bg-slate-50";
  const td = "px-3 py-2 text-sm text-slate-700 border-b border-slate-50";

  return (
    <div className="space-y-8">

      {/* Multiples Table */}
      <div>
        <SectionHead>Bewertungs-Multiples</SectionHead>
        {vt.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Kennzahl","Aktuell","Peer Ø","Hist. Ø","Einschätzung","Quelle"].map(h =>
                    <th key={h} className={th}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {vt.map((r, i) => (
                  <tr key={i} className="hover:bg-slate-50">
                    <td className={`${td} font-medium`}>{String(r.metric ?? "")}</td>
                    <td className={`${td} font-semibold`}>{safeNum(r.current_value)}</td>
                    <td className={td}>{safeNum(r.peer_average)}</td>
                    <td className={td}>{safeNum(r.historical_average)}</td>
                    <td className={td}>{assessmentBadge(String(r.assessment ?? "FAIR"))}</td>
                    <td className={`${td} text-slate-400 text-xs`}>{String(r.source ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : incomplete ? <MissingDataHint /> : null}
      </div>

      {/* Consensus Estimates */}
      <div>
        <SectionHead>Konsensschätzungen</SectionHead>
        {ce.length > 0 ? (
          <>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    {["Jahr","Umsatz (Mrd.)","EBITDA-%","EPS","KGV"].map(h =>
                      <th key={h} className={th}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {ce.map((r, i) => {
                    const isEst = r.type === "E";
                    return (
                      <tr key={i} className={isEst ? "bg-blue-50/50" : "hover:bg-slate-50"}>
                        <td className={`${td} font-medium`}>
                          {isEst && <span className="text-blue-500 mr-1">📊</span>}
                          {String(r.year ?? "")}
                        </td>
                        <td className={td}>{safeNum(r.revenue_bn)}</td>
                        <td className={td}>{safeNum(r.ebitda_margin_pct)}%</td>
                        <td className={td}>{safeNum(r.eps)}</td>
                        <td className={td}>{safeNum(r.pe_ratio)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-400 mt-1">📊 = Schätzung</p>
          </>
        ) : incomplete ? <MissingDataHint /> : null}
      </div>

      {/* Full Financials */}
      {ff.length > 0 && (
        <div>
          <SectionHead>Vollständige Finanzübersicht</SectionHead>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Jahr","Umsatz","EBITDA","EBITDA-%","EBIT-%","EPS","DPS","FCF","ND/EBITDA","ROIC","Quelle"].map(h =>
                    <th key={h} className={th}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {ff.map((y, i) => {
                  const isEst = y.type === "E";
                  return (
                    <tr key={i} className={isEst ? "bg-blue-50/50" : "hover:bg-slate-50"}>
                      <td className={`${td} font-medium`}>
                        {isEst && <span className="text-blue-500 mr-1">📊</span>}
                        {String(y.year ?? "")}
                      </td>
                      {["revenue_bn","ebitda_bn","ebitda_margin_pct","ebit_margin_pct",
                        "eps_adj","dps","fcf_bn","nd_ebitda","roic_pct"].map(k =>
                        <td key={k} className={td}>{String(y[k] ?? "n/v")}</td>
                      )}
                      <td className={`${td} text-xs text-slate-400`}>{String(y.source ?? "")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Peer Comparison */}
      {(peers.length > 0 || subj || avg) && (
        <div>
          <SectionHead>Peer-Vergleich</SectionHead>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Unternehmen","Land","EV/EBITDA","Fwd P/E","EBIT-%","ND/EBITDA","Div %","Rev-Wachstum"].map(h =>
                    <th key={h} className={th}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {[...peers, avg, subj].filter(Boolean).map((p, i) => {
                  const pr = p as Record<string, unknown>;
                  const isSub = pr.ticker === tkr;
                  const isAvg = pr.ticker === "AVG";
                  return (
                    <tr key={i}
                        className={isSub ? "bg-amber-50 font-semibold" : isAvg ? "bg-slate-50 italic" : "hover:bg-slate-50"}>
                      <td className={`${td} font-medium`}>
                        {isSub ? "⭐ " : isAvg ? "Ø " : ""}
                        {String(pr.company ?? "")}
                      </td>
                      <td className={td}>{String(pr.country ?? "")}</td>
                      <td className={td}>{String(pr.ev_ebitda ?? "-")}</td>
                      <td className={td}>{String(pr.forward_pe ?? "-")}</td>
                      <td className={td}>{String(pr.ebit_margin_pct ?? "-")}</td>
                      <td className={td}>{String(pr.nd_ebitda ?? "-")}</td>
                      <td className={td}>{String(pr.dividend_yield_pct ?? "-")}</td>
                      <td className={td}>{String(pr.revenue_growth_pct ?? "-")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
