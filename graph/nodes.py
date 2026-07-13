import sys
import os
import json
from graph.state import AnalysisState

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from agents.fundamental_agent import run_fundamental_agent
    from agents.news_agent import run_news_agent
    from agents.risk_agent import run_risk_agent
    from agents.classifier_agent import run_classifier_agent
except ImportError:
    from graph.fundamental_agent import run_fundamental_agent
    from graph.news_agent import run_news_agent
    from graph.risk_agent import run_risk_agent
    from graph.classifier_agent import run_classifier_agent

from graph.supervisor import _build_quality_checks, synthesize_memo
from tools.estimate_revision import apply_estimate_adjustments

try:
    from agents.forward_estimate_agent import run_forward_estimate_agent
    from agents.fundamental_agent import build_forward_rows_from_thesis
except ImportError:
    from graph.forward_estimate_agent import run_forward_estimate_agent
    from graph.fundamental_agent import build_forward_rows_from_thesis

try:
    from agents.thematic_agent import run_thematic_agent
except ImportError:
    from graph.thematic_agent import run_thematic_agent

try:
    from agents.optionality_agent import run_optionality_agent
except ImportError:
    from graph.optionality_agent import run_optionality_agent


def optionality_node(state: AnalysisState) -> dict:
    """
    Phase 4: Optionality-Sub-Agent. Real-Options-Bewertung für
    Pre-Revenue/Deep-Tech-Plays (Cash-Runway + TAM×Adoption + Szenario-Pfade).
    Läuft nach thematic (nutzt Adoptionskurven), greift nur bei
    optionality_play — bei allen anderen Unternehmen No-op.
    """
    bmc = state.get("business_model_classification") or {}
    is_opt = (bmc.get("business_model_type") == "optionality_play") or \
             bool(bmc.get("requires_optionality_analysis"))

    if not is_opt:
        return {
            "optionality_analysis": None,
            "routing_log": state.get("routing_log", []) + ["[optionality] ⏭ kein optionality_play"],
        }

    print(f"\n[optionality] Knoten läuft für {state['ticker']}...")
    try:
        oa = run_optionality_agent(
            ticker=state["ticker"],
            fundamental_output=state.get("fundamental_output"),
            thematic_context=state.get("thematic_analysis"),
            news_output=state.get("news_output"),
            business_model_context=bmc,
        )
        if not oa:
            return {
                "optionality_analysis": None,
                "routing_log": state.get("routing_log", []) + ["[optionality] ℹ keine Bewertung"],
            }
        log_entry = (
            f"[optionality] ✅ Fair Value: {oa.get('probability_weighted_value','n/v')} | "
            f"Runway: {oa.get('runway_months','n/v')} Mt | "
            f"Risiko: {oa.get('dilution_risk','?')}"
        )
        return {
            "optionality_analysis": oa,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[optionality] ⚠ Fehler — übersprungen: {e}"
        print(f"      {log_entry}")
        return {
            "optionality_analysis": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def thematic_node(state: AnalysisState) -> dict:
    """
    Phase 3: Thematic-Agent (4. Junior). Mappt Megatrends auf das Unternehmen
    und liefert quantifizierte Wachstumsbeiträge. Läuft nach estimate_revision,
    vor forward_estimate (damit der Forward-Agent die Trends nutzen kann).
    """
    print(f"\n[thematic] Knoten läuft für {state['ticker']}...")

    try:
        ta = run_thematic_agent(
            ticker=state["ticker"],
            fundamental_output=state.get("fundamental_output"),
            news_output=state.get("news_output"),
            business_model_context=state.get("business_model_classification"),
        )
        if not ta:
            return {
                "thematic_analysis": None,
                "routing_log": state.get("routing_log", []) + ["[thematic] ℹ keine Trends"],
            }
        n = len(ta.get("trends", []))
        log_entry = (
            f"[thematic] ✅ {n} Trends | "
            f"Netto: {ta.get('net_thematic_assessment', '?')} | "
            f"Conf: {ta.get('self_confidence', 0):.2f}"
        )
        return {
            "thematic_analysis": ta,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[thematic] ⚠ Fehler — übersprungen: {e}"
        print(f"      {log_entry}")
        return {
            "thematic_analysis": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def forward_estimate_node(state: AnalysisState) -> dict:
    """
    Forward-Estimate-Agent: leitet die Forward-Estimates aus einer
    Wachstums-These her (Sektor/Thematic/Makro/Position), nicht aus dem
    Median der Vergangenheit. Läuft nach estimate_revision, vor risk.
    """
    print(f"\n[forward_estimate] Knoten läuft für {state['ticker']}...")
    f_out = state.get("fundamental_output") or {}

    try:
        from tools.finance_tools import get_consensus_estimates
        try:
            consensus = get_consensus_estimates(state["ticker"])
        except Exception:
            consensus = None

        # Prefer IR-sourced quarterly signal (from PDF); fallback to yfinance-derived
        _qs_yf = (f_out.get("all_multiples") or {}).get("_quarterly_signal")
        _qs_ir = f_out.get("ir_quarterly_signal")
        _qs    = _qs_ir or _qs_yf

        fe = run_forward_estimate_agent(
            ticker=state["ticker"],
            fundamental_output=f_out,
            news_output=state.get("news_output"),
            business_model_context=state.get("business_model_classification"),
            thematic_context=state.get("thematic_analysis"),  # Phase 3, optional
            consensus_estimates=consensus,
            quarterly_signal=_qs,
        )

        if not fe:
            log_entry = "[forward_estimate] ℹ Keine Projektion möglich — übersprungen"
            return {
                "forward_estimates": None,
                "routing_log": state.get("routing_log", []) + [log_entry],
            }

        n = len(fe.get("projections", []))
        warns = sum(1 for p in fe["projections"] if p.get("plausibility_flag"))
        log_entry = (
            f"[forward_estimate] ✅ {n} Jahre projiziert | "
            f"Conf: {fe.get('self_confidence', 0):.2f} | "
            f"Plausibilitäts-Warnungen: {warns}"
        )

        # full_financials wurde im fundamental-Knoten mit E-Zeilen aus der
        # simplen consensus_estimates_from_ir-Heuristik gebaut (die läuft vor
        # diesem Knoten). Jetzt, wo die echte Wachstumsthese vorliegt, werden
        # die E-Zeilen dadurch ersetzt — sonst zeigt das Memo zwei
        # widersprüchliche Forward-Projektionen für dieselben Jahre.
        updated_f_out = f_out
        full_fin = f_out.get("_full_financials")
        if isinstance(full_fin, list) and fe.get("projections"):
            data_cache = f_out.get("_data_cache") or {}
            new_e_rows = build_forward_rows_from_thesis(
                projections   = fe["projections"],
                all_multiples = f_out.get("all_multiples") or data_cache.get("all_multiples"),
                ir_analysis   = f_out.get("_ir_analysis"),
                stock_info    = data_cache.get("stock_info"),
                current_price = f_out.get("current_price"),
            )
            actual_rows = [r for r in full_fin if r.get("type") != "E"]
            updated_f_out = {**f_out, "_full_financials": actual_rows + new_e_rows}

        return {
            "forward_estimates":  fe,
            "quarterly_signal":   _qs,
            "fundamental_output": updated_f_out,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[forward_estimate] ⚠ Fehler — übersprungen: {e}"
        print(f"      {log_entry}")
        return {
            "forward_estimates": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def classifier_node(state: AnalysisState) -> dict:
    """Knoten 0 (Phase 1): Geschäftsmodell-Klassifikation vor allen Agenten."""
    ticker = state["ticker"]
    print(f"\n[classifier] Knoten läuft für {ticker}...")

    try:
        classification = run_classifier_agent(ticker)
        log_entry = (
            f"[classifier] ✅ {classification['business_model_type']} "
            f"(Conf: {classification['classification_confidence']:.2f}, "
            f"DCF: {'ja' if classification['dcf_applicable'] else 'nein'})"
        )
        return {
            "business_model_classification": classification,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[classifier] ⚠ Fehler — Fallback auf growth_with_revenue: {e}"
        print(f"      {log_entry}")
        return {
            "business_model_classification": {
                "business_model_type": "growth_with_revenue",
                "classification_confidence": 0.30,
                "rationale": f"Classifier-Fehler: {e}",
                "valuation_methods_recommended": ["DCF", "EV/EBITDA"],
                "dcf_applicable": True,
                "suggested_weights": {
                    "fundamental": 0.70, "news": 0.15,
                    "risk": 0.15, "thematic": 0.0,
                },
                "suggested_peers": [],
                "requires_optionality_analysis": False,
                "cycle_position": "unknown",
            },
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def estimate_revision_node(state: AnalysisState) -> dict:
    """
    Knoten (Phase 2): Makro-Estimate-Revision.

    Läuft NACH dem News-Agent und VOR dem Risk-Agent. Wendet die vom
    News-Agent identifizierten estimate_adjustments (Makro-/Sektor-Treiber
    mit Transmission-Chain) DETERMINISTISCH auf die Forward-Estimates des
    Fundamental-Agenten an. Kein LLM-Call — reine Python-Berechnung.
    """
    print(f"\n[estimate_revision] Knoten läuft für {state['ticker']}...")

    n_out = state.get("news_output") or {}
    f_out = state.get("fundamental_output") or {}
    adjustments = n_out.get("estimate_adjustments", []) if isinstance(n_out, dict) else []

    if not adjustments:
        log_entry = "[estimate_revision] ℹ Keine Makro-Adjustments identifiziert — übersprungen"
        print(f"      {log_entry}")
        return {
            "revised_estimates": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    try:
        news_conf = (state.get("agent_confidence_scores") or {}).get("news", 0.70)
        revised = apply_estimate_adjustments(
            fundamental_output=f_out,
            adjustments=adjustments,
            news_agent_confidence=news_conf,
        )
        log_entry = (
            f"[estimate_revision] ✅ {len(revised['adjustments_applied'])} Adjustments | "
            f"Umsatz-Δ: {revised['revenue_delta_pct']:+.2f}% | "
            f"EPS-Δ: {revised['eps_delta_pct']:+.2f}%"
        )
        print(f"      {log_entry}")
        return {
            "revised_estimates": revised,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[estimate_revision] ⚠ Fehler — Revision übersprungen: {e}"
        print(f"      {log_entry}")
        return {
            "revised_estimates": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def fundamental_node(state: AnalysisState) -> dict:
    """Knoten 1: Fundamentalanalyse."""
    ticker = state["ticker"]
    retry = state.get("fundamental_retry_count", 0)

    print(f"\n[fundamental] Knoten läuft "
          f"({'Wiederholung ' + str(retry) if retry > 0 else 'Erstaufruf'})...")

    try:
        output = run_fundamental_agent(
            ticker,
            structural_context=state.get("structural_context"),
            business_model_context=state.get("business_model_classification"),
            ir_analysis_cache=state.get("ir_analysis_cache"),
            data_cache=state.get("fundamental_data_cache"),
        )

        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "fundamental": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[fundamental] ✅ Erfolgreich | "
            f"Fair Value: {output.get('fair_value_estimate')} | "
            f"Empfehlung: {output.get('recommendation')} | "
            f"Conf: {agent_conf['fundamental']:.2f}"
        )

        return {
            "fundamental_output": output,
            "agent_confidence_scores": agent_conf,
            "ir_analysis_cache": state.get("ir_analysis_cache") or output.get("_ir_analysis"),
            "fundamental_data_cache": state.get("fundamental_data_cache") or output.get("_data_cache"),
            "routing_log": state.get("routing_log", []) + [log_entry],
        }

    except Exception as e:
        log_entry = f"[fundamental] ❌ Fehler: {str(e)}"
        print(f"      {log_entry}")
        return {
            "fundamental_output": {"error": str(e), "error_type": type(e).__name__},
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
        output = run_news_agent(
            ticker,
            fundamental_context,
            business_model_context=state.get("business_model_classification"),
        )

        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "news": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[news] ✅ Erfolgreich | "
            f"Sentiment: {output.get('overall_sentiment_score')}/10 | "
            f"Outlook: {output.get('short_term_outlook')} | "
            f"Adjustments: {len(output.get('estimate_adjustments', []))} | "
            f"Conf: {agent_conf['news']:.2f}"
        )

        return {
            "news_output": output,
            "agent_confidence_scores": agent_conf,
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
        output = run_risk_agent(
            ticker, f_out, n_out,
            business_model_context=state.get("business_model_classification"),
        )

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

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "risk": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[risk] ✅ Erfolgreich | "
            f"Bear-Case: {bear_price} | "
            f"Conviction Killers: {len(output.get('conviction_killers', []))} | "
            f"Conf: {agent_conf['risk']:.2f}"
        )

        return {
            "risk_output": output,
            "agent_confidence_scores": agent_conf,
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


# ── Neue Knoten: Anomalie-Erkennung & Corporate Actions ──────────────────────


def anomaly_check_node(state: AnalysisState) -> dict:
    """Knoten A: Deterministischer Anomalie-Check auf strukturelle Veränderungen."""
    from tools.finance_tools import get_historical_financials, detect_structural_anomalies
    ticker = state["ticker"]
    print(f"\n[anomaly_check] Prüfe auf strukturelle Veränderungen...")

    try:
        hist_data = get_historical_financials(ticker)
        flags = detect_structural_anomalies(hist_data)

        for f in flags:
            print(f"      ⚠ {f['note']}")

        log_entry = (
            f"[anomaly_check] {len(flags)} Anomalie(n) erkannt"
            if flags else "[anomaly_check] ✅ Keine strukturellen Anomalien"
        )
        return {
            "anomaly_flags": flags,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[anomaly_check] ❌ {e}"
        return {
            "anomaly_flags": [],
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def corporate_actions_node(state: AnalysisState) -> dict:
    """Knoten B: LLM recherchiert Corporate Actions für erkannte Anomalien."""
    from tools.finance_tools import get_strategic_milestones
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    ticker = state["ticker"]
    anomaly_flags = state.get("anomaly_flags") or []
    f_out = state.get("fundamental_output") or {}
    company_name = f_out.get("company", ticker)

    print(f"\n[corporate_actions] Recherchiere Corporate Actions für {company_name}...")

    try:
        milestones = get_strategic_milestones.invoke(
            {"ticker": ticker, "company_name": company_name}
        )
        anomaly_text = "\n".join(f"• {f['note']}" for f in anomaly_flags)

        prompt = (
            f"Analysiere diese Corporate Actions für {company_name} ({ticker}).\n\n"
            f"Erkannte Anomalien in den Finanzkennzahlen:\n{anomaly_text}\n\n"
            f"Strategische Meilensteine (letzte 12 Monate):\n"
            f"{json.dumps(milestones[:5], ensure_ascii=False, indent=2)}\n\n"
            f"Erkläre in 2-3 prägnanten Sätzen welche Corporate Actions (Spin-off, M&A, "
            f"Divestiture, Restrukturierung) die Anomalien erklären. "
            f"Falls ein Spin-off identifiziert: nenne das abgespaltene Unternehmen und erkläre "
            f"dass YoY-Vergleiche Pro-forma Basis brauchen. "
            f"Kein Markdown, keine Überschriften."
        )

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        response = llm.invoke([HumanMessage(content=prompt)])
        structural_context = response.content.strip()

        print(f"      ✅ {structural_context[:100]}...")
        log_entry = f"[corporate_actions] ✅ Kontext: {structural_context[:80]}..."

        return {
            "structural_context": structural_context,
            "corporate_actions_checked": True,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[corporate_actions] ❌ {e}"
        return {
            "structural_context": f"Corporate Actions Analyse nicht verfügbar: {e}",
            "corporate_actions_checked": True,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


# ── Neuer Knoten: Senior-Analyst Review ──────────────────────────────────────

SUPERVISOR_REVIEW_PROMPT = """Du bist ein Senior Equity Analyst und prüfst die Arbeit deiner Junior-Analysten.

PRÜFAUFGABE (vor der finalen Synthese):
Bewerte ob die drei Analysen ausreichend vollständig und konsistent sind.

PRÜFKRITERIEN:
1. Strukturelle Ereignisse: Falls Anomalie-Flags vorhanden (Spin-off, M&A), hat der \
Fundamental-Agent diese adäquat berücksichtigt und erklärt?
2. Zahlen-Plausibilität: Sind EPS-Sprünge >150% begründet? Stimmen Revenue-Angaben überein?
3. Investment Case Qualität: Ist jeder Bullet-Point mit konkreten Zahlen belegt?
4. Empfehlungs-Konsistenz: Passt Empfehlung zur Fair-Value-Herleitung?

ENTSCHEIDUNGSREGELN:
- Sei KONSERVATIV: Nur bei KLAREN, GRAVIERENDEN Mängeln "request_critique"
- Soft-Issues (fehlende Quellen, ungenaue Formulierungen) → "approve"
- Hard-Issues (fehlende Spin-off-Berücksichtigung, implausible Zahlen) → "request_critique"
- Falls supervisor_rounds > 0: IMMER "approve" (keine zweite Critique-Runde)
- Nur EINE Kritik pro Runde, nur EIN Target

Antworte AUSSCHLIESSLICH als valides JSON:
{
  "action": "approve",
  "critique_target": null,
  "critique_text": null,
  "review_notes": "Kurze Begründung (2-3 Sätze)"
}
ODER:
{
  "action": "request_critique",
  "critique_target": "fundamental",
  "critique_text": "Konkrete, actionable Anweisung was der Agent korrigieren soll",
  "review_notes": "Kurze Begründung (2-3 Sätze)"
}"""


def supervisor_review_node(state: AnalysisState) -> dict:
    """Knoten 4b: Senior-Analyst prüft Konsistenz und fordert ggf. Nachbesserung."""
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage

    ticker = state["ticker"]
    rounds = state.get("supervisor_rounds", 0)

    print(f"\n[supervisor_review] Senior-Analyst Review läuft "
          f"(Runde {rounds + 1})...")

    f_out  = state.get("fundamental_output") or {}
    n_out  = state.get("news_output") or {}
    r_out  = state.get("risk_output") or {}
    flags  = state.get("anomaly_flags") or []
    struct = state.get("structural_context") or ""

    anomaly_block = ""
    if flags:
        anomaly_block = (
            "\n=== STRUKTURELLE ANOMALIEN (deterministisch erkannt) ===\n"
            + "\n".join(f"• {f['note']}" for f in flags)
            + f"\n\nCorporate Actions Kontext:\n{struct}\n"
        )

    human_content = (
        f"Prüfe diese drei Analysen für {ticker}.\n"
        f"supervisor_rounds bereits abgeschlossen: {rounds}\n"
        f"{anomaly_block}"
        f"\n=== FUNDAMENTAL-AGENT OUTPUT (Zusammenfassung) ===\n"
        f"Empfehlung: {f_out.get('recommendation', '-')} | "
        f"Fair Value: {f_out.get('fair_value_estimate', '-')} | "
        f"Conviction: {f_out.get('conviction_level', '-')}\n"
        f"Investment Case (erste 2 Punkte): "
        f"{json.dumps(f_out.get('investment_case', [])[:2], ensure_ascii=False)}\n"
        f"Key Metrics: {json.dumps(list(f_out.get('key_metrics', {}).items())[:6], ensure_ascii=False)}\n"
        f"\n=== NEWS-AGENT OUTPUT ===\n"
        f"Sentiment: {n_out.get('overall_sentiment_score', '-')}/10 | "
        f"Outlook: {n_out.get('short_term_outlook', '-')}\n"
        f"\n=== RISK-AGENT OUTPUT ===\n"
        f"Conviction Killers: {len(r_out.get('conviction_killers', []))} | "
        f"Empfehlung: {r_out.get('original_recommendation', '-')}\n"
        f"\nBewerte und antworte als JSON."
    )

    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        response = llm.invoke([
            SystemMessage(content=SUPERVISOR_REVIEW_PROMPT),
            HumanMessage(content=human_content),
        ])
        raw = response.content.strip()

        # Robustes JSON-Parsing
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        review = json.loads(raw[start:end]) if start != -1 else {"action": "approve"}

        action = review.get("action", "approve")
        target = review.get("critique_target")
        notes  = review.get("review_notes", "")

        # Sicherheitsnetz: bei supervisor_rounds > 0 immer approve
        if rounds >= 1:
            action = "approve"
            target = None

        if action == "request_critique" and target in ("fundamental", "news", "risk"):
            print(f"      ↩ Kritik angefordert für [{target}]: "
                  f"{review.get('critique_text', '')[:80]}...")
            log_entry = (
                f"[supervisor_review] ↩ Kritik → {target}: "
                f"{review.get('critique_text', '')[:60]}..."
            )
            return {
                "supervisor_review_action":   "request_critique",
                "supervisor_critique":        review.get("critique_text", ""),
                "supervisor_critique_target": target,
                "routing_log": state.get("routing_log", []) + [log_entry],
            }
        else:
            print(f"      ✅ Analyse genehmigt: {notes[:80]}")
            log_entry = f"[supervisor_review] ✅ Approved: {notes[:60]}"
            return {
                "supervisor_review_action":   "approve",
                "supervisor_critique":        None,
                "supervisor_critique_target": None,
                "routing_log": state.get("routing_log", []) + [log_entry],
            }

    except Exception as e:
        log_entry = f"[supervisor_review] ❌ {e} → approve fallback"
        return {
            "supervisor_review_action":   "approve",
            "supervisor_critique":        None,
            "supervisor_critique_target": None,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def update_supervisor_round(state: AnalysisState) -> dict:
    """Erhöht den Supervisor-Runden-Counter vor dem Critique-Agent-Re-Run."""
    new_round = state.get("supervisor_rounds", 0) + 1
    print(f"\n[supervisor_round] Critique-Runde {new_round} startet...")
    return {
        "supervisor_rounds": new_round,
        "routing_log": state.get("routing_log", []) + [
            f"[supervisor_round] Critique-Runde {new_round}"
        ],
    }


# ── Critique-Knoten: Re-Run mit Supervisor-Feedback ──────────────────────────


def fundamental_critique_node(state: AnalysisState) -> dict:
    """Re-runs Fundamental Agent mit Supervisor-Kritik und structural_context."""
    ticker = state["ticker"]
    critique = state.get("supervisor_critique", "")
    print(f"\n[fundamental_critique] Re-Analyse mit Senior-Feedback...")
    print(f"      Critique: {critique[:100]}...")

    try:
        output = run_fundamental_agent(
            ticker,
            supervisor_critique=critique,
            structural_context=state.get("structural_context"),
            business_model_context=state.get("business_model_classification"),
            ir_analysis_cache=state.get("ir_analysis_cache"),
            data_cache=state.get("fundamental_data_cache"),
        )
        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "fundamental": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[fundamental_critique] ✅ Re-Analyse | "
            f"Fair Value: {output.get('fair_value_estimate')} | "
            f"Empfehlung: {output.get('recommendation')} | "
            f"Conf: {agent_conf['fundamental']:.2f}"
        )
        return {
            "fundamental_output": output,
            "agent_confidence_scores": agent_conf,
            "ir_analysis_cache": state.get("ir_analysis_cache") or output.get("_ir_analysis"),
            "fundamental_data_cache": state.get("fundamental_data_cache") or output.get("_data_cache"),
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[fundamental_critique] ❌ {e}"
        return {
            "fundamental_output": state.get("fundamental_output") or {"error": str(e), "error_type": type(e).__name__},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def news_critique_node(state: AnalysisState) -> dict:
    """Re-runs News Agent mit Supervisor-Kritik."""
    ticker = state["ticker"]
    critique = state.get("supervisor_critique", "")
    print(f"\n[news_critique] Re-Analyse mit Senior-Feedback...")

    f_out = state.get("fundamental_output") or {}
    fundamental_context = (
        f"Empfehlung: {f_out.get('recommendation', '-')}, "
        f"Fair Value: {f_out.get('fair_value_estimate', '-')}"
    )

    try:
        output = run_news_agent(
            ticker,
            fundamental_context,
            supervisor_critique=critique,
            business_model_context=state.get("business_model_classification"),
        )
        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "news": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[news_critique] ✅ Re-Analyse | "
            f"Sentiment: {output.get('overall_sentiment_score')}/10 | "
            f"Conf: {agent_conf['news']:.2f}"
        )
        return {
            "news_output": output,
            "agent_confidence_scores": agent_conf,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[news_critique] ❌ {e}"
        return {
            "news_output": state.get("news_output") or {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


def risk_critique_node(state: AnalysisState) -> dict:
    """Re-runs Risk Agent mit Supervisor-Kritik."""
    ticker = state["ticker"]
    critique = state.get("supervisor_critique", "")
    print(f"\n[risk_critique] Re-Analyse mit Senior-Feedback...")

    f_out = state.get("fundamental_output") or {}
    n_out = state.get("news_output") or {}

    try:
        output = run_risk_agent(
            ticker,
            f_out,
            n_out,
            supervisor_critique=critique,
            business_model_context=state.get("business_model_classification"),
        )
        if hasattr(output, "model_dump"):
            output = output.model_dump()
        elif not isinstance(output, dict):
            output = dict(output)

        agent_conf = state.get("agent_confidence_scores") or {}
        agent_conf = {**agent_conf, "risk": float(output.get("self_confidence", 0.70))}

        log_entry = (
            f"[risk_critique] ✅ Re-Analyse | "
            f"Conviction Killers: {len(output.get('conviction_killers', []))} | "
            f"Conf: {agent_conf['risk']:.2f}"
        )
        return {
            "risk_output": output,
            "agent_confidence_scores": agent_conf,
            "routing_log": state.get("routing_log", []) + [log_entry],
        }
    except Exception as e:
        log_entry = f"[risk_critique] ❌ {e}"
        return {
            "risk_output": state.get("risk_output") or {"error": str(e)},
            "routing_log": state.get("routing_log", []) + [log_entry],
        }


# ── Bestehender Supervisor-Synthese-Knoten ────────────────────────────────────


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
            business_model_classification=state.get("business_model_classification"),
            agent_confidence_scores=state.get("agent_confidence_scores"),
            revised_estimates=state.get("revised_estimates"),
            forward_estimates=state.get("forward_estimates"),
            thematic_analysis=state.get("thematic_analysis"),
            optionality_analysis=state.get("optionality_analysis"),
            anomaly_flags=state.get("anomaly_flags") or [],
            structural_context=state.get("structural_context"),
        )

        if hasattr(memo, "model_dump"):
            memo = memo.model_dump()
        elif not isinstance(memo, dict):
            memo = dict(memo)

        memo["routing_log"] = state.get("routing_log", [])
        memo["fundamental_retry_count"] = state.get("fundamental_retry_count", 0)
        # Phase 1/2: Transparenz-Felder ins Memo
        memo["business_model_classification"] = state.get("business_model_classification")
        memo["agent_confidence_scores"] = state.get("agent_confidence_scores")
        memo["revised_estimates"] = state.get("revised_estimates")
        memo["forward_estimates"] = state.get("forward_estimates")
        memo["thematic_analysis"] = state.get("thematic_analysis")
        memo["optionality_analysis"] = state.get("optionality_analysis")

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
