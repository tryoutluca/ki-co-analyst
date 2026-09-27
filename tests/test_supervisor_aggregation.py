"""
tests/test_supervisor_aggregation.py — Deterministische Aggregation im Supervisor
und Dashboard-Transparenzfelder (ohne LLM).

    pytest tests/test_supervisor_aggregation.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.supervisor import (
    _aggregation_weights,
    _apply_deterministic_score,
    _build_aggregation_block,
    _score_to_recommendation,
)
from graph.nodes import _build_agent_results

BMC = {"business_model_type": "mature_cashflow", "dcf_applicable": True,
       "suggested_weights": {"fundamental": 0.6, "news": 0.2, "risk": 0.2}}
CONF = {"fundamental": 0.8, "news": 0.7, "risk": 0.7}


def _news(score=5, macro="neutral", industry="neutral"):
    return {"overall_sentiment_score": score, "overall_macro_direction": macro,
            "overall_industry_direction": industry}


class TestThresholds:
    def test_boundaries_match_prompt_directive(self):
        assert _score_to_recommendation(12.1) == "KAUFEN"
        assert _score_to_recommendation(12) == "ÜBERGEWICHTEN"
        assert _score_to_recommendation(4) == "ÜBERGEWICHTEN"
        assert _score_to_recommendation(3.9) == "HALTEN"
        assert _score_to_recommendation(-4) == "UNTERGEWICHTEN"
        assert _score_to_recommendation(-12) == "UNTERGEWICHTEN"
        assert _score_to_recommendation(-12.1) == "VERKAUFEN"


class TestDeterministicScore:
    def test_formula(self):
        result = {"upside_downside_pct": 20.0, "final_recommendation": "HALTEN", "final_reasoning": ""}
        risk = {"conviction_killers": [{"x": 1}]}
        out = _apply_deterministic_score(result, _news(7, "tailwind"), risk, BMC, CONF, None)
        agg = out["aggregation"]
        w = _aggregation_weights(_news(7, "tailwind"), BMC, CONF, None)["weights"]
        expected = 20 * w["fundamental"] + 20 * w["news"] + 5 * w["risk"]
        assert agg["score"] == round(expected, 2)
        assert agg["components"] == {"fundamental": 20.0, "news": 20.0, "risk": 5}
        assert out["final_recommendation"] == _score_to_recommendation(expected)

    def test_llm_recommendation_kept_and_explained(self):
        result = {"upside_downside_pct": 30.0, "final_recommendation": "HALTEN", "final_reasoning": "x"}
        out = _apply_deterministic_score(result, _news(8), {"conviction_killers": []}, BMC, CONF, None)
        assert out["aggregation"]["llm_recommendation"] == "HALTEN"
        assert out["final_recommendation"] == "KAUFEN"
        assert "[Aggregation]" in out["final_reasoning"]

    def test_negative_sentiment_can_flip_positive_upside(self):
        # +6 % Upside allein wäre ÜBERGEWICHTEN (alte Backend-Regel) —
        # schlechtes Sentiment + 2 Conviction Killers + Gegenwind drücken den Score
        result = {"upside_downside_pct": 6.0, "final_recommendation": "ÜBERGEWICHTEN"}
        risk = {"conviction_killers": [{}, {}]}
        out = _apply_deterministic_score(result, _news(2, "headwind", "headwind"), risk, BMC, CONF, None)
        assert out["aggregation"]["score"] < 4
        assert out["final_recommendation"] in ("HALTEN", "UNTERGEWICHTEN", "VERKAUFEN")

    def test_thematic_component(self):
        th = {"trends": [{"trend": "AI"}], "net_thematic_assessment": "starker rückenwind",
              "self_confidence": 0.6}
        bmc = {**BMC, "suggested_weights": {**BMC["suggested_weights"], "thematic": 0.2}}
        out = _apply_deterministic_score({"upside_downside_pct": 0.0}, _news(5), {"conviction_killers": []},
                                         bmc, CONF, th)
        assert out["aggregation"]["components"]["thematic"] == 20
        assert "thematic" in out["aggregation"]["weights"]

    def test_upside_from_price_target(self):
        out = _apply_deterministic_score({"price_target": 110, "current_price": 100},
                                         _news(), {}, BMC, CONF, None)
        assert out["aggregation"]["components"]["fundamental"] == 10.0

    def test_missing_upside_keeps_llm_recommendation(self):
        out = _apply_deterministic_score({"final_recommendation": "HALTEN"}, _news(), {}, BMC, CONF, None)
        assert out["final_recommendation"] == "HALTEN"
        assert out["aggregation"]["score"] is None

    def test_prompt_block_still_builds(self):
        block = _build_aggregation_block({}, _news(), {"scenarios": []}, BMC, CONF)
        assert "AGGREGATIONS-DIREKTIVE" in block and "Score > 12" in block


class TestAgentResults:
    def test_rows_and_confidence(self):
        state = {
            "fundamental_output": {"investment_case": [{"point": "EV/EBITDA 8x vs Peers 10x"}]},
            "news_output": {"sentiment_vs_fundamentals_reasoning": "Solide Zahlen, CEO-Vakuum"},
            "risk_output": {"counter_position": "Zyklus-Spitze"},
            "revised_estimates": {"summary": "Keine Makro-Anpassung"},
            "thematic_analysis": {"thematic_thesis": "Elektrifizierung", "self_confidence": 0.6},
            "forward_estimates": {"overall_thesis": "+5 % p.a.", "self_confidence": 0.7},
            "optionality_analysis": None,
            "agent_confidence_scores": {"fundamental": 0.8, "news": 0.7, "risk": 0.65},
            "supervisor_critique_target": "risk",
        }
        rows = {r["key"]: r for r in _build_agent_results(state, {})}
        assert rows["fundamental"]["text"] == "EV/EBITDA 8x vs Peers 10x"
        assert rows["fundamental"]["confidence"] == 0.8
        assert rows["estimate_revision"]["confidence"] is None       # deterministisch
        assert rows["thematic"]["confidence"] == 0.6
        assert rows["optionality"]["ran"] is False
        assert rows["risk"]["after_critique"] is True


class TestJobStdout:
    def test_routes_by_thread_and_single_running_job(self):
        import io
        import threading
        from backend.job_stdout import JobStdout

        buf = io.StringIO()
        jobs = {"A": {"status": "running", "progress": []},
                "B": {"status": "running", "progress": []}}
        router = JobStdout(buf, jobs, threading.Lock())

        def job(jid, msg):
            router.bind(jid)
            router.write(msg)

        ta = threading.Thread(target=job, args=("A", "log A"))
        tb = threading.Thread(target=job, args=("B", "log B"))
        ta.start(); tb.start(); ta.join(); tb.join()
        assert jobs["A"]["progress"] == ["log A"]
        assert jobs["B"]["progress"] == ["log B"]

        router.write("ohne Job-Bindung")          # zwei Jobs laufen → nicht zuordenbar
        assert "ohne Job-Bindung" in buf.getvalue()

        jobs["B"]["status"] = "done"
        router.write("Worker-Thread")              # nur A läuft → geht an A
        assert jobs["A"]["progress"][-1] == "Worker-Thread"

        jobs["C"] = {"status": "running", "progress": []}
        jobs["A"]["status"] = "cancelling"         # A beendet noch seinen Agenten
        router.write("unklar")                     # A und C aktiv → nicht zuordenbar
        assert jobs["C"]["progress"] == []


class TestCancellation:
    def test_graph_stops_before_first_node(self):
        import pytest
        from graph.graph import build_analysis_graph, AnalysisCancelled
        compiled = build_analysis_graph(cancel_check=lambda: True)
        with pytest.raises(AnalysisCancelled) as exc:
            compiled.invoke({"ticker": "TEST", "routing_log": []})
        assert str(exc.value) == "classifier"

    def test_guard_passes_through_when_not_cancelled(self):
        from graph.graph import _guard
        called = []
        fn = _guard("x", lambda s: called.append(s) or {"ok": 1}, lambda: False)
        assert fn({"a": 1}) == {"ok": 1} and called == [{"a": 1}]

    def test_no_guard_without_cancel_check(self):
        from graph.graph import _guard
        f = lambda s: s
        assert _guard("x", f, None) is f
