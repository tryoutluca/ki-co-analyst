/**
 * Pipeline-Modell des LangGraph (graph/graph.py) — einzige Quelle für
 *  - die Live-Anzeige während der Analyse (aus den Progress-Zeilen "[knoten] …")
 *  - den "Pipeline-Lauf" im fertigen Memo (aus memo.routing_log)
 *
 * Jeder Knoten schreibt beim Start "[<key>] …" nach stdout (graph/nodes.py);
 * das Backend leitet stdout als Progress an den Job weiter.
 */

export type NodeStatus = "pending" | "active" | "done" | "flag" | "skip";

export interface PipelineNode {
  key: string;          // Log-Präfix in graph/nodes.py
  name: string;
  tag: string;          // Kurzbeschreibung (Mono-Label)
  optional?: boolean;   // läuft nur unter Bedingungen
}

/** Ablauf-Reihenfolge wie in graph/graph.py. "critique" bündelt
 *  fundamental_critique / news_critique / risk_critique (max. 1 Runde). */
export const PIPELINE: PipelineNode[] = [
  { key: "classifier",        name: "Classifier",        tag: "GESCHÄFTSMODELL" },
  { key: "fundamental",       name: "Fundamental",       tag: "KENNZAHLEN · BEWERTUNG" },
  { key: "anomaly_check",     name: "Anomalie-Check",    tag: "PLAUSIBILITÄT" },
  { key: "corporate_actions", name: "Corporate Actions", tag: "OPTIONAL", optional: true },
  { key: "news",              name: "News",              tag: "NACHRICHTENLAGE" },
  { key: "estimate_revision", name: "Estimate Revision", tag: "MAKRO-REVISION" },
  { key: "thematic",          name: "Thematic",          tag: "THEMEN · TRENDS" },
  { key: "optionality",       name: "Optionality",       tag: "PRE-REVENUE", optional: true },
  { key: "forward_estimate",  name: "Forward Estimate",  tag: "WACHSTUM" },
  { key: "risk",              name: "Risk",              tag: "RISIKOPROFIL" },
  { key: "quality",           name: "Quality",           tag: "DATENKONSISTENZ" },
  { key: "supervisor_review", name: "Senior Review",     tag: "PRÜFT ALLE ERGEBNISSE" },
  { key: "critique",          name: "Kritik-Runde",      tag: "OPTIONAL", optional: true },
  { key: "supervisor",        name: "Supervisor",        tag: "SYNTHESE" },
];

const CRITIQUE_KEYS = ["fundamental_critique", "news_critique", "risk_critique", "supervisor_round"];
const TARGET_LABEL: Record<string, string> = { fundamental: "Fundamental", news: "News", risk: "Risk" };

export interface NodeState extends PipelineNode {
  status: NodeStatus;
  note: string;
}

/** "[fundamental_critique] …" → "critique"; "[news] …" → "news". */
function nodeKeyOf(line: string): string | null {
  const m = line.match(/^\s*\[([a-z_]+)\]/);
  if (!m) return null;
  const k = m[1];
  if (CRITIQUE_KEYS.includes(k)) return "critique";
  return PIPELINE.some(n => n.key === k) ? k : null;
}

function critiqueTarget(lines: string[]): string | null {
  for (const l of lines) {
    const m = l.match(/^\s*\[(fundamental|news|risk)_critique\]/) ?? l.match(/Kritik\s*→\s*(fundamental|news|risk)/i);
    if (m) return m[1].toLowerCase();
  }
  return null;
}

const BMT_LABEL: Record<string, string> = {
  mature_cashflow: "REIFER CASHFLOW",
  growth_with_revenue: "WACHSTUM",
  optionality_play: "OPTIONALITY",
  cyclical: "ZYKLISCH",
  financial_institution: "FINANZINSTITUT",
};

