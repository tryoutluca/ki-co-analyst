from datetime import datetime
from langgraph.graph import StateGraph, END

from graph.state import AnalysisState
from graph.nodes import (
    classifier_node,
    fundamental_node,
    anomaly_check_node,
    corporate_actions_node,
    news_node,
    estimate_revision_node,
    thematic_node,
    optionality_node,
    forward_estimate_node,
    risk_node,
    quality_node,
    supervisor_review_node,
    update_supervisor_round,
    fundamental_critique_node,
    news_critique_node,
    risk_critique_node,
    supervisor_node,
)
from graph.edges import (
    route_after_fundamental,
    route_after_anomaly_check,
    route_after_news,
    route_after_supervisor_review,
    update_fundamental_retry,
    update_news_retry,
)


def build_analysis_graph():
    """
    Erstellt und kompiliert den LangGraph StateGraph.

    Topologie:
      START → fundamental → [routing] → anomaly_check → [routing]
            → corporate_actions (optional) → news → [routing] → risk
            → quality → supervisor_review → [routing]
            → supervisor → END

    Retry-Loops:
      fundamental → update_fund_retry → fundamental  (max 2×)
      news        → update_news_retry → news          (max 1×)

    Senior-Analyst Review Loop (max 1×):
      supervisor_review → update_supervisor_round
        → fundamental_critique → supervisor  (wenn Fundamental-Kritik)
        → news_critique        → supervisor  (wenn News-Kritik)
        → risk_critique        → supervisor  (wenn Risk-Kritik)
    """
    graph = StateGraph(AnalysisState)

    # ── Bestehende Knoten ────────────────────────────────────────────────────
    graph.add_node("classifier",        classifier_node)
    graph.add_node("fundamental",       fundamental_node)
    graph.add_node("update_fund_retry", update_fundamental_retry)
    graph.add_node("news",              news_node)
    graph.add_node("update_news_retry", update_news_retry)
    graph.add_node("estimate_revision", estimate_revision_node)
    graph.add_node("thematic",          thematic_node)
    graph.add_node("optionality",       optionality_node)
    graph.add_node("forward_estimate",  forward_estimate_node)
    graph.add_node("risk",              risk_node)
    graph.add_node("quality",           quality_node)
    graph.add_node("supervisor",        supervisor_node)

    # ── Neue Knoten ──────────────────────────────────────────────────────────
    graph.add_node("anomaly_check",         anomaly_check_node)
    graph.add_node("corporate_actions",     corporate_actions_node)
    graph.add_node("supervisor_review",     supervisor_review_node)
    graph.add_node("update_supervisor_round", update_supervisor_round)
    graph.add_node("fundamental_critique",  fundamental_critique_node)
    graph.add_node("news_critique",         news_critique_node)
    graph.add_node("risk_critique",         risk_critique_node)

    # ── Entry Point: Phase 1 Classifier läuft VOR Fundamental ───────────────
    graph.set_entry_point("classifier")
    graph.add_edge("classifier", "fundamental")

    # ── Fundamental → Anomalie-Check ────────────────────────────────────────
    graph.add_conditional_edges(
        "fundamental",
        route_after_fundamental,
        {
            "proceed_news":              "anomaly_check",
            "proceed_news_with_warning": "anomaly_check",
            "retry_fundamental":         "update_fund_retry",
        },
    )
    graph.add_edge("update_fund_retry", "fundamental")

    # ── Anomalie-Check → Corporate Actions oder News ─────────────────────────
    graph.add_conditional_edges(
        "anomaly_check",
        route_after_anomaly_check,
        {
            "check_corporate_actions": "corporate_actions",
            "proceed_news":            "news",
        },
    )
    graph.add_edge("corporate_actions", "news")

    # ── News → Estimate-Revision (Phase 2) → Risk ────────────────────────────
    graph.add_conditional_edges(
        "news",
        route_after_news,
        {
            "proceed_risk":              "estimate_revision",
            "proceed_risk_with_warning": "estimate_revision",
            "retry_news":                "update_news_retry",
        },
    )
    graph.add_edge("update_news_retry", "news")
    graph.add_edge("estimate_revision", "thematic")
    graph.add_edge("thematic", "optionality")
    graph.add_edge("optionality", "forward_estimate")
    graph.add_edge("forward_estimate", "risk")

    # ── Risk → Quality → Senior Review ──────────────────────────────────────
    graph.add_edge("risk",              "quality")
    graph.add_edge("quality",           "supervisor_review")

    # ── Senior Review → Synthese oder Critique ───────────────────────────────
    graph.add_conditional_edges(
        "supervisor_review",
        route_after_supervisor_review,
        {
            "proceed_synthesis":  "supervisor",
            "critique_fundamental": "update_supervisor_round",
            "critique_news":        "update_supervisor_round",
            "critique_risk":        "update_supervisor_round",
        },
    )

    # update_supervisor_round weiß welchen Agenten treffen via supervisor_critique_target
    graph.add_conditional_edges(
        "update_supervisor_round",
        lambda s: s.get("supervisor_critique_target", "fundamental"),
        {
            "fundamental": "fundamental_critique",
            "news":        "news_critique",
            "risk":        "risk_critique",
        },
    )

    # Critique-Knoten → direkt zur finalen Synthese (kein weiterer Review)
    graph.add_edge("fundamental_critique", "supervisor")
    graph.add_edge("news_critique",        "supervisor")
    graph.add_edge("risk_critique",        "supervisor")

    graph.add_edge("supervisor", END)

    return graph.compile()


