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
