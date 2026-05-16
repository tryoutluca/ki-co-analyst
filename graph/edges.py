from graph.state import AnalysisState


def route_after_fundamental(state: AnalysisState) -> str:
    """
    Conditional Edge nach Fundamental-Knoten.
    - "proceed_news":              Output valide
    - "retry_fundamental":         Output unvollständig, Retries verfügbar
    - "proceed_news_with_warning": Max Retries erreicht
    """
    f_out = state.get("fundamental_output") or {}
    retry = state.get("fundamental_retry_count", 0)

    if f_out.get("error"):
        if retry < 2:
            print(f"      [edge] Retry fundamental ({retry+1}/2): Fehler")
            return "retry_fundamental"
        print(f"      [edge] Max Retries erreicht → proceed mit Warnung")
        return "proceed_news_with_warning"

    fv = f_out.get("fair_value_estimate")
    if not fv or fv in ("n/v", "-", "N/A", None):
        if retry < 2:
            print(f"      [edge] Retry fundamental ({retry+1}/2): Fair Value fehlt")
            return "retry_fundamental"
        print(f"      [edge] Fair Value fehlt — proceed mit Warnung")
        return "proceed_news_with_warning"

    if not f_out.get("investment_case"):
        if retry < 1:
            print(f"      [edge] Retry fundamental ({retry+1}/2): Investment Case leer")
            return "retry_fundamental"
        return "proceed_news_with_warning"

    print(f"      [edge] Fundamental valide → proceed zu News")
    return "proceed_news"


def route_after_news(state: AnalysisState) -> str:
    """
    Conditional Edge nach News-Knoten.
    - "proceed_risk":              Output valide
    - "retry_news":                Output unvollständig, Retry verfügbar
    - "proceed_risk_with_warning": Max Retries erreicht
    """
    n_out = state.get("news_output") or {}
    retry = state.get("news_retry_count", 0)

    if n_out.get("error"):
        if retry < 1:
            print(f"      [edge] Retry news (1/1): Fehler")
            return "retry_news"
        return "proceed_risk_with_warning"

    if not n_out.get("overall_sentiment_score"):
        if retry < 1:
            print(f"      [edge] Retry news (1/1): Sentiment Score fehlt")
            return "retry_news"
        return "proceed_risk_with_warning"

    print(f"      [edge] News valide → proceed zu Risk")
    return "proceed_risk"


def update_fundamental_retry(state: AnalysisState) -> dict:
    """Erhöht Retry-Counter vor erneutem Fundamental-Aufruf."""
    return {
        "fundamental_retry_count": state.get("fundamental_retry_count", 0) + 1,
        "retry_reason": "Fundamental-Output unvollständig",
    }


def update_news_retry(state: AnalysisState) -> dict:
    """Erhöht Retry-Counter vor erneutem News-Aufruf."""
    return {
        "news_retry_count": state.get("news_retry_count", 0) + 1,
        "retry_reason": "News-Output unvollständig",
    }
