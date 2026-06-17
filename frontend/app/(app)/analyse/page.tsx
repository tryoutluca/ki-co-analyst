"use client";

import { useEffect, useRef, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { searchTicker, startAnalysis, getJobStatus } from "@/lib/api";
import { recColor, upsideClass, upsideLabel, safeNum, scoreColor } from "@/lib/utils";
import { Search, Play, X, CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import MemoViewer from "@/components/memo/MemoViewer";

function AnalyseInner() {
  const params = useSearchParams();

  const [query,    setQuery]    = useState(params.get("ticker") ?? "");
  const [results,  setResults]  = useState<{ ticker: string; display: string }[]>([]);
  const [selected, setSelected] = useState(params.get("ticker") ?? "");
  const [showDrop, setShowDrop] = useState(false);

  const [jobId,    setJobId]    = useState<string | null>(null);
  const [status,   setStatus]   = useState<"idle"|"running"|"done"|"error">("idle");
  const [progress, setProgress] = useState<string[]>([]);
  const [result,   setResult]   = useState<Record<string, unknown> | null>(null);
  const [histId,   setHistId]   = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState("");

  const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const afterRef   = useRef(0);
  const progressEl = useRef<HTMLDivElement>(null);

  // Auto-scroll progress
  useEffect(() => {
    if (progressEl.current) {
      progressEl.current.scrollTop = progressEl.current.scrollHeight;
    }
  }, [progress]);

  // Ticker search
  useEffect(() => {
    if (query.length < 2) { setResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const res = await searchTicker(query);
        setResults(res.slice(0, 6));
        setShowDrop(true);
      } catch { setResults([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  // Polling
  const poll = useCallback(async (jid: string) => {
    try {
      const data = await getJobStatus(jid, afterRef.current);
      if (data.progress.length > 0) {
        setProgress(prev => [...prev, ...data.progress]);
        afterRef.current += data.progress.length;
      }
      if (data.status === "done") {
        clearInterval(pollRef.current!);
        setStatus("done");
        setResult(data.result);
        setHistId(data.hist_id);
      } else if (data.status === "error") {
        clearInterval(pollRef.current!);
        setStatus("error");
        setErrorMsg(data.error ?? "Unbekannter Fehler");
      }
    } catch { /* ignore transient errors */ }
  }, []);

  async function handleStart() {
    if (!selected) return;
    setStatus("running");
    setProgress([]);
    setResult(null);
    setErrorMsg("");
    afterRef.current = 0;

    try {
      const { job_id } = await startAnalysis(selected);
      setJobId(job_id);
      pollRef.current = setInterval(() => poll(job_id), 2000);
    } catch (e: unknown) {
      setStatus("error");
      setErrorMsg(String(e));
    }
  }

  function handleReset() {
    clearInterval(pollRef.current!);
    setStatus("idle");
    setResult(null);
    setProgress([]);
    setJobId(null);
    setHistId(null);
  }

  function selectTicker(t: string) {
    setSelected(t);
    setQuery(t);
    setShowDrop(false);
  }

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">

      {/* ── Search bar ─────────────────────────────────────────────────── */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-5">
        <h1 className="font-serif text-xl font-semibold text-slate-800 mb-4">
          Aktienanalyse starten
        </h1>

        <div className="flex gap-3 items-start flex-wrap">
          {/* Input + Dropdown */}
          <div className="relative flex-1 min-w-64">
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">
              <Search size={16} />
            </div>
            <input
              type="text"
              value={query}
              onChange={e => { setQuery(e.target.value); setSelected(""); }}
              onFocus={() => results.length > 0 && setShowDrop(true)}
              onBlur={() => setTimeout(() => setShowDrop(false), 150)}
              placeholder="Unternehmen oder Ticker suchen…  z.B. Holcim, AAPL"
              className="w-full pl-9 pr-4 py-2.5 border border-slate-200 rounded-lg text-sm
                         focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                         bg-slate-50 text-slate-800 placeholder-slate-400"
            />
            {showDrop && results.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-slate-200
                              rounded-lg shadow-lg z-50 overflow-hidden">
                {results.map(r => (
                  <button key={r.ticker}
                          onMouseDown={() => selectTicker(r.ticker)}
                          className="w-full text-left px-4 py-2.5 text-sm hover:bg-slate-50
                                     transition-colors border-b border-slate-50 last:border-0">
                    <span className="font-semibold text-slate-800 mr-2">{r.ticker}</span>
                    <span className="text-slate-500">{r.display.replace(r.ticker + " – ", "")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Selected badge */}
          {selected && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg border text-sm font-medium"
                 style={{ background: "rgba(201,168,76,0.1)", borderColor: "#c9a84c", color: "#8a6820" }}>
              {selected}
              <button onClick={() => { setSelected(""); setQuery(""); }}>
                <X size={13} />
              </button>
            </div>
          )}

          {/* Run button */}
          <button
            onClick={status === "idle" || status === "error" ? handleStart : handleReset}
            disabled={status === "running" || !selected}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm
                       text-white shadow transition-all disabled:opacity-50"
            style={{ background: status === "done" ? "#1e7c45" : "#0a1628" }}
          >
            {status === "running" ? (
              <><Loader2 size={15} className="animate-spin" /> Läuft…</>
            ) : status === "done" ? (
              <><CheckCircle size={15} /> Neue Analyse</>
            ) : (
              <><Play size={15} /> Analyse starten</>
            )}
          </button>
        </div>

        {/* Example tickers */}
        <div className="flex flex-wrap gap-2 mt-4">
          <span className="text-xs text-slate-400 self-center">Beispiele:</span>
          {["HOLN.SW","NESN.SW","NOVN.SW","AAPL","MSFT","RGTI"].map(t => (
            <button key={t}
                    onClick={() => selectTicker(t)}
                    className="px-2.5 py-1 rounded text-xs border border-slate-200
                               hover:border-slate-400 text-slate-600 hover:text-slate-900
                               transition-colors bg-white">
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* ── Progress ───────────────────────────────────────────────────── */}
      {(status === "running" || (status === "done" && progress.length > 0)) && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-3 border-b border-slate-100"
               style={{ background: "#0a1628" }}>
            <div className="flex gap-1.5">
              <div className="w-3 h-3 rounded-full bg-red-400" />
              <div className="w-3 h-3 rounded-full bg-amber-400" />
              <div className="w-3 h-3 rounded-full bg-green-400" />
            </div>
            <span className="text-xs text-slate-400 font-mono">
              {status === "running"
                ? `Analyse läuft — ${selected}…`
                : `✓ Abgeschlossen — ${selected}`}
            </span>
            {status === "running" && (
              <Loader2 size={13} className="animate-spin text-slate-400 ml-auto" />
            )}
            {status === "done" && (
              <CheckCircle size={13} className="text-emerald-400 ml-auto" />
            )}
          </div>
          <div ref={progressEl}
               className="h-52 overflow-y-auto p-4 font-mono text-xs text-slate-600 space-y-0.5"
               style={{ background: "#f8fafc" }}>
            {progress.map((line, i) => (
              <div key={i} className={
                line.startsWith("✅") ? "text-emerald-700 font-semibold" :
                line.startsWith("❌") ? "text-red-600 font-semibold" :
                line.startsWith("⚠")  ? "text-amber-700" :
                "text-slate-600"
              }>
                {line}
              </div>
            ))}
            {status === "running" && (
              <div className="text-slate-400 animate-pulse">█</div>
            )}
          </div>
        </div>
      )}

      {/* ── Error ──────────────────────────────────────────────────────── */}
      {status === "error" && (
        <div className="flex items-start gap-3 p-5 bg-red-50 border border-red-200 rounded-xl">
          <AlertCircle size={18} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold text-red-700 text-sm">Analyse fehlgeschlagen</div>
            <div className="text-red-600 text-sm mt-1">{errorMsg}</div>
          </div>
        </div>
      )}

      {/* ── Result ─────────────────────────────────────────────────────── */}
      {status === "done" && result && (
        <MemoViewer data={result} histId={histId ?? undefined} />
      )}

      {/* ── Empty state ────────────────────────────────────────────────── */}
      {status === "idle" && (
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm">
          <div className="py-20 text-center">
            <div className="text-5xl mb-4 opacity-20">📊</div>
            <h3 className="font-serif text-xl font-semibold text-slate-700 mb-2">
              Bereit zur Analyse
            </h3>
            <p className="text-sm text-slate-400 max-w-xs mx-auto">
              Suchen Sie eine Aktie oben und klicken Sie{" "}
              <strong className="text-slate-600">Analyse starten</strong>.
              Die Analyse dauert ca. 60–90 Sekunden.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default function AnalysePage() {
  return (
    <Suspense>
      <AnalyseInner />
    </Suspense>
  );
}
