import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function safeNum(v: unknown, decimals = 2): string {
  const f = parseFloat(String(v));
  return isNaN(f) ? "–" : f.toFixed(decimals);
}

export function upsideClass(v: number | null | undefined): string {
  if (v == null) return "text-muted";
  return v > 0 ? "text-positive" : v < 0 ? "text-negative" : "text-ink";
}

export function upsideLabel(v: number | null | undefined): string {
  if (v == null) return "–";
  return `${v > 0 ? "+" : ""}${v.toFixed(1)} %`;
}

/** "ÜBERGEWICHTEN" → "Übergewichten" (Darstellung im Serif-Stil des Entwurfs). */
export function recLabel(rec: string): string {
  if (!rec || rec === "-") return "–";
  return rec.charAt(0) + rec.slice(1).toLowerCase();
}

/** Position der Empfehlung auf der 5er-Skala (0 = Verkaufen … 4 = Kaufen). */
export function recStep(rec: string): number | null {
  const r = rec.toUpperCase();
  if (r.startsWith("KAUF")) return 4;
  if (r.startsWith("ÜBER")) return 3;
  if (r.startsWith("HALT")) return 2;
  if (r.startsWith("UNTER")) return 1;
  if (r.startsWith("VERK")) return 0;
  return null;
}

/** Conviction "hoch|mittel|niedrig" → gefüllte Balken (von 3). */
export function convictionBars(c: string): number {
  const l = (c || "").toLowerCase();
  if (l.includes("hoch")) return 3;
  if (l.includes("mittel")) return 2;
  if (l.includes("niedrig")) return 1;
  return 0;
}

export function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}
