"use client";

/**
 * LangGraph des KI-Co-Analysten (graph/graph.py) als Diagramm — aus dem
 * Homepage-Entwurf übernommen. Scroll-gesteuert: Ein Datenpaket folgt dem
 * Ablauf im gleichen Tempo, in dem man durch den Abschnitt scrollt; der
 * erreichte Knoten leuchtet auf und kommt dem Betrachter entgegen (skaliert).
 */
import { useEffect, useRef } from "react";

const MONO = "var(--font-jetbrains), monospace";
const SERIF = "var(--font-instrument), Georgia, serif";
const SANS = "var(--font-hanken), system-ui, sans-serif";

// Hauptablauf in Reihenfolge — Pfad des Datenpakets
const TRACE = "M16 120 L 1180 120 L 1180 262 L 20 262 L 20 340 L 1070 340 L 1070 470 L 20 470 L 20 560 L 1038 560";
const TAIL = 180;          // Länge des Leuchtschweifs (px entlang des Pfads)
const LIFT = 0.12;         // max. Vergrösserung des aktiven Knotens
const REACH = 190;         // Einflussbereich des Pakets um die Knotenmitte (px)

type Variant = "main" | "entry" | "optional" | "critique" | "supervisor" | "memo";

interface Node {
  id: string;
  x: number; y: number; w: number; h: number;
  title: string;
  tag?: string;
  variant: Variant;
  titleSize?: number;
  at?: number;   // Distanz entlang TRACE, an der das Paket die Box erreicht
}

const NODES: Node[] = [
  { id: "classifier",  x: 45,   y: 94,  w: 150, h: 52,  title: "Classifier",        tag: "GESCHÄFTSMODELL",        variant: "entry", at: 29 },
  { id: "fundamental", x: 255,  y: 94,  w: 150, h: 52,  title: "Fundamental",       tag: "KENNZAHLEN · BEWERTUNG", variant: "main",  at: 239 },
  { id: "anomaly",     x: 465,  y: 94,  w: 150, h: 52,  title: "Anomalie-Check",    tag: "PLAUSIBILITÄT",          variant: "main",  at: 449 },
  { id: "corporate",   x: 675,  y: 179, w: 150, h: 52,  title: "Corporate Actions", tag: "OPTIONAL",               variant: "optional" },
  { id: "news",        x: 885,  y: 94,  w: 150, h: 52,  title: "News",              tag: "NACHRICHTENLAGE",        variant: "main",  at: 869 },
  { id: "estrev",      x: 45,   y: 314, w: 150, h: 52,  title: "Estimate Revision", tag: "MAKRO-REVISION",         variant: "main",  at: 2569 },
  { id: "thematic",    x: 235,  y: 314, w: 150, h: 52,  title: "Thematic",          tag: "THEMEN · TRENDS",        variant: "main",  at: 2759 },
  { id: "optionality", x: 425,  y: 314, w: 150, h: 52,  title: "Optionality",       tag: "PRE-REVENUE",            variant: "main",  at: 2949 },
  { id: "forward",     x: 615,  y: 314, w: 150, h: 52,  title: "Forward Estimate",  tag: "WACHSTUM",               variant: "main",  at: 3139 },
  { id: "risk",        x: 805,  y: 314, w: 150, h: 52,  title: "Risk",              tag: "RISIKOPROFIL",           variant: "main",  at: 3329 },
  { id: "quality",     x: 995,  y: 314, w: 150, h: 52,  title: "Quality",           tag: "DATENKONSISTENZ",        variant: "main",  at: 3519 },
  { id: "senior",      x: 45,   y: 528, w: 170, h: 64,  title: "Senior Review",     tag: "PRÜFT ALLE ERGEBNISSE",  variant: "entry", titleSize: 21, at: 4889 },
  { id: "crit-f",      x: 430,  y: 598, w: 150, h: 44,  title: "Fundamental-Kritik", variant: "critique", titleSize: 17 },
  { id: "crit-n",      x: 430,  y: 668, w: 150, h: 44,  title: "News-Kritik",       variant: "critique", titleSize: 17 },
  { id: "crit-r",      x: 430,  y: 738, w: 150, h: 44,  title: "Risk-Kritik",       variant: "critique", titleSize: 17 },
  { id: "supervisor",  x: 830,  y: 528, w: 170, h: 64,  title: "Supervisor",        tag: "SYNTHESE",               variant: "supervisor", titleSize: 22, at: 5674 },
  { id: "memo",        x: 1040, y: 490, w: 160, h: 140, title: "Final Memo",        variant: "memo", titleSize: 24, at: 5874 },
];

