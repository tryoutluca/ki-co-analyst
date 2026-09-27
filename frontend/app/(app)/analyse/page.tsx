"use client";

import { useEffect, useRef, useState, useCallback, Suspense, useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { searchTicker, startAnalysis, getJobStatus, cancelAnalysis } from "@/lib/api";
import { pipelineState, PIPELINE } from "@/lib/pipeline";
import PipelineRun from "@/components/pipeline/PipelineRun";
import MemoViewer from "@/components/memo/MemoViewer";

const EXAMPLES = ["HOLN.SW", "NESN.SW", "NOVN.SW", "ROP.SW", "AAPL", "MSFT"];
const POLL_MS = 2000;

type Status = "idle" | "running" | "done" | "error";

function elapsedLabel(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function AnalyseInner() {
  const params = useSearchParams();

  const [query, setQuery]       = useState(params.get("ticker") ?? "");
  const [results, setResults]   = useState<{ ticker: string; display: string }[]>([]);
  const [selected, setSelected] = useState(params.get("ticker") ?? "");
  const [showDrop, setShowDrop] = useState(false);

  const [status, setStatus]     = useState<Status>("idle");
  const [running, setRunning]   = useState("");          // Ticker des laufenden Jobs
  const [progress, setProgress] = useState<string[]>([]);
  const [result, setResult]     = useState<Record<string, unknown> | null>(null);
  const [histId, setHistId]     = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [startedAt, setStartedAt] = useState(0);
  const [now, setNow]           = useState(0);
  const [notice, setNotice]     = useState("");

  const pollRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const afterRef = useRef(0);
  const jobRef   = useRef<string | null>(null);
  const handledParams = useRef("");

  const stopPolling = () => { if (pollRef.current) clearInterval(pollRef.current); pollRef.current = null; };
  useEffect(() => stopPolling, []);   // Polling beim Verlassen der Seite beenden

  // Laufzeit-Anzeige
  useEffect(() => {
    if (status !== "running") return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [status]);

  // Ticker-Suche (Ergebnisse nur anzeigen, solange eine Suche aktiv ist — abgeleitet statt per setState)
  const searching = query.length >= 2 && query !== selected;
  const visibleResults = searching ? results : [];
  useEffect(() => {
    if (!searching) return;
    const t = setTimeout(async () => {
      try {
        const res = await searchTicker(query);
        setResults(res.slice(0, 6));
        setShowDrop(true);
      } catch { setResults([]); }
    }, 300);
    return () => clearTimeout(t);
  }, [query, searching]);

  const poll = useCallback(async (jid: string) => {
    try {
      const data = await getJobStatus(jid, afterRef.current);
      if (data.progress.length > 0) {
        setProgress(prev => [...prev, ...data.progress]);
        afterRef.current += data.progress.length;
      }
      if (data.status === "done") {
        stopPolling();
        setStatus("done");
        setResult(data.result);
        setHistId(data.hist_id);
      } else if (data.status === "error") {
        stopPolling();
        setStatus("error");
        setErrorMsg(data.error ?? "Unbekannter Fehler");
      } else if (data.status === "cancelled") {
        stopPolling();
      }
    } catch { /* transiente Netzwerkfehler ignorieren */ }
  }, []);

  const start = useCallback(async (ticker: string) => {
    if (!ticker) return;
    stopPolling();
    setStatus("running");
    setRunning(ticker);
    setProgress([]);
    setResult(null);
    setHistId(null);
    setErrorMsg("");
    setNotice("");
    setStartedAt(Date.now());
    setNow(Date.now());
    afterRef.current = 0;
    try {
      const { job_id } = await startAnalysis(ticker);
      jobRef.current = job_id;
      pollRef.current = setInterval(() => poll(job_id), POLL_MS);
    } catch (e: unknown) {
      setStatus("error");
      setErrorMsg(String(e));
    }
  }, [poll]);

  // ?ticker=X&start=1 (Kopfzeile, "Neu berechnen") → Analyse direkt starten
  useEffect(() => {
    const key = params.toString();
    const t = params.get("ticker");
    if (params.get("start") === "1" && t && handledParams.current !== key) {
      handledParams.current = key;
      setQuery(t);
      setSelected(t);
      start(t.toUpperCase());
    }
  }, [params, start]);

  // Abbruch: UI kehrt sofort zurück; das Backend stoppt vor dem nächsten Agenten
  // und speichert nichts in der Historie.
  async function cancel() {
    const jid = jobRef.current;
    stopPolling();
    setStatus("idle");
    setProgress([]);
    setNotice(`Analyse von ${running} abgebrochen — der laufende Agent wird im Hintergrund noch beendet, danach stoppt die Pipeline. Es wird nichts gespeichert.`);
    jobRef.current = null;
    if (jid) {
      try { await cancelAnalysis(jid); }
      catch { setNotice(`Abbruch von ${running} konnte nicht an den Server gesendet werden.`); }
    }
  }

  function selectTicker(t: string) {
    setSelected(t);
    setQuery(t);
    setShowDrop(false);
  }

  const nodes = useMemo(() => pipelineState(progress, status === "done"), [progress, status]);
  const finished = nodes.filter(n => n.status === "done" || n.status === "flag" || n.status === "skip").length;
  const active = nodes.find(n => n.status === "active");
  const feed = progress.slice(-120);

  return (
    <div className="flex flex-col">
      {/* ── Suche ───────────────────────────────────────────────────────── */}
      <section className="dot-grid border-b border-line px-5 md:px-14 pt-11 pb-9 flex flex-col gap-6">
        <div className="flex flex-col gap-3">
          <div className="eyebrow">NEUE ANALYSE</div>
          <h1 className="m-0 font-display font-normal text-5xl md:text-[64px] leading-none tracking-[-0.02em]">
            Aktie <em className="text-gold-dark">analysieren.</em>
          </h1>
        </div>

        <form
          onSubmit={e => { e.preventDefault(); start((selected || query).trim().toUpperCase()); }}
          className="flex flex-wrap gap-3 items-start"
        >
          <div className="relative flex-1 min-w-[260px] max-w-[560px]">
            <label htmlFor="analyse-q" className="sr-only">Unternehmen oder Ticker</label>
            <input
              id="analyse-q"
              value={query}
              onChange={e => { setQuery(e.target.value); setSelected(""); }}
              onFocus={() => visibleResults.length > 0 && setShowDrop(true)}
              onBlur={() => setTimeout(() => setShowDrop(false), 150)}
              placeholder="Unternehmen oder Ticker, z. B. Holcim oder AAPL"
              autoComplete="off"
              className="w-full h-14 px-4 border border-line-3 rounded-[2px] bg-white text-base text-ink outline-none focus:border-gold"
            />
            {showDrop && visibleResults.length > 0 && (
              <ul className="absolute top-full left-0 right-0 mt-1 m-0 p-0 list-none bg-card border border-line z-50 shadow-[0_20px_40px_-20px_rgba(60,45,10,0.3)]">
                {visibleResults.map(r => (
                  <li key={r.ticker}>
                    <button type="button" onMouseDown={() => selectTicker(r.ticker)}
                      className="w-full text-left px-4 py-3 text-sm hover:bg-paper border-b border-line-2 last:border-0">
                      <span className="font-mono text-ink mr-3">{r.ticker}</span>
                      <span className="text-muted">{r.display.replace(r.ticker + " – ", "")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button type="submit" disabled={status === "running" || !(selected || query).trim()}
            className="h-14 px-8 rounded-[2px] bg-ink text-cream text-base font-semibold disabled:opacity-50">
            {status === "running" ? "Analyse läuft …" : status === "done" ? "Neue Analyse" : "Analyse starten"}
          </button>
        </form>

        <div className="flex flex-wrap gap-2 items-center">
          <span className="label-mono mr-1">Beispiele</span>
          {EXAMPLES.map(t => (
            <button key={t} type="button" onClick={() => selectTicker(t)}
              className="h-9 px-3 font-mono text-xs border border-line-3 rounded-[2px] bg-card text-ink-2 hover:border-gold">
              {t}
            </button>
          ))}
        </div>
      </section>

      {/* ── Live-Lauf ───────────────────────────────────────────────────── */}
      {status === "running" && (
        <section className="px-5 md:px-14 py-10 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-10" aria-live="polite">
          <div className="flex flex-col gap-4 min-w-0">
            <div className="flex flex-wrap justify-between items-baseline gap-3">
              <h2 className="m-0 font-display font-normal text-[34px]">
                {running} · <em className="text-gold-dark">{active ? active.name : "startet"}</em>
              </h2>
              <div className="flex items-center gap-5">
                <div className="label-mono">{finished} / {PIPELINE.length} KNOTEN · {elapsedLabel(now - startedAt)}</div>
                <button type="button" onClick={cancel}
                  className="h-11 px-5 rounded-[2px] border border-negative/50 text-negative text-sm font-semibold hover:bg-[#FBEFEF]">
                  Abbrechen
                </button>
              </div>
            </div>
            <div className="h-[3px] bg-bar" role="progressbar" aria-valuemin={0} aria-valuemax={PIPELINE.length} aria-valuenow={finished}>
              <div className="h-[3px] bg-gold transition-[width] duration-500" style={{ width: `${(finished / PIPELINE.length) * 100}%` }} />
            </div>
            <div className="bg-card border border-line">
              <div className="px-6 py-3 border-b border-ink font-mono text-[11px] tracking-[0.1em] text-muted">LIVE-REASONING</div>
              <div className="h-[460px] overflow-y-auto px-6 py-3 flex flex-col-reverse">
                <div className="flex flex-col">
                  {feed.map((line, i) => {
                    const node = /^\[[a-z_]+\]/.test(line);
                    const bad = /❌|Fehler/.test(line);
                    return (
                      <div key={progress.length - feed.length + i}
                        className={`fade-in font-mono text-xs leading-relaxed py-0.5 break-words ${
                          bad ? "text-negative" : node ? "text-ink font-medium pt-2" : "text-muted"
                        }`}>
                        {line}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
          <aside className="bg-card border border-line p-6 flex flex-col gap-4 self-start">
            <div className="flex justify-between items-baseline">
              <h2 className="m-0 font-display font-normal text-[28px]">Pipeline-Lauf</h2>
              <div className="label-mono">LIVE</div>
            </div>
            <PipelineRun nodes={nodes} />
          </aside>
        </section>
      )}

      {notice && status === "idle" && (
        <div role="status" className="mx-5 md:mx-14 mt-8 px-6 py-4 border border-line-3 bg-card text-sm text-ink-2">
          {notice}
        </div>
      )}

      {status === "error" && (
        <div className="mx-5 md:mx-14 my-10 px-6 py-5 border border-negative/40 bg-[#FBEFEF]">
          <div className="font-display text-2xl text-negative">Analyse fehlgeschlagen</div>
          <div className="text-sm text-negative mt-1 break-words">{errorMsg}</div>
        </div>
      )}

      {status === "done" && result && <MemoViewer data={result} histId={histId ?? undefined} />}

      {status === "idle" && (
        <section className="px-5 md:px-14 py-16 grid grid-cols-1 md:grid-cols-4 border-t-0">
          {[
            ["01", "Klassifizieren", "Das Geschäftsmodell bestimmt, welche Bewertungsmethoden gelten."],
            ["02", "Analysieren", "Fundamental, News, Thematik, Forward-Schätzung und Risiko — mit Retries."],
            ["03", "Prüfen", "Qualitätscheck und Senior Review, bei Bedarf mit gezielter Kritik."],
            ["04", "Synthese", "Der Supervisor gewichtet nach Konfidenz und schreibt das Memo."],
          ].map(([n, t, p], i) => (
            <div key={n} className={`pt-8 pr-8 flex flex-col gap-3 border-t border-ink ${i > 0 ? "md:pl-8 md:border-l md:border-l-line" : ""}`}>
              <div className="font-mono text-[13px] text-gold-dark">{n}</div>
              <h3 className="m-0 font-display font-normal text-[28px]">{t}</h3>
              <p className="m-0 text-[15px] leading-relaxed text-ink-2">{p}</p>
            </div>
          ))}
        </section>
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
