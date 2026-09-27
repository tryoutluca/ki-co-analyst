import type { NodeStatus } from "@/lib/pipeline";

/** Rauten-Logo mit Goldpunkt aus dem Entwurf. */
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
      <rect x="4" y="4" width="14" height="14" transform="rotate(45 11 11)" fill="none" stroke="#B08D3C" strokeWidth="1.5" />
      <circle cx="11" cy="11" r="2.5" fill="#B08D3C" />
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`flex items-center gap-3 ${className}`}>
      <LogoMark />
      <span className="font-display text-[26px] leading-none tracking-[-0.01em] text-ink">KI-Co-Analyst</span>
    </span>
  );
}

/** Rauten-Statusmarker der Pipeline: gefüllt = fertig, hohl = Auffälligkeit,
 *  grau = übersprungen, pulsierend = läuft. */
export function Diamond({ status }: { status: NodeStatus }) {
  const style: Record<NodeStatus, { fill: string; line: string }> = {
    done:    { fill: "#B08D3C", line: "#B08D3C" },
    active:  { fill: "#B08D3C", line: "#B08D3C" },
    flag:    { fill: "#FFFDF8", line: "#B08D3C" },
    skip:    { fill: "transparent", line: "#C4C6C9" },
    pending: { fill: "transparent", line: "#D9CDAE" },
  };
  const s = style[status];
  return (
    <span
      aria-hidden="true"
      className={`inline-block w-[9px] h-[9px] rotate-45 box-border ${status === "active" ? "diamond-active" : ""}`}
      style={{ background: s.fill, border: `1.5px solid ${s.line}` }}
    />
  );
}

export const STATUS_LABEL: Record<NodeStatus, string> = {
  pending: "wartet", active: "läuft", done: "fertig", flag: "auffällig", skip: "übersprungen",
};
