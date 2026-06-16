import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function safeNum(v: unknown, decimals = 2): string {
  const f = parseFloat(String(v));
  return isNaN(f) ? "-" : f.toFixed(decimals);
}

export function upsideClass(v: number | null | undefined): string {
  if (v == null) return "";
  return v > 0 ? "text-emerald-600" : "text-red-600";
}

export function upsideLabel(v: number | null | undefined): string {
  if (v == null) return "-";
  const abs = Math.abs(v).toFixed(1);
  return v > 0 ? `▲ +${abs}%` : `▼ ${v.toFixed(1)}%`;
}

export function recColor(rec: string): string {
  const r = rec.toUpperCase();
  if (r.includes("KAUF") || r.includes("ÜBER")) return "bg-emerald-100 text-emerald-700 border-emerald-200";
  if (r.includes("VERK") || r.includes("UNTER")) return "bg-red-100 text-red-700 border-red-200";
  return "bg-amber-100 text-amber-700 border-amber-200";
}

export function scoreColor(s: number | null | undefined): string {
  if (s == null) return "text-slate-400";
  if (s >= 7) return "text-emerald-600";
  if (s >= 5) return "text-amber-500";
  return "text-red-600";
}

export function convictionStars(c: string): string {
  const l = c.toLowerCase();
  if (l.includes("hoch")) return "★★★";
  if (l.includes("mittel")) return "★★☆";
  return "★☆☆";
}
