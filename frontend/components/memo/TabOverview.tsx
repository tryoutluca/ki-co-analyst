"use client";

import { useRouter } from "next/navigation";
import PipelineRun from "@/components/pipeline/PipelineRun";
import { pipelineState } from "@/lib/pipeline";
import { type Memo, asList, asObj, str, num, SectionTitle, Panel } from "./ui";

interface AgentRow {
  key: string; name: string; tag: string; text: string;
  confidence: number | null; ran: boolean; after_critique?: boolean;
}

const TARGET_LABEL: Record<string, string> = { fundamental: "Fundamental", news: "News", risk: "Risk" };

/** Ältere Memos (vor agent_results) — Zeilen aus den vorhandenen Feldern. */
function fallbackAgentRows(d: Memo): AgentRow[] {
  const conf  = asObj(d.agent_confidence_scores) ?? {};
  const th    = asObj(d.thematic_analysis);
  const fe    = asObj(d.forward_estimates);
  const opt   = asObj(d.optionality_analysis);
  const rev   = asObj(d.revised_estimates);
  const cases = asList(d.investment_case);
  return [
    { key: "fundamental", name: "Fundamental", tag: "KENNZAHLEN · BEWERTUNG",
      text: str(cases[0]?.point, "–"), confidence: num(conf.fundamental), ran: true },
    { key: "news", name: "News", tag: "NACHRICHTENLAGE", text: "–", confidence: num(conf.news), ran: true },
    { key: "estimate_revision", name: "Estimate Revision", tag: "MAKRO-REVISION · DETERMINISTISCH",
      text: str(rev?.summary, "–"), confidence: null, ran: Boolean(rev) },
    { key: "thematic", name: "Thematic", tag: "THEMEN · TRENDS",
      text: str(th?.thematic_thesis ?? th?.summary, "–"), confidence: num(th?.self_confidence), ran: Boolean(th) },
    { key: "forward_estimate", name: "Forward Estimate", tag: "WACHSTUM",
      text: str(fe?.overall_thesis, "–"), confidence: num(fe?.self_confidence), ran: Boolean(fe) },
    { key: "risk", name: "Risk", tag: "RISIKOPROFIL",
      text: str(d.advocatus_diaboli_summary, "–"), confidence: num(conf.risk), ran: true },
    { key: "optionality", name: "Optionality", tag: "PRE-REVENUE",
      text: str(opt?.optionality_thesis, "Nicht relevant für dieses Geschäftsmodell."),
      confidence: num(opt?.self_confidence), ran: Boolean(opt) },
  ];
}

