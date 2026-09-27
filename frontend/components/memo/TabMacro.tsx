"use client";

import { type Memo, asList, asObj, str, num, textOf, SectionTitle, Panel, Empty, signalTone } from "./ui";

const COMPONENT_LABEL: Record<string, string> = {
  milestones: "Meilensteine", industry: "Industrie", macro: "Makro", news: "Firmen-News",
};

/** Deterministischer Sentiment-Breakdown (tools/sentiment_engine.py). */
function SentimentBreakdown({ d }: { d: Memo }) {
  const ns = asObj(d.news_sentiment);
  const bd = asObj(ns?.breakdown);
  if (!ns || !bd) return null;
  const comps = asObj(bd.components) ?? {};
  const weights = asObj(bd.effective_weights) ?? {};
  const research = asList(ns.research_log);
  const warnings = asList<unknown>(bd.warnings).map(textOf).filter(Boolean);

  return (
    <section className="flex flex-col gap-4">
      <SectionTitle aside={`LLM-URTEIL ZUM VERGLEICH: ${str(ns.llm_score, "–")} / 10`}>
        Sentiment <em className="text-gold-dark">{str(ns.score, "–")} / 10</em>
      </SectionTitle>
      <Panel className="p-6 flex flex-col gap-4">
        {Object.keys(COMPONENT_LABEL).map(k => {
          const v = num(comps[k]);
          const w = num(weights[k]);
          const pct = v != null ? Math.round(Math.abs(v) * 50) : 0;   // −1…+1 → Balken ab Mitte
          return (
            <div key={k} className="grid grid-cols-[120px_minmax(0,1fr)_110px] gap-4 items-center">
              <span className="text-sm text-ink-2">{COMPONENT_LABEL[k]}</span>
              <div className="relative h-[5px] bg-bar" role="img"
                aria-label={v != null ? `${COMPONENT_LABEL[k]}: ${v.toFixed(2)}` : `${COMPONENT_LABEL[k]}: keine Daten`}>
                <div className="absolute top-[-3px] bottom-[-3px] left-1/2 w-px bg-line-3" />
                {v != null && (
                  <div className="absolute h-[5px]"
                    style={{ background: v >= 0 ? "#1E6B45" : "#9B2C2C", width: `${pct}%`, left: v >= 0 ? "50%" : `${50 - pct}%` }} />
                )}
              </div>
              <span className="font-mono text-xs text-muted text-right">
                {v != null ? `${v > 0 ? "+" : ""}${v.toFixed(2)}` : "–"} · {w != null ? `${Math.round(w * 100)} %` : "–"}
              </span>
            </div>
          );
        })}
        <p className="m-0 text-xs text-muted">Skala −1 bis +1 je Komponente · rechts: Wert und effektives Gewicht. Score deterministisch aus den Einzelurteilen berechnet.</p>
        {warnings.length > 0 && (
          <ul className="m-0 pl-4 text-xs text-gold-text">{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        )}
      </Panel>
      {research.length > 0 && (
        <Panel className="p-6 flex flex-col gap-2">
          <div className="label-mono">AUTONOME NACHRECHERCHE</div>
          {research.map((r, i) => (
            <div key={i} className="text-sm text-ink-2 border-t border-line-2 pt-2 first:border-t-0 first:pt-0">
              {str(r.query) ? <><span className="font-mono text-xs text-gold-text">SUCHE</span> «{str(r.query)}» — {str(r.reason)} ({str(r.results, "0")} Treffer)</>
                : str(r.guardrail) ? <><span className="font-mono text-xs text-negative">LEITPLANKE</span> {str(r.guardrail)}</>
                : <><span className="font-mono text-xs text-muted">ENTSCHEID</span> {str(r.decision)}</>}
            </div>
          ))}
        </Panel>
      )}
    </section>
  );
}

export default function TabMacro({ d }: { d: Memo }) {
  const ampel     = asList(d.macro_ampel);
  const checklist = asList<unknown>(d.monitoring_checklist).map(textOf).filter(Boolean);

  return (
    <div className="flex flex-col gap-12">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-10">
        <section className="flex flex-col gap-4">
          <SectionTitle>Makro-Ampel</SectionTitle>
          {ampel.length ? (
            <div className="border-t border-ink">
              {ampel.map((a, i) => {
                const tone = signalTone(str(a.signal));
                return (
                  <div key={i} className="grid grid-cols-[18px_140px_minmax(0,1fr)] gap-3 py-4 border-b border-line-2 items-baseline">
                    <span className="w-[9px] h-[9px] rotate-45 inline-block translate-y-[-1px]" style={{ background: tone.dot }} aria-hidden="true" />
                    <div className="flex flex-col">
                      <span className="font-display text-xl">{str(a.category)}</span>
                      <span className={`font-mono text-[10px] tracking-[0.08em] ${tone.text}`}>{str(a.signal).toUpperCase()}</span>
                    </div>
                    <span className="text-[15px] leading-relaxed text-ink-2">{str(a.key_point)}</span>
                  </div>
                );
              })}
            </div>
          ) : <Empty>Keine Makro-Daten verfügbar.</Empty>}
        </section>

        <section className="flex flex-col gap-4">
          <SectionTitle>Monitoring-Checkliste</SectionTitle>
          {checklist.length ? (
            <ul className="m-0 p-0 list-none border-t border-ink">
              {checklist.map((c, i) => (
                <li key={i} className="grid grid-cols-[18px_minmax(0,1fr)] gap-3 py-3.5 border-b border-line-2 text-[15px] leading-relaxed text-ink-2">
                  <span className="w-[9px] h-[9px] mt-2 rotate-45 inline-block border-[1.5px] border-gold" aria-hidden="true" />
                  {c}
                </li>
              ))}
            </ul>
          ) : <Empty>Keine Checkliste verfügbar.</Empty>}
        </section>
      </div>

      <SentimentBreakdown d={d} />
    </div>
  );
}
