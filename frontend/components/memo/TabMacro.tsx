"use client";

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                   border-b border-slate-100 pb-2">{children}</h3>
  );
}

export default function TabMacro({ data }: { data: Record<string, unknown> }) {
  const ampel    = (data.macro_ampel        as Record<string, string>[]) ?? [];
  const checklist = (data.monitoring_checklist as string[])              ?? [];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

      <div>
        <SectionHead>Makro-Ampel</SectionHead>
        <div className="space-y-2.5">
          {ampel.map((a, i) => {
            const s   = a.signal?.toLowerCase() ?? "";
            const icon = s.includes("positiv") ? "🟢" : s.includes("negativ") ? "🔴" : "🟡";
            const bg   = s.includes("positiv") ? "bg-emerald-50 border-emerald-200"
                       : s.includes("negativ") ? "bg-red-50 border-red-200"
                       : "bg-amber-50 border-amber-200";
            return (
              <div key={i} className={`p-3.5 rounded-xl border ${bg}`}>
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-sm text-slate-800">
                    {icon} {a.category}
                  </span>
                  <span className="text-xs text-slate-400 uppercase tracking-wide">{a.signal}</span>
                </div>
                <p className="text-sm text-slate-600 leading-relaxed">{a.key_point}</p>
              </div>
            );
          })}
          {ampel.length === 0 && (
            <p className="text-sm text-slate-400">Keine Makro-Daten verfügbar.</p>
          )}
        </div>
      </div>

      <div>
        <SectionHead>Monitoring-Checkliste</SectionHead>
        <ul className="space-y-2">
          {checklist.map((item, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm text-slate-700 py-1.5
                                   border-b border-slate-50 last:border-0">
              <span className="flex-shrink-0 mt-0.5 text-amber-400">□</span>
              {item}
            </li>
          ))}
          {checklist.length === 0 && (
            <p className="text-sm text-slate-400">Keine Checkliste verfügbar.</p>
          )}
        </ul>
      </div>
    </div>
  );
}