function NodeBox({ n }: { n: Node }) {
  const { x, y, w, h } = n;
  const titleY = y + (n.variant === "supervisor" || n.variant === "memo" ? 34
    : n.h >= 64 || n.variant === "critique" ? 28 : 23);
  const tagY = y + (n.h >= 64 ? 50 : 41);

  if (n.variant === "supervisor") {
    return (
      <>
        <rect x={x} y={y} width={w} height={h} fill="#121417" />
        <rect x={x + 5} y={y + 5} width={w - 10} height={h - 10} fill="none" stroke="#B08D3C" strokeWidth="0.8" />
        <rect data-hit="" x={x - 3} y={y - 3} width={w + 6} height={h + 6} fill="none" stroke="#D9B45A" strokeWidth="3" filter="url(#glow)" opacity="0" />
        <text x={x + w / 2} y={titleY} textAnchor="middle" fontFamily={SERIF} fontSize={n.titleSize} fill="#F2E6C4">{n.title}</text>
        <text x={x + w / 2} y={tagY} textAnchor="middle" fontFamily={MONO} fontSize="9.5" letterSpacing="0.8" fill="#D9B45A">{n.tag}</text>
      </>
    );
  }

  const base: Record<Exclude<Variant, "supervisor">, React.SVGProps<SVGRectElement>> = {
    main:     { fill: "#FFFFFF", stroke: "#B08D3C", strokeWidth: 1.3 },
    entry:    { fill: "#FFFFFF", stroke: "#121417", strokeWidth: 1.5 },
    optional: { fill: "#F7F4EC", stroke: "#C9A24A", strokeWidth: 1.3, strokeDasharray: "5 4" },
    critique: { fill: "#F7F0DE", stroke: "#C9A24A", strokeWidth: 1.2, strokeDasharray: "5 4" },
    memo:     { fill: "#FBF6EA", stroke: "#B08D3C", strokeWidth: 1.5 },
  };

  return (
    <>
      <rect x={x} y={y} width={w} height={h} {...base[n.variant]} />
      {n.at != null && (
        <rect data-hit="" x={x - 3} y={y - 3} width={w + 6} height={h + 6}
          fill="#F2E2B2" stroke="#D9B45A" strokeWidth="3" filter="url(#glow)" opacity="0" />
      )}
      <text x={x + (n.variant === "memo" ? 18 : 14)} y={titleY} fontFamily={SERIF} fontSize={n.titleSize ?? 19} fill="#121417">{n.title}</text>
      {n.tag && (
        <text x={x + 14} y={tagY} fontFamily={MONO} fontSize="9.5" letterSpacing="0.8" fill="#6A6D72">{n.tag}</text>
      )}
      {n.variant === "memo" && (
        <>
          {["Empfehlung", "Conviction", "Routing-Log"].map((t, i) => (
            <g key={t}>
              <text x={x + 18} y={y + 66 + i * 26} fontFamily={SANS} fontSize="13" fill="#3A3D42">{t}</text>
              <rect x={x + 138} y={y + 58 + i * 26} width="6" height="6" fill="#B08D3C"
                transform={`rotate(45 ${x + 141} ${y + 61 + i * 26})`} />
            </g>
          ))}
        </>
      )}
    </>
  );
}

