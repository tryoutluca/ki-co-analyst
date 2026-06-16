"use client";

function ampelIcon(signal: string) {
  const s = signal.toLowerCase();
  if (s.includes("positiv") || s.includes("tailwind")) return "🟢";
  if (s.includes("negativ") || s.includes("headwind")) return "🔴";
  return "🟡";
}

export default function TabMemo({ data }: { data: Record<string, unknown> }) {
  const investmentCase  = (data.investment_case  as unknown[]) ?? [];
  const macroAmpel      = (data.macro_ampel      as unknown[]) ?? [];
  const sources         = (data.sources          as string[])  ?? [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">

      {/* Left: 3/5 */}
      <div className="lg:col-span-3 space-y-6">
        <section>
          <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                         border-b border-slate-100 pb-2">
            Unternehmensbeschreibung
          </h3>
          <p className="text-sm text-slate-700 leading-relaxed">
            {String(data.company_description ?? "-")}
          </p>
        </section>

        <section>
          <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                         border-b border-slate-100 pb-2">
            Investment Case
          </h3>
          <div className="space-y-2">
            {investmentCase.map((item, i) => {
              const d = item as Record<string, string>;
              return (
                <div key={i}
                     className="pl-3 border-l-2 border-amber-300 py-1 text-sm text-slate-700 leading-relaxed">
                  {d.point ?? String(item)}
                  {d.source && (
                    <span className="block text-xs text-slate-400 mt-0.5">{d.source}</span>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                         border-b border-slate-100 pb-2">
            Finale Begründung
          </h3>
          <p className="text-sm text-slate-700 leading-relaxed bg-slate-50 rounded-lg p-4">
            {String(data.final_reasoning ?? "-")}
          </p>
        </section>
      </div>

      {/* Right: 2/5 */}
      <div className="lg:col-span-2 space-y-6">
        <section>
          <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                         border-b border-slate-100 pb-2">
            Makro-Ampel
          </h3>
          <div className="space-y-2">
            {macroAmpel.map((amp, i) => {
              const a = amp as Record<string, string>;
              const icon = ampelIcon(a.signal ?? "");
              const bg = a.signal?.toLowerCase().includes("positiv") ? "bg-emerald-50 border-emerald-200"
                       : a.signal?.toLowerCase().includes("negativ") ? "bg-red-50 border-red-200"
                       : "bg-amber-50 border-amber-200";
              return (
                <div key={i} className={`flex gap-3 p-3 rounded-lg border ${bg}`}>
                  <span className="text-base flex-shrink-0">{icon}</span>
                  <div>
                    <div className="text-xs font-semibold text-slate-700">{a.category}</div>
                    <div className="text-xs text-slate-600 mt-0.5">{a.key_point}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                         border-b border-slate-100 pb-2">
            Advocatus Diaboli
          </h3>
          <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800 leading-relaxed">
            {String(data.advocatus_diaboli_summary ?? "-")}
          </div>
        </section>

        {sources.length > 0 && (
          <section>
            <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                           border-b border-slate-100 pb-2">
              Quellen
            </h3>
            <div className="space-y-1">
              {sources.map((s, i) => (
                <div key={i} className="text-xs text-slate-500">• {s}</div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
