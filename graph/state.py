from typing import TypedDict, Optional
from langgraph.graph.message import add_messages


class AnalysisState(TypedDict):
    """
    Single Source of Truth für den gesamten Analyseprozess.
    Jeder Agent liest aus diesem State und schreibt zurück.
    """
    # ── Input ────────────────────────────────────────────────
    ticker:              str
    company_name:        str

    # ── Agent Outputs ────────────────────────────────────────
    fundamental_output:  Optional[dict]
    news_output:         Optional[dict]
    risk_output:         Optional[dict]

    # ── Retry / Self-Correction ──────────────────────────────
    fundamental_retry_count:  int        # max 2
    news_retry_count:         int        # max 2
    retry_reason:             str

    # ── IR-RAG Cache (teure Extraktion nur einmal pro Analyse-Lauf) ──
    ir_analysis_cache:        Optional[dict]

    # ── Fundamental-Rohdaten-Cache (yfinance/Finnhub/MultiplesEngine/DCF/
    # Peer-Comparison nur einmal pro Analyse-Lauf holen — Retry/Kritik-Runden
    # korrigieren die LLM-Interpretation, nicht die zugrundeliegenden Fakten) ──
    fundamental_data_cache:   Optional[dict]

    # ── Qualität ─────────────────────────────────────────────
    quality_checks:      Optional[list]
    data_consistency_score: Optional[int]

    # ── Final Output ─────────────────────────────────────────
    final_memo:          Optional[dict]

    # ── Metadaten ────────────────────────────────────────────
    analysis_started_at: Optional[str]
    analysis_duration_s: Optional[float]
    routing_log:         list   # dokumentiert jeden Routing-Entscheid

    # ── Corporate Actions / Anomalie-Erkennung ───────────────
    anomaly_flags:             Optional[list]  # detect_structural_anomalies() output
    structural_context:        Optional[str]   # Ergebnis corporate_actions_node
    corporate_actions_checked: Optional[bool]  # ob corp_actions_node gelaufen ist

    # ── Senior-Analyst Review (Supervisor Feedback Loop) ─────
    supervisor_critique:        Optional[str]  # konkretes Feedback-Text
    supervisor_critique_target: Optional[str]  # "fundamental" | "news" | "risk"
    supervisor_review_action:   Optional[str]  # "approve" | "request_critique"
    supervisor_rounds:          int            # Anzahl Critique-Runden (max 2)

    # ── Phase 1: Business-Model-Classifier ───────────────────
    business_model_classification: Optional[dict]

    # ── Phase 1: Confidence Scores pro Agent ─────────────────
    agent_confidence_scores: Optional[dict]
    # Struktur: {"fundamental": float, "news": float, "risk": float}

    # ── Phase 2: Makro-Estimate-Revision ─────────────────────
    # Deterministisch berechnete Revision der Forward-Estimates basierend
    # auf den estimate_adjustments des News-Agenten.
    revised_estimates: Optional[dict]
    # Struktur:
    # {
    #   "adjustments_applied": [ {driver, affected_metric, applied_delta_pct, ...} ],
    #   "revenue_delta_pct":   float,   # kumulierter Netto-Effekt auf Umsatz FY+1
    #   "eps_delta_pct":       float,   # kumulierter Netto-Effekt auf EPS FY+1
    #   "indicative_fair_value_adjusted": float | None,
    #   "summary": str,
    # }

    # ── Forward-Estimate-Agent (Wachstums-Projektion) ────────
    # Das Herzstück: hergeleitete Forward-Estimates aus einer Wachstums-These
    # (Sektor-Nachfrage, Thematic, Makro, Unternehmensposition), NICHT aus dem
    # Median der Vergangenheit. Bestimmt direkt das 12-Monats-Kursziel.
    forward_estimates: Optional[dict]

    # ── Phase 3: Thematic-Agent (4. Junior) ──────────────────
    # Strukturelle Megatrends + ihr quantifizierter Beitrag zu den
    # Forward-Wachstumsraten. Speist thematic_context in den Forward-Agent.
    thematic_analysis: Optional[dict]

    # ── Phase 4: Optionality-Sub-Agent ───────────────────────
    # Real-Options-Bewertung für Pre-Revenue/Deep-Tech (nur bei
    # optionality_play). Cash-Runway + TAM×Adoption + Szenario-Pfade.
    optionality_analysis: Optional[dict]

    # ── Perioden-Qualität / Quarterly Routing ────────────────
    # QuarterlySignal.to_dict() — darf AUSSCHLIESSLICH in Forward-Estimates
    # (E-Spalten) einfliessen, nie in Actuals (A-Spalten) oder MultiplesEngine.
    quarterly_signal: Optional[dict]
