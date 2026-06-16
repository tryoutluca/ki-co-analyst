"use client";

import { useState } from "react";
import { changePassword } from "@/lib/api";
import { getUsername } from "@/lib/auth";
import { CheckCircle, AlertCircle } from "lucide-react";

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-serif text-lg font-semibold text-slate-800 border-b border-slate-200 pb-2 mb-5">
      {children}
    </h2>
  );
}

export default function SettingsPage() {
  const [oldPw,   setOldPw]   = useState("");
  const [newPw,   setNewPw]   = useState("");
  const [newPw2,  setNewPw2]  = useState("");
  const [msg,     setMsg]     = useState<{ ok: boolean; text: string } | null>(null);
  const [loading, setLoading] = useState(false);

  async function handlePwChange(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);
    if (newPw !== newPw2) { setMsg({ ok: false, text: "Passwörter stimmen nicht überein." }); return; }
    if (newPw.length < 8) { setMsg({ ok: false, text: "Mindestens 8 Zeichen." }); return; }
    setLoading(true);
    try {
      await changePassword(oldPw, newPw);
      setMsg({ ok: true, text: "Passwort erfolgreich geändert." });
      setOldPw(""); setNewPw(""); setNewPw2("");
    } catch {
      setMsg({ ok: false, text: "Aktuelles Passwort falsch oder Server-Fehler." });
    } finally {
      setLoading(false);
    }
  }

  const username = typeof window !== "undefined" ? getUsername() : "";

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="font-serif text-2xl font-bold text-slate-800 mb-8">Einstellungen</h1>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

        {/* Passwort */}
        <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
          <SectionHead>Passwort ändern</SectionHead>
          <form onSubmit={handlePwChange} className="space-y-4">
            {[
              { label: "Aktuelles Passwort", val: oldPw, set: setOldPw, auto: "current-password" },
              { label: "Neues Passwort",      val: newPw, set: setNewPw, auto: "new-password" },
              { label: "Wiederholen",          val: newPw2, set: setNewPw2, auto: "new-password" },
            ].map(({ label, val, set, auto }) => (
              <div key={label}>
                <label className="block text-xs font-semibold text-slate-500 mb-1.5">{label}</label>
                <input
                  type="password"
                  value={val}
                  onChange={e => set(e.target.value)}
                  autoComplete={auto}
                  required
                  className="w-full px-3 py-2.5 border border-slate-200 rounded-lg text-sm
                             focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100
                             bg-slate-50"
                />
              </div>
            ))}

            {msg && (
              <div className={`flex items-center gap-2 p-3 rounded-lg text-sm
                ${msg.ok ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                          : "bg-red-50 text-red-700 border border-red-200"}`}>
                {msg.ok ? <CheckCircle size={15} /> : <AlertCircle size={15} />}
                {msg.text}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg font-semibold text-sm text-white
                         transition-all disabled:opacity-50"
              style={{ background: "#0a1628" }}>
              {loading ? "Wird gespeichert…" : "Passwort aktualisieren"}
            </button>
          </form>
        </div>

        {/* System-Info */}
        <div className="space-y-5">
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6">
            <SectionHead>System-Information</SectionHead>
            <div className="space-y-3 text-sm">
              {[
                { label: "Angemeldeter Nutzer", val: username },
                { label: "Analyse-Modell",      val: "Claude Sonnet 4.6" },
                { label: "Classifier/Tools",    val: "GPT-5.4-mini" },
                { label: "Peer-Daten",          val: "Yahoo Finance · Finnhub · Tavily" },
                { label: "Frontend",            val: "Next.js 15 · Tailwind CSS" },
                { label: "Backend",             val: "FastAPI · LangGraph · Python 3.12" },
              ].map(({ label, val }) => (
                <div key={label} className="flex justify-between items-center py-2 border-b border-slate-50">
                  <span className="text-slate-500">{label}</span>
                  <span className="font-medium text-slate-700">{val}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
            <strong>Rechtlicher Hinweis:</strong> Dieses Tool ist ein akademisches Forschungsprojekt.
            Alle Analysen dienen ausschliesslich Informationszwecken und stellen keine Anlageberatung
            im Sinne von Art. 3 lit. c FIDLEG dar.
          </div>
        </div>
      </div>
    </div>
  );
}
