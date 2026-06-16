"use client";

import { safeNum } from "@/lib/utils";

function SectionHead({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-bold tracking-widest uppercase text-slate-400 mb-3
                   border-b border-slate-100 pb-2">{children}</h3>
  );
}

const SC_STYLES: Record<string, { bg: string; border: string; icon: string }> = {
  "Bear Case": { bg: "bg-red-50",    border: "border-red-200",   icon: "🐻" },
  "Base Case": { bg: "bg-amber-50",  border: "border-amber-200", icon: "⚖️" },
  "Bull Case": { bg: "bg-emerald-50",border: "border-emerald-200",icon: "🐂" },
};

export default function TabRisk({ data }: { data: Record<string, unknown> }) {
  const scenarios = (data.scenarios as Record<string, unknown>[]) ?? [];
  const risks     = (data.key_risks as string[]) ?? [];
  const ckList    = (data.conviction_killers as Record<string, string>[]) ?? [];
  const opt       = data.optionality_analysis as Record<string, unknown> | undefined;
  const ccy       = String(data.currency ?? "");

  return (
    <div className="space-y-8">

      {/* Optionality */}
      {opt && (
        <div>
          <SectionHead>🎲 Optionality-Bewertung</SectionHead>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            {[
              { label: "Cash-Runway", val: `${opt.runway_months ?? "n/v"} Mt.` },
              { label: "Fairer Wert (pW)", val: `${ccy} ${safeNum(opt.probability_weighted_value)}` },
              { label: "Verwässerungsrisiko", val: String(opt.dilution_risk ?? "?").toUpperCase() },
            ].map(({ label, val }) => (
              <div key={label} className="bg-slate-50 rounded-xl border border-slate-200 p-4 text-center">
                <div className="text-xs text-slate-400 uppercase tracking-widest mb-1">{label}</div>
                <div className="font-serif text-xl font-bold text-slate-800">{val}</div>
              </div>
            ))}
          </div>
          {opt.binary_risk_warning ? (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
              ⚠️ {String(opt.binary_risk_warning)}
            </div>
          ) : null}
        </div>
      )}

      {/* Scenarios */}
      {scenarios.length > 0 && (
        <div>
          <SectionHead>Szenarien</SectionHead>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {scenarios.map((sc, i) => {
              const name = String(sc.name ?? "");
              const s    = SC_STYLES[name] ?? SC_STYLES["Base Case"];
              return (
                <div key={i} className={`rounded-xl border p-5 ${s.bg} ${s.border}`}>
                  <div className="font-bold text-sm mb-3">{s.icon} {name}</div>
                  <div className="font-serif text-2xl font-bold text-slate-800 mb-1">
                    {ccy} {safeNum(sc.price_target)}
                  </div>
                  <div className="text-xs text-slate-500 mb-3">
                    Wahrscheinlichkeit: <strong>{String(sc.probability_pct ?? "?")}%</strong>
                  </div>
                  <div className="text-xs text-slate-600 leading-relaxed mb-2">
                    <strong>Kernannahme:</strong><br />{String(sc.key_assumption ?? "")}
                  </div>
                  <div className="text-xs text-slate-500">
                    Trigger: {String(sc.trigger ?? "")}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Key Risks */}
      {risks.length > 0 && (
        <div>
          <SectionHead>Quantifizierte Risiken</SectionHead>
          <div className="space-y-2">
            {risks.map((r, i) => (
              <div key={i} className="flex items-start gap-2.5 p-3 rounded-lg
                                      bg-red-50 border border-red-100 text-sm text-red-800">
                <span className="flex-shrink-0">⚠️</span>
                {r}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Conviction Killers */}
      {ckList.length > 0 && (
        <div>
          <SectionHead>Conviction Killers</SectionHead>
          <div className="space-y-2">
            {ckList.map((ck, i) => (
              <div key={i} className="p-4 rounded-xl bg-red-50 border border-red-200">
                <div className="font-semibold text-sm text-red-800">
                  🚨 {ck.description ?? String(ck)}
                </div>
                {ck.monitoring_indicator && (
                  <div className="text-xs text-red-600 mt-1">
                    → Monitor: {ck.monitoring_indicator}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