/** Hinweis + Status je Knoten aus seinen Log-Zeilen. */
function describe(key: string, lines: string[], target: string | null): { status: NodeStatus; note: string } {
  const text = lines.join(" ");
  const failed = /❌|⚠ Fehler/.test(text);
  if (failed) return { status: "flag", note: "FEHLER" };

  switch (key) {
    case "classifier": {
      const m = text.match(/✅\s+([a-z_]+)/);
      return { status: "done", note: m ? (BMT_LABEL[m[1]] ?? m[1].toUpperCase()) : "OK" };
    }
    case "fundamental": {
      const retries = lines.filter(l => /Wiederholung/.test(l)).length;
      return retries > 0 ? { status: "flag", note: `${retries} RETRY` } : { status: "done", note: "OK" };
    }
    case "news": {
      const retries = lines.filter(l => /Wiederholung/.test(l)).length;
      const score = text.match(/Sentiment:?\s*(\d+)\/10/);
      if (retries > 0) return { status: "flag", note: `${retries} RETRY` };
      return { status: "done", note: score ? `SENTIMENT ${score[1]}/10` : "OK" };
    }
    case "anomaly_check": {
      const m = text.match(/(\d+) Anomalie/);
      return m && Number(m[1]) > 0
        ? { status: "flag", note: `${m[1]} AUFFÄLLIGKEIT${Number(m[1]) > 1 ? "EN" : ""}` }
        : { status: "done", note: "UNAUFFÄLLIG" };
    }
    case "estimate_revision":
      return { status: "done", note: /Keine Makro-Adjustments/.test(text) ? "KEINE ANPASSUNG" : "OK" };
    case "supervisor_review":
      return target
        ? { status: "flag", note: `KRITIK → ${(TARGET_LABEL[target] ?? target).toUpperCase()}` }
        : { status: "done", note: "FREIGEGEBEN" };
    case "supervisor":
      return { status: "done", note: "SYNTHESE" };
    default:
      return { status: "done", note: "OK" };
  }
}

const SKIP_NOTE: Record<string, string> = {
  corporate_actions: "NICHT AUSGELÖST",
  optionality: "NICHT RELEVANT",
  critique: "NICHT NÖTIG",
};

/**
 * Zustand aller Knoten aus Log-Zeilen.
 * finished=false (live): letzter gestarteter Knoten = aktiv; nicht gestartete
 *   optionale Knoten gelten als übersprungen, sobald ein späterer Knoten läuft.
 * finished=true (Memo/routing_log): nicht vorhandene Knoten = übersprungen.
 */
export function pipelineState(lines: string[], finished: boolean): NodeState[] {
  const byNode = new Map<string, string[]>();
  const order: string[] = [];
  for (const line of lines) {
    const k = nodeKeyOf(line);
    if (!k) continue;
    if (!byNode.has(k)) { byNode.set(k, []); order.push(k); }
    byNode.get(k)!.push(line);
  }
  // Optionality schreibt beim Überspringen nur "⏭" ins routing_log
  const optLines = byNode.get("optionality") ?? [];
  const optionalitySkipped = optLines.some(l => l.includes("⏭"));

  const target = critiqueTarget(lines);
  const lastStarted = order[order.length - 1];
  const lastIdx = PIPELINE.findIndex(n => n.key === lastStarted);

  return PIPELINE.map((node, idx) => {
    const own = byNode.get(node.key);
    const name = node.key === "critique" && target ? `${TARGET_LABEL[target] ?? target}-Kritik` : node.name;

    if (node.key === "optionality" && optionalitySkipped) {
      return { ...node, name, status: "skip", note: SKIP_NOTE.optionality };
    }
    if (!own) {
      const passed = finished || idx < lastIdx;
      if (passed && node.optional) return { ...node, name, status: "skip", note: SKIP_NOTE[node.key] ?? "—" };
      return { ...node, name, status: "pending", note: "" };
    }
    if (!finished && node.key === lastStarted) {
      return { ...node, name, status: "active", note: "LÄUFT" };
    }
    const d = describe(node.key, own, target);
    return { ...node, name, status: d.status, note: d.note };
  });
}

export const AGENT_COUNT_LLM = 15;  // 8 Haupt- + 5 Sub- + 2 Kontroll-Agenten (Senior Review, Corporate Actions)
export const GRAPH_NODE_COUNT = 19; // Knoten in graph/graph.py inkl. Retry-/Kritik-Knoten