export default function PipelineGraph() {
  const svgRef    = useRef<SVGSVGElement>(null);
  const traceRef  = useRef<SVGPathElement>(null);
  const tailRef   = useRef<SVGPathElement>(null);
  const packetRef = useRef<SVGGElement>(null);

  useEffect(() => {
    const svg = svgRef.current, trace = traceRef.current, tail = tailRef.current, packet = packetRef.current;
    if (!svg || !trace || !tail || !packet) return;

    const length = trace.getTotalLength();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const groups = NODES
      .filter(n => n.at != null)
      .map(n => ({
        n,
        g: svg.querySelector<SVGGElement>(`[data-node="${n.id}"]`),
        // Wirkungszentrum: Mitte der Box entlang des Pfads (Final Memo: Pfadende)
        center: Math.min(n.at! + n.w / 2, length - 4),
      }));

    tail.style.strokeDasharray = `${TAIL} ${length + TAIL}`;

    let frame = 0;
    const render = () => {
      frame = 0;
      const r = svg.getBoundingClientRect();
      const vh = window.innerHeight;
      // Start, wenn der Graph 70 % in den Viewport ragt; ein voller Durchlauf
      // entspricht ~90 % der Graphenhöhe Scrollweg → Paket bewegt sich im Scroll-Tempo
      const progress = reduced ? 1 : Math.min(1, Math.max(0, (vh * 0.7 - r.top) / (r.height * 0.9)));
      const d = progress * length;

      const pt = trace.getPointAtLength(d);
      packet.setAttribute("transform", `translate(${pt.x} ${pt.y})`);
      packet.style.opacity = reduced ? "0" : "1";
      tail.style.strokeDashoffset = String(TAIL - d);

      for (const { g, center } of groups) {
        if (!g) continue;
        const peak = reduced ? 0 : Math.max(0, 1 - Math.abs(d - center) / REACH);
        const visited = d >= center;
        const hit = g.querySelector<SVGRectElement>("[data-hit]");
        if (hit) hit.setAttribute("opacity", String(Math.max(peak, visited ? 0.28 : 0)));
        g.style.transform = `scale(${1 + LIFT * peak})`;
      }
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(render); };

    render();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  // Knoten mit Paket-Station zuletzt zeichnen, damit der vergrösserte Knoten über Nachbarn liegt
  const ordered = [...NODES].sort((a, b) => (a.at != null ? 1 : 0) - (b.at != null ? 1 : 0));

  return (
    // viewBox mit 20 px Rand: der vergrösserte Knoten (Final Memo sitzt an der Kante) wird nicht abgeschnitten
    <svg ref={svgRef} viewBox="-20 -10 1240 820" className="w-full h-auto min-w-[900px]" role="img"
      aria-label="LangGraph des KI-Co-Analysten: Klassifikation und Datenbasis, Spezialisten-Agenten, Senior Review mit Kritik-Schleife und Synthese durch den Supervisor">
      <defs>
        <marker id="pa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" fill="#9A7A2E" />
        </marker>
        <marker id="pr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" fill="#8B8E93" />
        </marker>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <g fontFamily={MONO} fontSize="11" letterSpacing="1.5" fill="#7F6320">
        <text x="45" y="24">PHASE 1 · KLASSIFIKATION &amp; DATENBASIS</text>
        <text x="45" y="296">PHASE 2 · SPEZIALISTEN</text>
        <text x="45" y="506">PHASE 3 · SENIOR REVIEW &amp; SYNTHESE</text>
      </g>

      <g fill="none" stroke="#B08D3C" strokeWidth="1.3">
        <path d="M24 120 L 43 120" markerEnd="url(#pa)" />
        <path d="M195 120 L 253 120" markerEnd="url(#pa)" />
        <path d="M405 120 L 463 120" markerEnd="url(#pa)" />
        <path d="M615 120 L 883 120" markerEnd="url(#pa)" />
        <path d="M1035 120 L 1180 120 L 1180 262 L 20 262 L 20 340 L 43 340" markerEnd="url(#pa)" />
        <path d="M195 340 L 233 340" markerEnd="url(#pa)" />
        <path d="M385 340 L 423 340" markerEnd="url(#pa)" />
        <path d="M575 340 L 613 340" markerEnd="url(#pa)" />
        <path d="M765 340 L 803 340" markerEnd="url(#pa)" />
        <path d="M955 340 L 993 340" markerEnd="url(#pa)" />
        <path d="M1070 366 L 1070 470 L 20 470 L 20 560 L 43 560" markerEnd="url(#pa)" />
        <path d="M215 560 L 828 560" markerEnd="url(#pa)" />
        <path d="M1000 560 L 1038 560" markerEnd="url(#pa)" strokeWidth="2" />
      </g>
      <g fill="none" stroke="#C9A24A" strokeWidth="1.3" strokeDasharray="7 5">
        <path d="M540 146 C 540 205, 600 205, 673 205" markerEnd="url(#pa)" />
        <path d="M825 205 C 900 205, 960 200, 960 148" markerEnd="url(#pa)" />
        <path d="M130 592 L 130 690 L 286 690" markerEnd="url(#pa)" />
        <path d="M314 690 C 370 690, 370 620, 428 620" markerEnd="url(#pa)" />
        <path d="M314 690 L 428 690" markerEnd="url(#pa)" />
        <path d="M314 690 C 370 690, 370 760, 428 760" markerEnd="url(#pa)" />
        <path d="M580 620 C 760 620, 915 700, 915 594" markerEnd="url(#pa)" />
        <path d="M580 690 C 760 690, 915 720, 915 594" markerEnd="url(#pa)" />
        <path d="M580 760 C 760 760, 915 740, 915 594" markerEnd="url(#pa)" />
      </g>
      <g fill="none" stroke="#8B8E93" strokeWidth="1.2" strokeDasharray="2 4">
        <path d="M370 94 C 370 50, 290 50, 290 92" markerEnd="url(#pr)" />
        <path d="M1000 94 C 1000 50, 920 50, 920 92" markerEnd="url(#pr)" />
      </g>
      <circle cx="330" cy="61" r="4" fill="#FFFDF8" stroke="#8B8E93" />
      <circle cx="960" cy="61" r="4" fill="#FFFDF8" stroke="#8B8E93" />

      {/* Referenzpfad (unsichtbar) + Leuchtschweif hinter dem Paket */}
      <path ref={traceRef} d={TRACE} fill="none" stroke="none" />
      <path ref={tailRef} d={TRACE} fill="none" stroke="#D9B45A" strokeWidth="4" strokeLinecap="round"
        filter="url(#glow)" aria-hidden="true" style={{ strokeDashoffset: TAIL }} />

      <g fontFamily={MONO} fontSize="10" letterSpacing="1" fill="#5C5F64">
        <text x="330" y="44" textAnchor="middle">RETRY ≤ 2×</text>
        <text x="960" y="44" textAnchor="middle">RETRY ≤ 1×</text>
        <text x="750" y="112" textAnchor="middle">DIREKT</text>
        {/* links der Corporate-Actions-Box, damit das Label nicht verdeckt wird */}
        <text x="545" y="226" fill="#7F6320">BEI AUFFÄLLIGKEIT</text>
        <rect x="455" y="549" width="130" height="22" fill="#FFFDF8" stroke="none" />
        <text x="520" y="564" textAnchor="middle" fill="#7F6320">FREIGEGEBEN</text>
        <text x="140" y="650" fill="#7F6320">KRITIK</text>
        <text x="300" y="722" textAnchor="middle">RUNDE +1</text>
      </g>

      <circle cx="16" cy="120" r="7" fill="#121417" />
      <rect x="290" y="680" width="20" height="20" transform="rotate(45 300 690)" fill="#FBF6EA" stroke="#B08D3C" strokeWidth="1.3" />

      {/* Datenpaket (unter den Knoten: es "betritt" die Box, die dann aufleuchtet) */}
      <g ref={packetRef} className="pipeline-packet" aria-hidden="true" transform="translate(16 120)" style={{ opacity: 0 }}>
        <circle r="8" fill="#D9B45A" filter="url(#glow)" />
        <circle r="3.5" fill="#FFFDF8" />
      </g>

      {ordered.map(n => (
        <g key={n.id} data-node={n.id}
          style={{ transformBox: "fill-box", transformOrigin: "center", willChange: n.at != null ? "transform" : undefined }}>
          <NodeBox n={n} />
        </g>
      ))}
    </svg>
  );
}
