"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getHistory, getHistoryStats, type HistoryItem } from "@/lib/api";
import { recColor, upsideClass, upsideLabel, scoreColor, safeNum } from "@/lib/utils";
import { ArrowUpRight, TrendingUp, Clock, BarChart3, Bot, ChevronRight } from "lucide-react";

const AGENTS = [
  { icon: "🏷️", name: "Classifier",        desc: "Geschäftsmodell-Klassifikation & Peer-Gruppen" },
  { icon: "🔍", name: "Fundamental",        desc: "IR-Dokumente · DCF · Multiples · Bilanz" },
  { icon: "📰", name: "News / Sentiment",   desc: "Makro · Branchentrends · Nachrichten" },
  { icon: "📐", name: "Estimate Revision",  desc: "Makro-adjustierte Konsensschätzungen" },
  { icon: "🌐", name: "Thematic",           desc: "Megatrends · Adoptionskurven · Positionierung" },
  { icon: "🎲", name: "Optionality",        desc: "Real Options · Pre-Revenue-Bewertung" },
  { icon: "📈", name: "Forward Estimates",  desc: "Wachstums-Projektion · Szenarienmodell" },
  { icon: "⚖️", name: "Risk (Advocatus)",  desc: "Gegenposition · Conviction Killers" },
  { icon: "✍️", name: "Supervisor",         desc: "Synthese · Qualitätsprüfung · Final Memo" },
];

const EXAMPLES = [
  { name: "Holcim",    ticker: "HOLN.SW", flag: "🇨🇭" },
  { name: "Nestlé",    ticker: "NESN.SW", flag: "🇨🇭" },
  { name: "Novartis",  ticker: "NOVN.SW", flag: "🇨🇭" },
  { name: "Apple",     ticker: "AAPL",    flag: "🇺🇸" },
  { name: "MSFT",      ticker: "MSFT",    flag: "🇺🇸" },
  { name: "Rigetti",   ticker: "RGTI",    flag: "🇺🇸" },
];

