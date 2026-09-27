"use client";

import { recLabel } from "@/lib/utils";
import { type Memo, asList, asObj, str, num, SectionTitle, Panel, Empty } from "./ui";

const RESULT: Record<string, { label: string; cls: string; dot: string }> = {
  bestanden:      { label: "BESTANDEN",      cls: "text-positive",  dot: "#1E6B45" },
  Warnung:        { label: "WARNUNG",        cls: "text-gold-text", dot: "#B08D3C" },
  fehlgeschlagen: { label: "FEHLGESCHLAGEN", cls: "text-negative",  dot: "#9B2C2C" },
};

const WEIGHT_LABEL: Record<string, string> = {
  fundamental: "Fundamental", news: "News / Sentiment", risk: "Risk", thematic: "Thematic",
};

/** Deterministischer Aggregations-Score (graph/supervisor.py). */
function Aggregation({ d }: { d: Memo }) {
  const agg = asObj(d.aggregation);
  const score = num(agg?.score);
  if (!agg || score == null) return null;
  const weights = asObj(agg.weights) ?? {};
  const comps = asObj(agg.components) ?? {};
  const llmRec = str(agg.llm_recommendation);
  const rec = str(agg.recommendation);

  return (
    <section className="flex flex-col gap-4">
      <SectionTitle aside="SCHWELLEN: > 12 KAUFEN · 4–12 ÜBERGEWICHTEN · −4–4 HALTEN · −12–−4 UNTERGEWICHTEN">
        Aggregation <em className="text-gold-dark">{score > 0 ? "+" : ""}{score.toFixed(1)}</em>
      </SectionTitle>
      <Panel className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>{["Komponente", "Wert", "Gewicht", "Beitrag"].map(h => (
              <th key={h} className="px-5 py-3 text-left font-mono text-[11px] tracking-[0.1em] font-normal text-muted border-b border-ink">{h}</th>
            ))}</tr>
          </thead>
          <tbody>
            {Object.keys(weights).map(k => {
              const w = num(weights[k]) ?? 0;
              const c = num(comps[k]) ?? 0;
              return (
                <tr key={k}>
                  <td className="px-5 py-3 text-sm border-b border-line-2">{WEIGHT_LABEL[k] ?? k}</td>
                  <td className="px-5 py-3 text-sm font-mono border-b border-line-2">{c > 0 ? "+" : ""}{c.toFixed(1)}</td>
                  <td className="px-5 py-3 text-sm font-mono border-b border-line-2">{Math.round(w * 100)} %</td>
                  <td className="px-5 py-3 text-sm font-mono border-b border-line-2">{c * w > 0 ? "+" : ""}{(c * w).toFixed(2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
      <p className="m-0 text-sm text-muted">
        Gewichte = Classifier-Basis × Agent-Konfidenz{agg.sentiment_override_applied ? " · Sentiment-Override aktiv" : ""}
        {agg.dcf_cap_applied ? " · DCF-Cap aktiv" : ""}. Empfehlung: <strong className="text-ink">{recLabel(rec)}</strong>
        {llmRec && llmRec !== rec ? <> (LLM-Vorschlag war {recLabel(llmRec)} — überstimmt)</> : null}.
      </p>
    </section>
  );
}

export default function TabQuality({ d }: { d: Memo }) {
  const checks = asList(d.quality_checks);
  const score  = num(d.data_consistency_score);
  const notes  = str(d.consistency_notes);
  const count = (r: string) => checks.filter(c => c.result === r).length;

  return (
    <div className="flex flex-col gap-12">
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-10">
        <section className="flex flex-col gap-4 min-w-0">
          <SectionTitle>Qualitätschecks</SectionTitle>
          {checks.length ? (
            <div className="border-t border-ink">
              {checks.map((c, i) => {
                const r = RESULT[str(c.result)] ?? { label: str(c.result).toUpperCase(), cls: "text-muted", dot: "#8B8E93" };
                return (
                  <div key={i} className="grid grid-cols-[18px_minmax(0,1fr)_auto] gap-3 py-4 border-b border-line-2 items-baseline">
                    <span className="w-[9px] h-[9px] rotate-45 inline-block" style={{ background: r.dot }} aria-hidden="true" />
                    <div className="flex flex-col gap-1">
                      <span className="text-[15px] text-ink">{str(c.check)}</span>
                      {str(c.comment) && <span className="text-sm text-muted">{str(c.comment)}</span>}
                    </div>
                    <span className={`font-mono text-[10px] tracking-[0.08em] ${r.cls}`}>{r.label}</span>
                  </div>
                );
              })}
            </div>
          ) : <Empty>Keine Qualitätschecks vorhanden.</Empty>}
        </section>

        <aside className="flex flex-col gap-6">
          <Panel className="p-6 flex flex-col gap-4">
            <div className="label-mono">DATENKONSISTENZ</div>
            <div className="font-display text-[64px] leading-none">{score ?? "–"}<span className="text-2xl text-muted"> / 10</span></div>
            <div className="grid grid-cols-3 border-t border-line pt-4 text-center">
              {(["bestanden", "Warnung", "fehlgeschlagen"] as const).map(k => (
                <div key={k} className="flex flex-col gap-1">
                  <span className={`font-mono text-xl ${RESULT[k].cls}`}>{count(k)}</span>
                  <span className="font-mono text-[10px] tracking-[0.08em] text-muted">{RESULT[k].label}</span>
                </div>
              ))}
            </div>
          </Panel>
          {notes && <p className="m-0 text-[15px] leading-relaxed text-ink-2">{notes}</p>}
        </aside>
      </div>

      <Aggregation d={d} />
    </div>
  );
}
