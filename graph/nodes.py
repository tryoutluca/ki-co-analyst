import sys
import os
from graph.state import AnalysisState

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from agents.fundamental_agent import run_fundamental_agent
    from agents.news_agent import run_news_agent
    from agents.risk_agent import run_risk_agent
except ImportError:
    from graph.fundamental_agent import run_fundamental_agent
    from graph.news_agent import run_news_agent
    from graph.risk_agent import run_risk_agent

from graph.supervisor import _build_quality_checks, synthesize_memo


def fundamental_node(state: AnalysisState) -> dict:
    """Knoten 1: Fundamentalanalyse."""
    ticker = state["ticker"]
    retry = state.get("fundamental_retry_count", 0)

    print(f"\n[fundamental] Knoten läuft "
          f"({'Wiederholung ' + str(retry) if retry > 0 else 'Erstaufruf'})...")

    try:
        output = run_fundamental_agent(ticker)

        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        log_entry = (
            f"[fundamental] ✅ Erfolgreich | "
            f"Fair Value: {output.get('fair_value_estimate')} | "
            f"Empfehlung: {output.get('recommendation')}"
        )

        return {
            "fundamental_output": output,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[fundamental] ❌ Fehler: {str(e)}"
        print(f"      {log_entry}")
        return {
            "fundamental_output": {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def news_node(state: AnalysisState) -> dict:
    """Knoten 2: News & Sentiment Analyse."""
    ticker = state["ticker"]
    retry = state.get("news_retry_count", 0)

    print(f"\n[news] Knoten läuft "
          f"({'Wiederholung ' + str(retry) if retry > 0 else 'Erstaufruf'})...")

    f_out = state.get("fundamental_output") or {}
    fundamental_context = (
        f"Empfehlung: {f_out.get('recommendation', '-')}, "
        f"Fair Value: {f_out.get('fair_value_estimate', '-')}, "
        f"Bewertung: {f_out.get('valuation_assessment', '-')}"
    )

    try:
        output = run_news_agent(ticker, fundamental_context)

        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        log_entry = (
            f"[news] ✅ Erfolgreich | "
            f"Sentiment: {output.get('overall_sentiment_score')}/10 | "
            f"Outlook: {output.get('short_term_outlook')}"
        )

        return {
            "news_output": output,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[news] ❌ Fehler: {str(e)}"
        print(f"      {log_entry}")
        return {
            "news_output": {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def risk_node(state: AnalysisState) -> dict:
    """Knoten 3: Risiko-Analyse (Advocatus Diaboli)."""
    ticker = state["ticker"]

    print(f"\n[risk] Knoten läuft...")

    f_out = state.get("fundamental_output") or {}
    n_out = state.get("news_output") or {}

    try:
        output = run_risk_agent(ticker, f_out, n_out)

        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        scenarios = output.get("scenarios", [])
        bear = next(
            (s for s in scenarios
             if (s.get("name") if isinstance(s, dict) else s.name) == "Bear Case"),
            None,
        )
        bear_price = (
            bear.get("price_target") if isinstance(bear, dict)
            else getattr(bear, "price_target", "N/A")
        ) if bear else "N/A"

        log_entry = (
            f"[risk] ✅ Erfolgreich | "
            f"Bear-Case: {bear_price} | "
            f"Conviction Killers: {len(output.get('conviction_killers', []))}"
        )

        return {
            "risk_output": output,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[risk] ❌ Fehler: {str(e)}"
        print(f"      {log_entry}")
        return {
            "risk_output": {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def quality_node(state: AnalysisState) -> dict:
    """Knoten 4: Deterministische Qualitätsprüfung."""
    print(f"\n[quality] Qualitätsprüfung läuft...")

    f_out = state.get("fundamental_output") or {}
    n_out = state.get("news_output") or {}
    r_out = state.get("risk_output") or {}

    try:
        checks = _build_quality_checks(f_out, n_out, r_out)

        ok  = sum(1 for c in checks if c["result"] == "bestanden")
        wrn = sum(1 for c in checks if c["result"] == "Warnung")
        err = sum(1 for c in checks if c["result"] == "fehlgeschlagen")
        score = max(1, min(10, 10 - (err * 2) - wrn))

        log_entry = (
            f"[quality] ✅ {ok} bestanden | "
            f"⚠️ {wrn} Warnungen | "
            f"❌ {err} fehlgeschlagen | "
            f"Score: {score}/10"
        )
        print(f"      {log_entry}")

        return {
            "quality_checks": checks,
            "data_consistency_score": score,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[quality] ❌ Fehler: {str(e)}"
        return {
            "quality_checks": [],
            "data_consistency_score": 5,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def supervisor_node(state: AnalysisState) -> dict:
    """Knoten 5: Supervisor-Synthese."""
    ticker = state["ticker"]

    print(f"\n[supervisor] Synthese läuft...")

    f_out  = state.get("fundamental_output") or {}
    n_out  = state.get("news_output") or {}
    r_out  = state.get("risk_output") or {}
    checks = state.get("quality_checks") or []
    score  = state.get("data_consistency_score") or 5

    try:
        memo = synthesize_memo(
            ticker, f_out, n_out, r_out,
            quality_checks=checks,
            consistency_score=score,
        )

        if hasattr(memo, "model_dump"):
            memo = memo.model_dump()
        elif not isinstance(memo, dict):
            memo = dict(memo)

        memo["routing_log"] = state.get("routing_log", [])
        memo["fundamental_retry_count"] = state.get("fundamental_retry_count", 0)

        log_entry = (
            f"[supervisor] ✅ Memo erstellt | "
            f"Empfehlung: {memo.get('final_recommendation')} | "
            f"Conviction: {memo.get('conviction_level')}"
        )

        return {
            "final_memo": memo,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[supervisor] ❌ Fehler: {str(e)}"
        return {
            "final_memo": {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
