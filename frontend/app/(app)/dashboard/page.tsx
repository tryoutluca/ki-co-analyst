"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getHistory, getHistoryStats, type HistoryItem } from "@/lib/api";
import { useUsername } from "@/lib/auth";
import { safeNum, upsideClass, upsideLabel, recLabel, recStep } from "@/lib/utils";
import { PIPELINE, AGENT_COUNT_LLM, GRAPH_NODE_COUNT } from "@/lib/pipeline";
import { Diamond } from "@/components/brand/Brand";

const EXAMPLES = [
  { name: "Holcim", ticker: "HOLN.SW" }, { name: "Nestlé", ticker: "NESN.SW" },
  { name: "Novartis", ticker: "NOVN.SW" }, { name: "Roche", ticker: "ROP.SW" },
  { name: "Apple", ticker: "AAPL" }, { name: "Microsoft", ticker: "MSFT" },
];

const REC_ORDER = ["KAUFEN", "ÜBERGEWICHTEN", "HALTEN", "UNTERGEWICHTEN", "VERKAUFEN"];

export default function DashboardPage() {
  const router = useRouter();
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [stats, setStats]     = useState<{ total: number; last: HistoryItem | null; by_rec: Record<string, number> } | null>(null);
  const [loading, setLoading] = useState(true);
  const username = useUsername();

  useEffect(() => {
    Promise.all([
      getHistory(10).then(setHistory).catch(() => {}),
      getHistoryStats().then(setStats).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  const byRec = stats?.by_rec ?? {};
  const maxRec = Math.max(1, ...REC_ORDER.map(r => byRec[r] ?? 0));

  return (
    <div className="flex flex-col">
      <section className="dot-grid border-b border-line px-5 md:px-14 pt-11 pb-9 flex flex-wrap justify-between items-end gap-10">
        <div className="flex flex-col gap-3">
          <div className="eyebrow">DASHBOARD{username ? ` · ${username.toUpperCase()}` : ""}</div>
          <h1 className="m-0 font-display font-normal text-5xl md:text-[72px] leading-none tracking-[-0.02em]">
            Ihr Research. <em className="text-gold-dark">Auf einen Blick.</em>
          </h1>
          <div className="text-[15px] text-muted">
            {AGENT_COUNT_LLM} KI-Agenten · {GRAPH_NODE_COUNT} Knoten · konfidenz-gewichtete Synthese
          </div>
        </div>

        <div className="flex flex-wrap bg-card border border-line shadow-[0_30px_60px_-40px_rgba(60,45,10,0.35)]">
          <div className="px-7 py-5 flex flex-col gap-1.5 bg-ink text-cream">
            <div className="font-mono text-[11px] tracking-[0.12em] text-gold-dim">ANALYSEN</div>
            <div className="font-display text-[40px] leading-none">{stats?.total ?? "–"}</div>
          </div>
          <div className="px-7 py-5 flex flex-col gap-2.5 border-r border-line">
            <div className="label-mono">ZULETZT</div>
            <div className="font-display text-[30px] leading-none">{stats?.last?.ticker ?? "–"}</div>
            <div className="font-mono text-[11px] text-muted">{stats?.last?.date ?? ""}</div>
          </div>
          <div className="px-7 py-5 flex flex-col gap-2 min-w-[220px]">
            <div className="label-mono">EMPFEHLUNGEN</div>
            {REC_ORDER.map(r => (
              <div key={r} className="grid grid-cols-[110px_minmax(0,1fr)_20px] gap-2 items-center">
                <span className="text-xs text-ink-2">{recLabel(r)}</span>
                <div className="h-[5px] bg-bar"><div className="h-[5px] bg-gold" style={{ width: `${((byRec[r] ?? 0) / maxRec) * 100}%` }} /></div>
                <span className="font-mono text-xs text-right">{byRec[r] ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="px-5 md:px-14 pt-10 pb-12 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-10">
        <section className="flex flex-col gap-3.5 min-w-0">
          <div className="flex justify-between items-baseline">
            <h2 className="m-0 font-display font-normal text-[34px]">Letzte Analysen</h2>
            <Link href="/history" className="text-sm font-semibold no-underline">Alle ansehen →</Link>
          </div>
          <div className="bg-card border border-line overflow-x-auto">
            <div className="min-w-[640px]">
              <div className="grid grid-cols-[110px_minmax(0,1fr)_150px_120px_90px_90px] gap-4 px-6 py-3 border-b border-ink font-mono text-[11px] tracking-[0.1em] text-muted">
                <div>TICKER</div><div>UNTERNEHMEN</div><div>EMPFEHLUNG</div><div>KURSZIEL</div><div>UPSIDE</div><div>DATUM</div>
              </div>
              {loading ? (
                <div className="px-6 py-10 text-sm text-muted">Lade …</div>
              ) : history.length === 0 ? (
                <div className="px-6 py-12 flex flex-col gap-3 items-start">
                  <p className="m-0 text-[15px] text-ink-2">Noch keine Analysen gespeichert.</p>
                  <Link href="/analyse" className="text-sm font-semibold no-underline">Erste Analyse starten →</Link>
                </div>
              ) : history.map(item => (
                <Link key={item.id} href={`/history/${item.id}`}
                  className="grid grid-cols-[110px_minmax(0,1fr)_150px_120px_90px_90px] gap-4 px-6 py-4 border-b border-line-2 last:border-b-0 items-center no-underline text-ink hover:bg-paper hover:text-ink">
                  <span className="font-mono text-sm">{item.ticker}</span>
                  <span className="text-[15px] truncate text-ink-2">{item.company}</span>
                  <span className="font-display text-xl flex items-center gap-2">
                    <span className="flex gap-[2px]" aria-hidden="true">
                      {[0, 1, 2, 3, 4].map(i => (
                        <span key={i} className="w-1.5 h-3" style={{ background: recStep(item.recommendation) === i ? "#B08D3C" : "#E4DCC8" }} />
                      ))}
                    </span>
                    {recLabel(item.recommendation)}
                  </span>
                  <span className="font-mono text-sm">{item.currency} {safeNum(item.price_target)}</span>
                  <span className={`font-mono text-sm ${upsideClass(item.upside)}`}>{upsideLabel(item.upside)}</span>
                  <span className="font-mono text-xs text-muted">{item.date}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        <aside className="flex flex-col gap-6">
          <section className="bg-card border border-line p-6 flex flex-col gap-4">
            <h2 className="m-0 font-display font-normal text-[28px]">Schnellstart</h2>
            <div className="grid grid-cols-2 gap-2">
              {EXAMPLES.map(e => (
                <button key={e.ticker} type="button"
                  onClick={() => router.push(`/analyse?ticker=${e.ticker}&start=1&ts=${Date.now()}`)}
                  className="text-left px-3 py-2.5 border border-line-2 hover:border-gold bg-white">
                  <div className="text-sm text-ink">{e.name}</div>
                  <div className="font-mono text-[11px] text-muted">{e.ticker}</div>
                </button>
              ))}
            </div>
          </section>

          <section className="bg-card border border-line p-6 flex flex-col gap-4">
            <div className="flex justify-between items-baseline">
              <h2 className="m-0 font-display font-normal text-[28px]">Pipeline</h2>
              <div className="label-mono">{GRAPH_NODE_COUNT} KNOTEN</div>
            </div>
            <ol className="m-0 p-0 list-none flex flex-col">
              {PIPELINE.map(n => (
                <li key={n.key} className="grid grid-cols-[18px_minmax(0,1fr)_auto] gap-3 items-center min-h-8">
                  <span className="flex justify-center"><Diamond status={n.optional ? "flag" : "done"} /></span>
                  <span className="text-sm">{n.name}</span>
                  <span className="font-mono text-[10px] tracking-[0.06em] text-muted">{n.tag}</span>
                </li>
              ))}
            </ol>
            <p className="m-0 text-xs text-muted">Hohle Raute = läuft nur bei Bedarf (Anomalie, Pre-Revenue, Senior-Review-Kritik).</p>
          </section>
        </aside>
      </div>

      <p className="mx-5 md:mx-14 mb-10 pt-6 border-t border-line text-xs text-muted">
        KI-Co-Analyst · Bachelorthesis Berner Fachhochschule · Keine Anlageberatung im Sinne von Art. 3 lit. c FIDLEG.
      </p>
    </div>
  );
}
