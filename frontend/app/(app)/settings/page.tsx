"use client";

import { useState } from "react";
import { changePassword } from "@/lib/api";
import { useUsername } from "@/lib/auth";

// Modelle wie im Code konfiguriert (graph/supervisor.py, tools/ir_rag_tool.py,
// agents/*, graph/nodes.py) — bei Modellwechsel hier nachführen.
const SYSTEM_INFO = [
  { label: "Supervisor (Synthese)",        val: "Claude Sonnet 4.5" },
  { label: "IR-Berichte (RAG-Extraktion)", val: "Claude Sonnet 4.6" },
  { label: "Agenten & Sub-Agenten",        val: "GPT-5.4-mini" },
  { label: "Senior Review · Corp. Actions", val: "GPT-4o-mini" },
  { label: "Datenquellen",                 val: "yfinance · SEC EDGAR · IR-Berichte · Finnhub · Tavily" },
  { label: "Frontend",                     val: "Next.js 16 · Tailwind CSS 4" },
  { label: "Backend",                      val: "FastAPI · LangGraph" },
];

const INPUT = "w-full h-11 px-3.5 border border-line-3 rounded-[2px] bg-white text-[15px] outline-none focus:border-gold";

export default function SettingsPage() {
  const [oldPw, setOldPw]   = useState("");
  const [newPw, setNewPw]   = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [msg, setMsg]       = useState<{ ok: boolean; text: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const username = useUsername();

  async function handlePwChange(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (newPw !== newPw2) { setMsg({ ok: false, text: "Passwörter stimmen nicht überein." }); return; }
    if (newPw.length < 8) { setMsg({ ok: false, text: "Mindestens 8 Zeichen." }); return; }
    setLoading(true);
    try {
      await changePassword(oldPw, newPw);
      setMsg({ ok: true, text: "Passwort geändert." });
      setOldPw(""); setNewPw(""); setNewPw2("");
    } catch {
      setMsg({ ok: false, text: "Aktuelles Passwort falsch oder Server-Fehler." });
    } finally {
      setLoading(false);
    }
  }

  const fields = [
    { id: "pw-old",  label: "Aktuelles Passwort", val: oldPw,  set: setOldPw,  auto: "current-password" },
    { id: "pw-new",  label: "Neues Passwort",     val: newPw,  set: setNewPw,  auto: "new-password" },
    { id: "pw-new2", label: "Wiederholen",        val: newPw2, set: setNewPw2, auto: "new-password" },
  ];

  return (
    <div className="flex flex-col">
      <section className="dot-grid border-b border-line px-5 md:px-14 pt-11 pb-9 flex flex-col gap-3">
        <div className="eyebrow">EINSTELLUNGEN{username ? ` · ${username.toUpperCase()}` : ""}</div>
        <h1 className="m-0 font-display font-normal text-5xl md:text-[72px] leading-none tracking-[-0.02em]">
          Konto <em className="text-gold-dark">&amp; System.</em>
        </h1>
      </section>

      <div className="px-5 md:px-14 pt-10 pb-12 grid grid-cols-1 lg:grid-cols-2 gap-10">
        <section className="bg-card border border-line p-7 flex flex-col gap-5">
          <h2 className="m-0 font-display font-normal text-[32px]">Passwort ändern</h2>
          <form onSubmit={handlePwChange} className="flex flex-col gap-4">
            {fields.map(f => (
              <div key={f.id} className="flex flex-col gap-1.5">
                <label htmlFor={f.id} className="label-mono">{f.label}</label>
                <input id={f.id} type="password" value={f.val} onChange={e => f.set(e.target.value)}
                  autoComplete={f.auto} required className={INPUT} />
              </div>
            ))}
            {msg && (
              <div role="status" className={`px-4 py-3 text-sm border ${msg.ok ? "border-positive/40 text-positive bg-[#EEF6F1]" : "border-negative/40 text-negative bg-[#FBEFEF]"}`}>
                {msg.text}
              </div>
            )}
            <button type="submit" disabled={loading}
              className="h-12 rounded-[2px] bg-ink text-cream text-[15px] font-semibold disabled:opacity-50">
              {loading ? "Wird gespeichert …" : "Passwort aktualisieren"}
            </button>
          </form>
        </section>

        <div className="flex flex-col gap-6">
          <section className="bg-card border border-line p-7 flex flex-col gap-4">
            <h2 className="m-0 font-display font-normal text-[32px]">System</h2>
            <dl className="m-0">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-3 border-t border-line-2">
                <dt className="text-sm text-muted">Angemeldet als</dt>
                <dd className="m-0 text-sm text-ink text-right">{username || "–"}</dd>
              </div>
              {SYSTEM_INFO.map(({ label, val }) => (
                <div key={label} className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 py-3 border-t border-line-2">
                  <dt className="text-sm text-muted">{label}</dt>
                  <dd className="m-0 text-sm text-ink text-right">{val}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="bg-ink text-cream-2 p-6 flex flex-col gap-2">
            <div className="font-mono text-[11px] tracking-[0.12em] text-gold-dim">RECHTLICHER HINWEIS</div>
            <p className="m-0 text-sm leading-relaxed text-dark-muted">
              Akademisches Forschungsprojekt. Alle Analysen dienen ausschliesslich Informationszwecken und
              stellen keine Anlageberatung im Sinne von Art. 3 lit. c FIDLEG dar.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