function AgentTable({ rows }: { rows: AgentRow[] }) {
  return (
    <Panel className="flex flex-col">
      <div>
        <div className="hidden md:grid grid-cols-[200px_minmax(0,1fr)_190px] gap-6 px-6 py-3 border-b border-ink font-mono text-[11px] tracking-[0.1em] text-muted">
          <div>AGENT</div><div>KERNAUSSAGE</div><div>KONFIDENZ</div>
        </div>
        {rows.map(a => {
          const c = a.confidence;
          return (
            <div key={a.key} className="grid grid-cols-1 md:grid-cols-[200px_minmax(0,1fr)_190px] gap-2 md:gap-6 px-5 md:px-6 py-4 border-b border-line-2 md:items-center last:border-b-0">
              <div className="flex flex-col gap-0.5">
                <div className={`font-display text-[22px] ${a.ran ? "text-ink" : "text-muted-2"}`}>{a.name}</div>
                <div className="font-mono text-[10px] tracking-[0.08em] text-muted-2">
                  {a.tag}{a.after_critique ? " · NACH KRITIK" : ""}
                </div>
              </div>
              <div className="text-[15px] leading-relaxed text-ink-2">{a.text || "–"}</div>
              <div className="flex items-center gap-3">
                <div className="flex-grow h-[5px] bg-bar" role="img"
                  aria-label={c != null ? `Konfidenz ${Math.round(c * 100)} Prozent` : "Keine Konfidenz (deterministisch oder nicht gelaufen)"}>
                  <div className="h-[5px] bg-gold" style={{ width: c != null ? `${Math.round(c * 100)}%` : "0%" }} />
                </div>
                <div className="font-mono text-[13px] w-[34px] text-right">{c != null ? c.toFixed(2) : "–"}</div>
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function SeniorReview({ d }: { d: Memo }) {
  const sr = asObj(d.senior_review);
  // Ältere Memos: Review nur im routing_log
  const logLine = asList<string>(d.routing_log).find(l => l.startsWith("[supervisor_review]")) ?? "";
  const target = str(sr?.target) || (logLine.match(/Kritik → (\w+)/)?.[1] ?? "");
  const critique = str(sr?.critique);
  const notes = str(sr?.notes) || logLine.replace(/^\[supervisor_review\]\s*(✅|↩)?\s*/, "");
  const rounds = num(sr?.rounds) ?? (target ? 1 : 0);

  return (
    <section className="bg-ink text-cream-2 p-6 flex flex-col gap-3">
      <div className="flex justify-between font-mono text-[11px] tracking-[0.12em]">
        <span className="text-gold-dim">SENIOR REVIEW</span>
        <span className="text-[#9C968A]">RUNDE {rounds} / 1</span>
      </div>
      {target ? (
        <div className="font-display text-2xl leading-tight">
          Kritik an <em className="text-gold-dim">{TARGET_LABEL[target] ?? target}</em> zurückgespielt
        </div>
      ) : (
        <div className="font-display text-2xl leading-tight">Ergebnisse <em className="text-gold-dim">freigegeben</em></div>
      )}
      {(critique || notes) && (
        <p className="m-0 text-sm leading-relaxed text-dark-muted">{critique || notes}</p>
      )}
    </section>
  );
}

export default function TabOverview({ d, histId, onPdf }: { d: Memo; histId?: string; onPdf?: () => void }) {
  const router = useRouter();
  const thesis = str(d.summary_bottom_line) || str(d.final_reasoning).split("│")[0];
  const exec   = str(d.executive_summary);
  const rows   = asList<AgentRow>(d.agent_results);
  const agents = rows.length ? rows : fallbackAgentRows(d);
  const nodes  = pipelineState(asList<string>(d.routing_log), true);
  const ticker = str(d.ticker);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-10">
      <div className="flex flex-col gap-9 min-w-0">
        <section className="flex flex-col gap-3.5">
          <div className="eyebrow plain">INVESTMENT-THESE · SUPERVISOR</div>
          <p className="m-0 font-display text-[28px] leading-[1.35] text-ink max-w-[860px] text-pretty">
            {thesis || "–"}
          </p>
          {exec && <p className="m-0 text-base leading-relaxed text-ink-2 max-w-[860px]">{exec}</p>}
        </section>

        <section className="flex flex-col gap-3.5">
          <SectionTitle aside="KONFIDENZ FLIESST IN DIE GEWICHTUNG">Ergebnisse der Agenten</SectionTitle>
          <AgentTable rows={agents} />
        </section>
      </div>

      <aside className="flex flex-col gap-6 min-w-0">
        <Panel className="p-6 flex flex-col gap-4">
          <div className="flex justify-between items-baseline">
            <h2 className="m-0 font-display font-normal text-[28px]">Pipeline-Lauf</h2>
            <div className="label-mono">19 KNOTEN</div>
          </div>
          {nodes.some(n => n.status !== "pending")
            ? <PipelineRun nodes={nodes} />
            : <p className="m-0 text-sm text-muted">Für diese Analyse ist kein Routing-Log gespeichert.</p>}
        </Panel>

        <SeniorReview d={d} />

        <div className="flex gap-3">
          {histId && onPdf && (
            <button type="button" onClick={onPdf}
              className="flex-grow h-12 rounded-[2px] bg-ink text-cream text-[15px] font-semibold">
              Memo als PDF
            </button>
          )}
          {ticker && (
            <button type="button"
              onClick={() => router.push(`/analyse?ticker=${encodeURIComponent(ticker)}&start=1&ts=${Date.now()}`)}
              className="flex-grow h-12 rounded-[2px] border border-gold text-ink text-[15px] font-semibold">
              Neu berechnen
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}
