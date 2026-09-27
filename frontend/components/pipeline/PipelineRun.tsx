"use client";

import { Diamond, STATUS_LABEL } from "@/components/brand/Brand";
import type { NodeState } from "@/lib/pipeline";

/** "Pipeline-Lauf": ein Eintrag pro LangGraph-Knoten mit Rauten-Status. */
export default function PipelineRun({ nodes }: { nodes: NodeState[] }) {
  return (
    <ol className="flex flex-col" aria-label="Pipeline-Lauf">
      {nodes.map(n => {
        const muted = n.status === "skip" || n.status === "pending";
        return (
          <li key={n.key} className="grid grid-cols-[18px_minmax(0,1fr)_auto] gap-3 items-center min-h-8">
            <span className="flex justify-center">
              <Diamond status={n.status} />
              <span className="sr-only">{STATUS_LABEL[n.status]}</span>
            </span>
            <span className={`text-sm ${muted ? "text-subtle" : "text-ink"} ${n.status === "active" ? "font-semibold" : ""}`}>
              {n.name}
            </span>
            <span className={`font-mono text-[10px] tracking-[0.06em] ${
              n.status === "flag" || n.status === "active" ? "text-gold-text" : muted ? "text-subtle" : "text-muted"
            }`}>
              {n.note}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
