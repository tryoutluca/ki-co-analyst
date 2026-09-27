"use client";

import { safeNum } from "@/lib/utils";
import { type Memo, asList, asObj, str, textOf, SectionTitle, Panel, Empty } from "./ui";

const HORIZON: Record<string, string> = {
  kurzfristig: "KURZFRISTIG", mittelfristig: "MITTELFRISTIG", strukturell: "STRUKTURELL", langfristig: "LANGFRISTIG",
};

const SCENARIO_LABEL: Record<string, string> = { "Bear Case": "Bear", "Base Case": "Base", "Bull Case": "Bull" };

export default function TabRisk({ d }: { d: Memo }) {
  const scenarios = asList(d.scenarios);
  // Schema: list[str] — das LLM liefert aber oft {description, affected_segment, time_horizon, quantification}
  const risks     = asList<unknown>(d.key_risks);
  const killers   = asList(d.conviction_killers);
  const opt       = asObj(d.optionality_analysis);
  const ccy       = str(d.currency);

  return (
    <div className="flex flex-col gap-12">
      <section className="flex flex-col gap-4">
        <SectionTitle aside="WAHRSCHEINLICHKEITEN SUMMIEREN AUF 100 %">Szenarien</SectionTitle>
        {scenarios.length ? (
          <div className="grid grid-cols-1 md:grid-cols-3 border-t border-ink">
            {scenarios.map((s, i) => {
              const name = str(s.name);
              const base = name === "Base Case";
              return (
                <div key={i} className={`pt-7 pb-2 flex flex-col gap-3 ${i > 0 ? "md:pl-8 md:border-l md:border-line" : ""} ${i < 2 ? "md:pr-8" : ""}`}>
                  <div className="flex justify-between items-baseline">
                    <span className={`font-display text-[32px] ${base ? "text-gold-dark" : ""}`}>
                      {SCENARIO_LABEL[name] ?? name} <em className="text-muted text-2xl">Case</em>
                    </span>
                    <span className="font-mono text-[13px] text-gold-dark">{str(s.probability_pct, "?")} %</span>
                  </div>
                  <div className="font-mono text-2xl">{ccy} {safeNum(s.price_target)}</div>
                  <p className="m-0 text-[15px] leading-relaxed text-ink-2">{str(s.key_assumption)}</p>
                  {str(s.trigger) && <p className="m-0 text-sm text-muted"><span className="label-mono">Trigger</span> · {str(s.trigger)}</p>}
                </div>
              );
            })}
          </div>
        ) : <Empty>Keine Szenarien vorhanden.</Empty>}
      </section>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-10">
        <section className="flex flex-col gap-4">
          <SectionTitle>Quantifizierte Risiken</SectionTitle>
          {risks.length ? (
            <ol className="m-0 p-0 list-none border-t border-ink">
              {risks.map((r, i) => {
                const o = asObj(r);
                const meta = o ? [
                  str(o.affected_segment),
                  HORIZON[str(o.time_horizon).toLowerCase()] ?? str(o.time_horizon).toUpperCase(),
                ].filter(Boolean) : [];
                const quant = o ? str(o.quantification) : "";
                return (
                  <li key={i} className="grid grid-cols-[48px_minmax(0,1fr)] gap-4 py-4 border-b border-line-2">
                    <span className="font-mono text-[13px] text-gold-dark">{String(i + 1).padStart(2, "0")}</span>
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[15px] leading-relaxed text-ink-2">{textOf(r)}</span>
                      {quant && <span className="text-sm text-muted">{quant}</span>}
                      {meta.length > 0 && (
                        <span className="font-mono text-[10px] tracking-[0.08em] text-muted-2">{meta.join(" · ")}</span>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : <Empty>Keine Risiken angegeben.</Empty>}
        </section>

        <section className="flex flex-col gap-4">
          <SectionTitle aside="SOFORTIGE INVALIDIERUNG">Conviction Killers</SectionTitle>
          {killers.length ? (
            <div className="flex flex-col gap-3">
              {killers.map((k, i) => (
                <div key={i} className="bg-ink text-cream-2 p-5 flex flex-col gap-2">
                  <div className="font-display text-xl leading-snug">{textOf(k)}</div>
                  {str(k.monitoring_indicator) && (
                    <div className="text-sm text-dark-muted"><span className="font-mono text-[11px] tracking-[0.1em] text-gold-dim">MONITOR</span> · {str(k.monitoring_indicator)}</div>
                  )}
                </div>
              ))}
            </div>
          ) : <Empty>Keine Conviction Killers identifiziert.</Empty>}
        </section>
      </div>

      {opt && (
        <section className="flex flex-col gap-4">
          <SectionTitle aside="REAL OPTIONS · NUR BEI PRE-REVENUE">Optionality-Bewertung</SectionTitle>
          <Panel className="grid grid-cols-1 md:grid-cols-3">
            {[
              { label: "CASH-RUNWAY", val: `${str(opt.runway_months, "–")} Mt.` },
              { label: "WAHRSCHEINLICHKEITSGEWICHTETER WERT", val: `${ccy} ${safeNum(opt.probability_weighted_value)}` },
              { label: "VERWÄSSERUNGSRISIKO", val: str(opt.dilution_risk, "–") },
            ].map((k, i) => (
              <div key={k.label} className={`p-6 flex flex-col gap-2 ${i > 0 ? "md:border-l md:border-line" : ""}`}>
                <div className="label-mono">{k.label}</div>
                <div className="font-display text-3xl">{k.val}</div>
              </div>
            ))}
          </Panel>
          {str(opt.binary_risk_warning) && <p className="m-0 text-sm text-negative">{str(opt.binary_risk_warning)}</p>}
        </section>
      )}
    </div>
  );
}
