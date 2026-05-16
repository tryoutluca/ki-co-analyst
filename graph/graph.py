from datetime import datetime
from langgraph.graph import StateGraph, END

from graph.state import AnalysisState
from graph.nodes import (
    fundamental_node,
    news_node,
    risk_node,
    quality_node,
    supervisor_node,
)
from graph.edges import (
    route_after_fundamental,
    route_after_news,
    update_fundamental_retry,
    update_news_retry,
)


def build_analysis_graph():
    """
    Erstellt und kompiliert den LangGraph StateGraph.

    Topologie:
      START → fundamental → [routing] → news → [routing] → risk
            → quality → supervisor → END

    Retry-Loops:
      fundamental → update_fund_retry → fundamental  (max 2×)
      news        → update_news_retry → news          (max 1×)
    """
    graph = StateGraph(AnalysisState)

    graph.add_node("fundamental",       fundamental_node)
    graph.add_node("update_fund_retry", update_fundamental_retry)
    graph.add_node("news",              news_node)
    graph.add_node("update_news_retry", update_news_retry)
    graph.add_node("risk",              risk_node)
    graph.add_node("quality",           quality_node)
    graph.add_node("supervisor",        supervisor_node)

    graph.set_entry_point("fundamental")

    graph.add_conditional_edges(
        "fundamental",
        route_after_fundamental,
        {
            "proceed_news":              "news",
            "proceed_news_with_warning": "news",
            "retry_fundamental":         "update_fund_retry",
        },
    )
    graph.add_edge("update_fund_retry", "fundamental")

    graph.add_conditional_edges(
        "news",
        route_after_news,
        {
            "proceed_risk":              "risk",
            "proceed_risk_with_warning": "risk",
            "retry_news":                "update_news_retry",
        },
    )
    graph.add_edge("update_news_retry", "news")

    graph.add_edge("risk",       "quality")
    graph.add_edge("quality",    "supervisor")
    graph.add_edge("supervisor", END)

    return graph.compile()


def run_analysis(ticker: str) -> dict:
    """
    Führt die vollständige Analyse via LangGraph aus.
    Ersetzt run_supervisor() aus supervisor.py.
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
        "quality_checks":           None,
        "data_consistency_score":   None,
        "final_memo":               None,
        "analysis_started_at":      datetime.now().isoformat(),
        "analysis_duration_s":      None,
        "routing_log":              [],
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

    rec  = memo.get("final_recommendation", "n/v")
    conv = memo.get("conviction_level", "n/v")
    print(f"✓ ANALYSE ABGESCHLOSSEN in {duration:.1f}s")
    print(f"  Empfehlung: {rec} | Conviction: {conv}")
    print(f"{'='*60}\n")

    return memo
