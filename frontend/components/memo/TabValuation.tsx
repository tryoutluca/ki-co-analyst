"use client";

import { safeNum } from "@/lib/utils";
import { type Memo, asList, asObj, str, SectionTitle, Panel, Empty } from "./ui";

const ASSESSMENT: Record<string, { label: string; cls: string }> = {
  DISCOUNT: { label: "Abschlag",  cls: "text-positive" },
  FAIR:     { label: "Fair",      cls: "text-gold-text" },
  ELEVATED: { label: "Erhöht",    cls: "text-negative" },
};

const TH = "px-4 py-3 text-left font-mono text-[11px] tracking-[0.1em] font-normal text-muted border-b border-ink whitespace-nowrap";
const TD = "px-4 py-3 text-sm text-ink-2 border-b border-line-2 whitespace-nowrap";

function cell(v: unknown): string {
  if (v == null || v === "") return "–";
  const f = typeof v === "number" ? v : NaN;
  return Number.isFinite(f) ? (Math.abs(f) >= 100 ? f.toFixed(0) : f.toFixed(2)) : String(v);
}

export default function TabValuation({ d }: { d: Memo }) {
  const vt    = asList(d.valuation_table);
  const ff    = asList(d.full_financials);
  const pc    = asObj(d.peer_comparison);
  const peers = asList(pc?.peers);
  const subj  = asObj(pc?.subject_company);
  const avg   = asObj(pc?.sector_averages);
  const ticker = str(d.ticker);
  const incomplete = Boolean(d.analysis_incomplete);

  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col gap-4">
        <SectionTitle aside="AKTUELL · PEERS · HISTORISCH">Bewertungs-Multiples</SectionTitle>
        {vt.length ? (
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead><tr>{["Kennzahl", "Aktuell", "Peer Ø", "Hist. Ø", "Einschätzung", "Quelle"].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
              <tbody>
                {vt.map((r, i) => {
                  const a = ASSESSMENT[str(r.assessment)] ?? { label: str(r.assessment, "–"), cls: "" };
                  return (
                    <tr key={i}>
                      <td className={`${TD} font-medium text-ink`}>{str(r.metric)}</td>
                      <td className={`${TD} font-mono`}>{safeNum(r.current_value)}</td>
                      <td className={`${TD} font-mono`}>{safeNum(r.peer_average)}</td>
                      <td className={`${TD} font-mono`}>{safeNum(r.historical_average)}</td>
                      <td className={`${TD} ${a.cls}`}>{a.label}</td>
                      <td className={`${TD} text-xs text-muted`}>{str(r.source)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        ) : <Empty>{incomplete ? "Fundamentaldaten nicht verfügbar — Analyse unvollständig." : "Keine Multiples vorhanden."}</Empty>}
      </section>

      <section className="flex flex-col gap-4">
        <SectionTitle aside="A = IST · E = SCHÄTZUNG (FORWARD-ESTIMATE-AGENT)">Finanzübersicht</SectionTitle>
        {ff.length ? (
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead><tr>{["Jahr", "Umsatz", "EBITDA", "EBITDA-%", "EBIT-%", "EPS", "KGV", "DPS", "FCF", "ND/EBITDA", "ROIC %", "Quelle"].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
              <tbody>
                {ff.map((y, i) => {
                  const est = y.type === "E";
                  return (
                    <tr key={i} className={est ? "bg-[#FBF6EA]" : ""}>
                      <td className={`${TD} font-mono ${est ? "text-gold-text" : "text-ink"}`}>{str(y.year)}</td>
                      {["revenue_bn", "ebitda_bn", "ebitda_margin_pct", "ebit_margin_pct", "eps_adj", "pe_ratio", "dps", "fcf_bn", "nd_ebitda", "roic_pct"].map(k => (
                        <td key={k} className={`${TD} font-mono`}>{cell(y[k])}</td>
                      ))}
                      <td className={`${TD} text-xs text-muted`}>{str(y.source)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        ) : <Empty>{incomplete ? "Fundamentaldaten nicht verfügbar — Analyse unvollständig." : "Keine Finanzübersicht vorhanden."}</Empty>}
      </section>

      {(peers.length > 0 || subj || avg) && (
        <section className="flex flex-col gap-4">
          <SectionTitle aside={str(pc?.sector).toUpperCase()}>Peer-Vergleich</SectionTitle>
          <Panel className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead><tr>{["Unternehmen", "Land", "EV/EBITDA", "Fwd P/E", "EBIT-%", "ND/EBITDA", "Div %", "Umsatzwachstum %"].map(h => <th key={h} className={TH}>{h}</th>)}</tr></thead>
              <tbody>
                {[...peers, avg, subj].filter((p): p is Record<string, unknown> => Boolean(p)).map((p, i) => {
                  const isSubj = p.ticker === ticker || p === subj;
                  const isAvg  = p.ticker === "AVG" || p === avg;
                  return (
                    <tr key={i} className={isSubj ? "bg-[#FBF6EA]" : isAvg ? "bg-paper" : ""}>
                      <td className={`${TD} ${isSubj ? "font-semibold text-ink" : ""} ${isAvg ? "italic" : ""}`}>
                        {isAvg ? "Ø Peers" : str(p.company)}
                      </td>
                      <td className={TD}>{str(p.country, "–")}</td>
                      {["ev_ebitda", "forward_pe", "ebit_margin_pct", "nd_ebitda", "dividend_yield_pct", "revenue_growth_pct"].map(k => (
                        <td key={k} className={`${TD} font-mono`}>{cell(p[k])}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
          {str(pc?.methodology) && <p className="m-0 text-xs text-muted">{str(pc?.methodology)}</p>}
        </section>
      )}
    </div>
  );
}