function StatCard({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold tracking-widest uppercase text-slate-400">{label}</span>
        <span className="text-slate-300">{icon}</span>
      </div>
      <div className="font-serif text-2xl font-bold text-slate-800">{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

function RecBadge({ rec }: { rec: string }) {
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold border ${recColor(rec)}`}>
      {rec}
    </span>
  );
}

export default function DashboardPage() {
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [stats,   setStats]   = useState<{ total: number; last: HistoryItem | null } | null>(null);

  useEffect(() => {
    getHistory(10).then(setHistory).catch(() => {});
    getHistoryStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-8">

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <div className="relative rounded-2xl overflow-hidden text-white"
           style={{ background: "linear-gradient(135deg, #0a1628 0%, #1a2f45 55%, #0f2030 100%)" }}>
        {/* Gold glow */}
        <div className="absolute top-0 right-0 w-80 h-80 opacity-10 pointer-events-none"
             style={{ background: "radial-gradient(circle, #c9a84c 0%, transparent 70%)" }} />

        <div className="relative px-8 py-10 md:py-12">
          <p className="text-xs font-semibold tracking-widest uppercase mb-3"
             style={{ color: "#c9a84c" }}>
            KI-gestützte Aktienanalyse · BFH Bachelor Thesis 2025/26
          </p>
          <h1 className="font-serif text-3xl md:text-4xl font-bold leading-tight mb-4">
            Institutional-Grade<br className="hidden md:block" />
            Equity Research — automatisiert.
          </h1>
          <p className="text-slate-300 text-sm md:text-base max-w-xl leading-relaxed mb-8">
            Neun spezialisierte KI-Agenten analysieren Fundamentaldaten, IR-Dokumente,
            Makro-Indikatoren und Risiken — und synthetisieren ein vollständiges
            Investment Memo in 60–90 Sekunden.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/analyse"
                  className="flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-sm
                             text-slate-900 shadow-lg transition-all hover:opacity-90"
                  style={{ background: "#c9a84c" }}>
              Analyse starten
              <ArrowUpRight size={16} />
            </Link>
            <Link href="/history"
                  className="flex items-center gap-2 px-6 py-3 rounded-lg font-semibold text-sm
                             text-white border border-white/20 hover:bg-white/10 transition-all">
              <Clock size={15} />
              Historie
            </Link>
          </div>
        </div>
      </div>

      {/* ── Stats ────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard icon={<BarChart3 size={18} />} label="Analysen gesamt"
                  value={String(stats?.total ?? "-")} sub="seit Inbetriebnahme" />
        <StatCard icon={<TrendingUp size={18} />} label="Letzte Analyse"
                  value={stats?.last?.ticker ?? "-"} sub={stats?.last?.date ?? ""} />
        <StatCard icon={<Bot size={18} />} label="KI-Agenten"
                  value="9" sub="Classifier + 8 Spezialisten" />
        <StatCard icon={<ArrowUpRight size={18} />} label="Modelle"
                  value="Claude + GPT" sub="Sonnet 4.6 / GPT-5.4-mini" />
      </div>

      {/* ── Content grid ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Letzte Analysen */}
        <div className="lg:col-span-2 bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
            <h2 className="font-serif text-base font-semibold text-slate-800">Letzte Analysen</h2>
            <Link href="/history"
                  className="text-xs text-slate-400 hover:text-slate-700 flex items-center gap-1">
              Alle <ChevronRight size={12} />
            </Link>
          </div>

          {history.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <div className="text-4xl mb-3 opacity-30">📊</div>
              <p className="text-sm text-slate-400">Noch keine Analysen — starten Sie mit der Suche.</p>
              <Link href="/analyse" className="mt-4 inline-block text-sm font-medium"
                    style={{ color: "#c9a84c" }}>
                Erste Analyse starten →
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {history.map(item => (
                <Link key={item.id} href={`/history/${item.id}`}
                      className="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 transition-colors">
                  {/* Ticker */}
                  <div className="w-20 flex-shrink-0">
                    <div className="font-serif font-bold text-slate-800">{item.ticker}</div>
                    <div className="text-xs text-slate-400 truncate">{item.company}</div>
                  </div>
                  {/* Rec */}
                  <div className="flex-1 min-w-0">
                    <RecBadge rec={item.recommendation} />
                  </div>
                  {/* PT */}
                  <div className="text-right hidden sm:block">
                    <div className="text-sm font-semibold text-slate-700">
                      {item.currency} {safeNum(item.price_target)} PT
                    </div>
                    <div className={`text-xs font-medium ${upsideClass(item.upside)}`}>
                      {upsideLabel(item.upside)}
                    </div>
                  </div>
                  {/* Score */}
                  <div className={`text-lg font-bold w-10 text-right hidden md:block ${scoreColor(item.score)}`}>
                    {item.score ?? "-"}
                  </div>
                  {/* Date */}
                  <div className="text-xs text-slate-400 w-20 text-right flex-shrink-0">
                    {item.date}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Rechte Spalte: Quick-Start + Pipeline */}
        <div className="space-y-5">

          {/* Quick-Start */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="font-serif text-base font-semibold text-slate-800">Schnell starten</h2>
            </div>
            <div className="p-4 grid grid-cols-2 gap-2">
              {EXAMPLES.map(({ name, ticker, flag }) => (
                <Link key={ticker} href={`/analyse?ticker=${ticker}`}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm border
                                 border-slate-100 hover:border-slate-300 hover:bg-slate-50
                                 transition-all text-slate-700">
                  <span>{flag}</span>
                  <div className="min-w-0">
                    <div className="font-medium text-xs truncate">{name}</div>
                    <div className="text-xs text-slate-400">{ticker}</div>
                  </div>
                </Link>
              ))}
            </div>
          </div>

          {/* Agent-Pipeline */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="font-serif text-base font-semibold text-slate-800">Agenten-Pipeline</h2>
            </div>
            <div className="divide-y divide-slate-50">
              {AGENTS.map(({ icon, name, desc }) => (
                <div key={name} className="flex items-center gap-3 px-5 py-3">
                  <span className="text-base w-6 flex-shrink-0">{icon}</span>
                  <div className="min-w-0">
                    <div className="text-xs font-semibold text-slate-700">{name}</div>
                    <div className="text-xs text-slate-400 truncate">{desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <p className="text-center text-xs text-slate-400 pt-4 border-t border-slate-200">
        KI-Co-Analyst · Berner Fachhochschule · Bachelor Thesis 2025/26 · Luca Lüdi
        · Kein Ersatz für professionelle Anlageberatung (Art. 3 lit. c FIDLEG)
      </p>
    </div>
  );
}
