"use client";

import { scoreColor } from "@/lib/utils";

export default function TabQuality({ data }: { data: Record<string, unknown> }) {
  const checks = (data.quality_checks as Record<string, string>[]) ?? [];
  const score  = data.data_consistency_score as number | undefined;
  const notes  = String(data.consistency_notes ?? "");

  const ICON: Record<string, string> = {
    bestanden:      "✅",
    Warnung:        "⚠️",
    fehlgeschlagen: "❌",
  };
  const BG: Record<string, string> = {
    bestanden:      "bg-emerald-50 border-emerald-200",
    Warnung:        "bg-amber-50 border-amber-200",
    fehlgeschlagen: "bg-red-50 border-red-200",
  };

  const pass = checks.filter(c => c.result === "bestanden").length;
  const warn = checks.filter(c => c.result === "Warnung").length;
  const fail = checks.filter(c => c.result === "fehlgeschlagen").length;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

      {/* Checks list */}
      <div className="lg:col-span-2 space-y-2">
        <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                       border-b border-slate-100 pb-2">Qualitätschecks</h3>
        {checks.map((c, i) => (
          <div key={i}
               className={`p-3.5 rounded-lg border ${BG[c.result] ?? "bg-slate-50 border-slate-200"}`}>
            <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
              <span>{ICON[c.result] ?? "ℹ️"}</span>
              {c.check}
            </div>
            {c.comment && (
              <div className="text-xs text-slate-500 mt-1 pl-6">{c.comment}</div>
            )}
          </div>
        ))}
        {checks.length === 0 && (
          <p className="text-sm text-slate-400">Keine Qualitätschecks vorhanden.</p>
        )}
      </div>

      {/* Score + Summary */}
      <div className="space-y-5">
        <div className="bg-slate-50 rounded-xl border border-slate-200 p-6 text-center">
          <div className="text-xs text-slate-400 uppercase tracking-widest mb-2">
            Gesamt-Score
          </div>
          <div className={`font-serif text-6xl font-bold leading-none ${scoreColor(score)}`}>
            {score ?? "-"}
          </div>
          <div className="text-sm text-slate-400 mt-1">von 10 Punkten</div>

          <div className="grid grid-cols-3 gap-2 mt-5">
            <div className="text-center">
              <div className="text-xl font-bold text-emerald-600">{pass}</div>
              <div className="text-xs text-slate-400">OK</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-bold text-amber-500">{warn}</div>
              <div className="text-xs text-slate-400">Warn.</div>
            </div>
            <div className="text-center">
              <div className="text-xl font-bold text-red-600">{fail}</div>
              <div className="text-xs text-slate-400">Fehler</div>
            </div>
          </div>
        </div>

        {notes && (
          <div className="bg-slate-50 rounded-xl border border-slate-200 p-4 text-sm text-slate-600 leading-relaxed">
            {notes}
          </div>
        )}
      </div>
    </div>
  );
}