def run_analysis(ticker: str) -> dict:
    """
    Führt die vollständige Analyse via LangGraph aus.
    """
    compiled = build_analysis_graph()

    initial_state: AnalysisState = {
        "ticker":                   ticker.upper().strip(),
        "company_name":             ticker.upper().strip(),
        "fundamental_output":       None,
        "news_output":              None,
        "risk_output":              None,
        "fundamental_retry_count":  0,
        "news_retry_count":         0,
        "retry_reason":             "",
        "ir_analysis_cache":        None,
        "fundamental_data_cache":   None,
        "quality_checks":           None,
        "data_consistency_score":   None,
        "final_memo":               None,
        "analysis_started_at":      datetime.now().isoformat(),
        "analysis_duration_s":      None,
        "routing_log":              [],
        # Neue Felder
        "anomaly_flags":             None,
        "structural_context":        None,
        "corporate_actions_checked": False,
        "supervisor_critique":        None,
        "supervisor_critique_target": None,
        "supervisor_review_action":   None,
        "supervisor_rounds":          0,
        # Phase 1: Classifier + Confidence
        "business_model_classification": None,
        "agent_confidence_scores":       None,
        # Phase 2: Makro-Estimate-Revision
        "revised_estimates":             None,
        # Forward-Estimate-Agent (Wachstums-Projektion)
        "forward_estimates":             None,
        # Phase 3: Thematic-Agent
        "thematic_analysis":             None,
        # Phase 4: Optionality-Sub-Agent
        "optionality_analysis":          None,
        # Perioden-Qualität / Quarterly Routing
        "quarterly_signal":              None,
    }

    print(f"\n{'='*60}")
    print(f"KI-Co-Analyst — Analyse: {ticker}")
    print(f"{'='*60}")

    start_time = datetime.now()
    final_state = compiled.invoke(initial_state)
    duration = (datetime.now() - start_time).total_seconds()

    print(f"\n{'='*60}")
    print("\n[Routing-Log]:")
    for entry in final_state.get("routing_log", []):
        print(f"  {entry}")

    memo = final_state.get("final_memo") or {}
    if isinstance(memo, dict):
        memo["analysis_duration_s"] = round(duration, 1)
        memo["routing_log"] = final_state.get("routing_log", [])

    rec  = memo.get("final_recommendation", "-")
    conv = memo.get("conviction_level", "-")
    print(f"✓ ANALYSE ABGESCHLOSSEN in {duration:.1f}s")
    print(f"  Empfehlung: {rec} | Conviction: {conv}")
    print(f"{'='*60}\n")

    return memo
