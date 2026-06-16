"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getHistory, deleteHistoryItem, type HistoryItem } from "@/lib/api";
import { recColor, upsideClass, upsideLabel, safeNum, scoreColor } from "@/lib/utils";
import { Trash2, ExternalLink, Search } from "lucide-react";

function RecBadge({ rec }: { rec: string }) {
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold border ${recColor(rec)}`}>
      {rec}
    </span>
  );
}

export default function HistoryPage() {
  const [items,   setItems]  = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search,  setSearch]  = useState("");

  useEffect(() => {
    getHistory(100).then(setItems).finally(() => setLoading(false));
  }, []);

  async function handleDelete(id: string) {
    if (!confirm("Analyse löschen?")) return;
    await deleteHistoryItem(id);
    setItems(prev => prev.filter(i => i.id !== id));
  }

  const filtered = search
    ? items.filter(i =>
        i.ticker.toLowerCase().includes(search.toLowerCase()) ||
        i.company.toLowerCase().includes(search.toLowerCase()))
    : items;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-serif text-2xl font-bold text-slate-800">Analyse-Historie</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {items.length} gespeicherte {items.length === 1 ? "Analyse" : "Analysen"}
          </p>
        </div>
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Suchen…"
            className="pl-9 pr-4 py-2 border border-slate-200 rounded-lg text-sm
                       focus:outline-none focus:border-blue-400 bg-white w-56"
          />
        </div>
      </div>

      {loading ? (
        <div className="text-center py-20 text-slate-400 text-sm">Lade…</div>
      ) : filtered.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm py-20 text-center">
          <div className="text-4xl mb-3 opacity-20">📂</div>
          <p className="text-sm text-slate-400">
            {search ? "Keine Treffer." : "Noch keine Analysen gespeichert."}
          </p>
          {!search && (
            <Link href="/analyse"
                  className="mt-4 inline-block text-sm font-medium"
                  style={{ color: "#c9a84c" }}>
              Erste Analyse starten →
            </Link>
          )}
        </div>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  {["Ticker","Unternehmen","Datum","Empfehlung","Kursziel","Upside","Score",""].map(h => (
                    <th key={h}
                        className="px-4 py-3 text-left text-xs font-semibold tracking-wide uppercase text-slate-400">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {filtered.map(item => (
                  <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-serif font-bold text-slate-800">
                      {item.ticker}
                    </td>
                    <td className="px-4 py-3 text-slate-600 max-w-48 truncate">{item.company}</td>
                    <td className="px-4 py-3 text-slate-500">{item.date}</td>
                    <td className="px-4 py-3">
                      <RecBadge rec={item.recommendation} />
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-700">
                      {item.currency} {safeNum(item.price_target)}
                    </td>
                    <td className={`px-4 py-3 font-medium ${upsideClass(item.upside)}`}>
                      {upsideLabel(item.upside)}
                    </td>
                    <td className={`px-4 py-3 font-bold ${scoreColor(item.score)}`}>
                      {item.score ?? "-"}<span className="text-slate-400 font-normal">/10</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Link href={`/history/${item.id}`}
                              className="p-1.5 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors">
                          <ExternalLink size={14} />
                        </Link>
                        <button
                          onClick={() => handleDelete(item.id)}
                          className="p-1.5 rounded hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors">
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
