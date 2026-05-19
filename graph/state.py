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
