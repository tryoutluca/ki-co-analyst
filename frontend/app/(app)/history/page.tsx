"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getHistory, deleteHistoryItem, type HistoryItem } from "@/lib/api";
import { safeNum, upsideClass, upsideLabel, recLabel } from "@/lib/utils";
import { Trash2 } from "lucide-react";

const COLS = "grid-cols-[110px_minmax(0,1fr)_100px_150px_120px_90px_90px_44px]";

export default function HistoryPage() {
  const [items, setItems]     = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch]   = useState("");

  useEffect(() => {
    getHistory(100).then(setItems).catch(() => {}).finally(() => setLoading(false));
  }, []);

  async function handleDelete(item: HistoryItem) {
    if (!confirm(`Analyse ${item.ticker} vom ${item.date} löschen?`)) return;
    await deleteHistoryItem(item.id);
    setItems(prev => prev.filter(i => i.id !== item.id));
  }

  const q = search.toLowerCase();
  const filtered = q
    ? items.filter(i => i.ticker.toLowerCase().includes(q) || i.company.toLowerCase().includes(q))
    : items;

  return (
    <div className="flex flex-col">
      <section className="dot-grid border-b border-line px-5 md:px-14 pt-11 pb-9 flex flex-wrap justify-between items-end gap-8">
        <div className="flex flex-col gap-3">
          <div className="eyebrow">HISTORIE · {items.length} {items.length === 1 ? "ANALYSE" : "ANALYSEN"}</div>
          <h1 className="m-0 font-display font-normal text-5xl md:text-[72px] leading-none tracking-[-0.02em]">
            Alle Analysen. <em className="text-gold-dark">Nachvollziehbar.</em>
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <label htmlFor="hist-q" className="label-mono">Suche</label>
          <input id="hist-q" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Ticker oder Unternehmen"
            className="w-[260px] h-11 px-3.5 border border-line-3 rounded-[2px] bg-white text-[15px] outline-none focus:border-gold" />
        </div>
      </section>

      <div className="px-5 md:px-14 pt-10 pb-12">
        <div className="bg-card border border-line overflow-x-auto">
          <div className="min-w-[860px]">
            <div className={`grid ${COLS} gap-4 px-6 py-3 border-b border-ink font-mono text-[11px] tracking-[0.1em] text-muted`}>
              <div>TICKER</div><div>UNTERNEHMEN</div><div>DATUM</div><div>EMPFEHLUNG</div><div>KURSZIEL</div><div>UPSIDE</div><div>KONSISTENZ</div><div />
            </div>
            {loading ? (
              <div className="px-6 py-10 text-sm text-muted">Lade …</div>
            ) : filtered.length === 0 ? (
              <div className="px-6 py-12 flex flex-col gap-3 items-start">
                <p className="m-0 text-[15px] text-ink-2">{search ? "Keine Treffer." : "Noch keine Analysen gespeichert."}</p>
                {!search && <Link href="/analyse" className="text-sm font-semibold no-underline">Erste Analyse starten →</Link>}
              </div>
            ) : filtered.map(item => (
              <div key={item.id} className={`grid ${COLS} gap-4 px-6 py-4 border-b border-line-2 last:border-b-0 items-center hover:bg-paper`}>
                <Link href={`/history/${item.id}`} className="font-mono text-sm text-ink no-underline hover:underline">{item.ticker}</Link>
                <Link href={`/history/${item.id}`} className="text-[15px] truncate text-ink-2 no-underline hover:text-ink">{item.company}</Link>
                <span className="font-mono text-xs text-muted">{item.date}</span>
                <span className="font-display text-xl">{recLabel(item.recommendation)}</span>
                <span className="font-mono text-sm">{item.currency} {safeNum(item.price_target)}</span>
                <span className={`font-mono text-sm ${upsideClass(item.upside)}`}>{upsideLabel(item.upside)}</span>
                <span className="font-mono text-sm">{item.score ?? "–"}<span className="text-muted"> / 10</span></span>
                <button type="button" onClick={() => handleDelete(item)}
                  className="w-11 h-11 flex items-center justify-center text-muted hover:text-negative"
                  aria-label={`Analyse ${item.ticker} vom ${item.date} löschen`}>
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
