/** Gemeinsame Bausteine der Memo-Ansicht im Stil des Entwurfs. */

export type Memo = Record<string, unknown>;

export function asList<T = Record<string, unknown>>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

export function asObj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

export function str(v: unknown, fallback = ""): string {
  return v == null || v === "" ? fallback : String(v);
}

/** Text aus einem Listeneintrag, der laut Schema ein String sein sollte, vom LLM
 *  aber oft als Objekt geliefert wird (z.B. key_risks als {description, time_horizon, …}).
 *  Verhindert "Objects are not valid as a React child". */
export function textOf(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  const o = asObj(v);
  if (o) {
    for (const k of ["description", "point", "text", "argument", "key_point", "risk", "item", "name", "title"]) {
      if (typeof o[k] === "string" && o[k]) return o[k] as string;
    }
    return Object.values(o).filter(x => typeof x === "string").join(" · ");
  }
  return Array.isArray(v) ? v.map(textOf).join(", ") : String(v);
}

export function num(v: unknown): number | null {
  const f = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(f) ? f : null;
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap justify-between items-baseline gap-3">
      <h2 className="m-0 font-display font-normal text-[34px] leading-tight">{children}</h2>
      {aside && <div className="label-mono">{aside}</div>}
    </div>
  );
}

export function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`bg-card border border-line ${className}`}>{children}</section>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="m-0 text-sm text-muted">{children}</p>;
}

/** Signalfarbe für positiv/neutral/negativ bzw. tailwind/headwind. */
export function signalTone(s: string): { dot: string; text: string } {
  const l = s.toLowerCase();
  if (/(positiv|tailwind|rückenwind)/.test(l)) return { dot: "#1E6B45", text: "text-positive" };
  if (/(negativ|headwind|gegenwind)/.test(l)) return { dot: "#9B2C2C", text: "text-negative" };
  return { dot: "#B08D3C", text: "text-gold-text" };
}
