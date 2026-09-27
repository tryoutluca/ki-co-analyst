"use client";

import { type Memo, asList, str, textOf, SectionTitle, Panel, Empty } from "./ui";

export default function TabMemo({ d }: { d: Memo }) {
  const cases   = asList(d.investment_case);
  const sources = asList<unknown>(d.sources).map(textOf).filter(Boolean);
  const reasoning = str(d.final_reasoning).split("│").map(s => s.trim()).filter(Boolean);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_400px] gap-10">
      <div className="flex flex-col gap-10 min-w-0">
        <section className="flex flex-col gap-3">
          <div className="eyebrow plain">UNTERNEHMEN</div>
          <p className="m-0 text-[17px] leading-relaxed text-ink-2 max-w-[860px]">{str(d.company_description, "–")}</p>
        </section>

        <section className="flex flex-col gap-4">
          <SectionTitle>Investment Case</SectionTitle>
          {cases.length ? (
            <ol className="m-0 p-0 list-none border-t border-ink">
              {cases.map((c, i) => (
                <li key={i} className="grid grid-cols-[48px_minmax(0,1fr)] gap-4 py-4 border-b border-line-2">
                  <span className="font-mono text-[13px] text-gold-dark">{String(i + 1).padStart(2, "0")}</span>
                  <div className="flex flex-col gap-1">
                    <span className="text-[15px] leading-relaxed text-ink-2">{textOf(c)}</span>
                    {str(c.source) && <span className="font-mono text-[10px] tracking-[0.08em] text-muted-2">{str(c.source).toUpperCase()}</span>}
                  </div>
                </li>
              ))}
            </ol>
          ) : <Empty>Kein Investment Case vorhanden.</Empty>}
        </section>

        <section className="flex flex-col gap-4">
          <SectionTitle>Finale Begründung</SectionTitle>
          <div className="flex flex-col gap-3">
            {reasoning.length ? reasoning.map((r, i) => (
              <p key={i} className="m-0 text-[15px] leading-relaxed text-ink-2">{r}</p>
            )) : <Empty>–</Empty>}
          </div>
        </section>
      </div>

      <aside className="flex flex-col gap-6 min-w-0">
        <section className="bg-ink text-cream-2 p-6 flex flex-col gap-3">
          <div className="font-mono text-[11px] tracking-[0.12em] text-gold-dim">ADVOCATUS DIABOLI</div>
          <p className="m-0 font-display text-xl leading-snug">{str(d.advocatus_diaboli_summary, "–")}</p>
        </section>
        <Panel className="p-6 flex flex-col gap-3">
          <h2 className="m-0 font-display font-normal text-[28px]">Quellen</h2>
          {sources.length ? (
            <ul className="m-0 p-0 list-none">
              {sources.map((s, i) => (
                <li key={i} className="py-2 border-t border-line-2 text-sm text-ink-2 break-words">{s}</li>
              ))}
            </ul>
          ) : <Empty>Keine Quellen angegeben.</Empty>}
        </Panel>
      </aside>
    </div>
  );
}
