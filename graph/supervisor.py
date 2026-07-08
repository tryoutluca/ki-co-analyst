from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
from datetime import date
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.schemas import SupervisorOutput

load_dotenv()

llm = ChatAnthropic(model="claude-sonnet-4-5")
parser = JsonOutputParser(pydantic_object=SupervisorOutput)

SUPERVISOR_PROMPT = """Du bist der Senior Portfolio Manager und leitende Analyst einer Schweizer
Asset Management Firma. Drei Junior-Analysten haben ihre Spezialanalysen abgeliefert. Deine Aufgabe:

SCHRITT 1 — QUALITÄTSPRÜFUNG (vor der Synthese):
Prüfe aktiv die Konsistenz der drei Analysen:
- Stimmen die Zahlen überein? (z.B. KGV beim Fundamental- und Risk-Agent — flag wenn Differenz >5%)
- Gibt es Widersprüche zwischen den Empfehlungen?
- Sind alle Quellen vollständig und glaubwürdig?
- Hat der Fundamental-Agent die Makro-Risiken aus dem News-Agent berücksichtigt?
- Sind die Conviction Killers des Risk-Agents in der Fundamentalanalyse reflektiert?
Dokumentiere JEDEN Qualitätscheck mit Ergebnis: bestanden/Warnung/fehlgeschlagen

SCHRITT 2 — SYNTHESE nach professionellen Buy-Side Standards:

GEWICHTUNG — ⚠️ ZWINGEND aus der AGGREGATIONS-DIREKTIVE im Human-Prompt:
- Die effektiven Gewichte (Fundamental/News/Risk/Thematic) werden NICHT hier
  festgelegt, sondern stehen deterministisch berechnet in der
  AGGREGATIONS-DIREKTIVE weiter unten. Sie hängen ab von Geschäftsmodell-Typ,
  Agent-Confidence, Sentiment und DCF-Anwendbarkeit.
- Verwende AUSSCHLIESSLICH die dort vorgegebenen Gewichte und die dort
  vorgegebene Score-Formel. Erfinde KEINE eigene 80/10/10-Gewichtung.
- Falls die Direktive z.B. Fundamental 55%, News 20%, Risk 15%, Thematic 10%
  vorgibt, nutze GENAU diese Werte — nicht die früheren Standardwerte.

EMPFEHLUNGS-SKALA (5-stufig — Buy-Side Standard):

  Die Score→Empfehlung-Schwellen stehen ebenfalls in der AGGREGATIONS-DIREKTIVE.
  Mappe den dort berechneten Score auf:
    KAUFEN / ÜBERGEWICHTEN / HALTEN / UNTERGEWICHTEN / VERKAUFEN
  gemäss den Schwellen in der Direktive.

  WICHTIG — Upside ist NICHT alleiniger Faktor:
  Der Score kombiniert Upside, Sentiment, Risk (und ggf. Thematic) mit den
  dynamischen Gewichten aus der Direktive. Die genaue Formel steht dort.

  Risk_Adjustment (Bestandteil der Score-Formel):
    Keine Conviction Killers aktiv:     +10
    1 Conviction Killer aktiv:           0
    2+ Conviction Killers aktiv:        -15
    Makro headwind:                      -5
    Makro tailwind:                      +5

  Die konkrete Score-Formel mit den effektiven Gewichten und das
  Score→Empfehlung-Mapping stehen in der AGGREGATIONS-DIREKTIVE im
  Human-Prompt. Nutze AUSSCHLIESSLICH diese — sie ist die einzige
  Quelle der Wahrheit für Gewichte, Formel und Schwellen.

  CONVICTION LEVEL bei 5-stufiger Skala:
    hoch:    KAUFEN oder VERKAUFEN (klare Richtung)
    mittel:  ÜBERGEWICHTEN oder UNTERGEWICHTEN
    niedrig: HALTEN (maximale Unsicherheit)

CONVICTION LEVEL Regeln:
- hoch: Alle drei Agenten zeigen dieselbe Richtung UND keine Conviction Killers
- mittel: Zwei von drei Agenten einig ODER ein Conviction Killer vorhanden
- niedrig: Widersprüche zwischen Agenten ODER zwei+ Conviction Killers

INVESTMENT CASE Regeln:
- die relevantesten 3-5 Bulletpoints
- Jeder Punkt: konkrete Zahl + Peer-Vergleich oder historischer Vergleich + Quelle
- Kein Punkt ohne Zahl — "günstige Bewertung" ist NICHT ausreichend
- Letzter Punkt immer: Katalysator der die These auslöst

CONSENSUS ESTIMATES Tabelle:
- 2 historische Jahre (A=Actual) aus Finanzkennzahlen
- 3 Vorwärtsjahre (E=Estimate) aus Konsensschätzungen
- Falls Schätzungen fehlen: mit "-" markieren

VOLLSTÄNDIGE FINANZÜBERSICHT (full_financials):
- Übernehme die 6-Jahres-Tabelle (3A + 3E) exakt aus dem Fundamental-Agent Output
- Kennzeichne Schätzjahre explizit als (E) im year-Feld
- Die Felder source müssen den Disclaimer enthalten:
  "A = Istzahlen | E = Schätzung (Quelle: [source]) | "
- Falls full_financials fehlen: leere Liste zurückgeben

PEER-VERGLEICH (peer_comparison):
- Übernehme die Peer-Tabelle exakt aus dem Fundamental-Agent Output
- Bewertung Subject vs. Sektor-Ø in final_reasoning einbeziehen:
  DISCOUNT (>15% unter Ø) → mögliches Kaufargument
  ELEVATED (>15% über Ø)  → mögliches Bewertungsrisiko
  IN LINE (±15%)           → fair bewertet
- Falls peer_comparison fehlt: null zurückgeben

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON.
{format_instructions}"""


def _extract(output, key, default=None):
    """Works for both dict and Pydantic model outputs from junior agents."""
    if isinstance(output, dict):
        return output.get(key, default)
    return getattr(output, key, default)


def _fundamental_failed(fundamental_output) -> bool:
    """True wenn der Fundamental-Agent nach allen Retries keinen validen Output lieferte."""
    if not fundamental_output:
        return True
    if _extract(fundamental_output, "error"):
        return True
    fv = _extract(fundamental_output, "fair_value_estimate")
    return not fv or fv in ("n/v", "-", "N/A", None)


def _build_quality_checks(fundamental_output, news_output, risk_output) -> list[dict]:
    """Pre-flight consistency checks passed to the supervisor as context."""
    checks = []

    # 0. Fundamental-Agent hat überhaupt einen validen Output geliefert
    # (harter Fail, nicht nur eine Warnung — sonst könnte ein komplett
    # gescheiterter Fundamental-Agent unbemerkt in den Score einfliessen)
    fund_error = _extract(fundamental_output, "error")
    checks.append({
        "check": "Fundamental-Agent hat validen Output geliefert",
        "result": "fehlgeschlagen" if _fundamental_failed(fundamental_output) else "bestanden",
        "comment": f"Fehler: {fund_error}" if fund_error else (
            "Output fehlt oder unvollständig" if _fundamental_failed(fundamental_output) else "OK"
        ),
    })

    # 1. Fair value present
    fv = _extract(fundamental_output, "fair_value_estimate")
    checks.append({
        "check": "Fair Value im Fundamental-Output vorhanden",
        "result": "bestanden" if fv else "fehlgeschlagen",
        "comment": f"fair_value_estimate={fv}" if fv else "Wert fehlt",
    })

    # 2. Sentiment score present
    score = _extract(news_output, "overall_sentiment_score")
    checks.append({
        "check": "Sentiment Score im News-Output vorhanden",
        "result": "bestanden" if score is not None else "fehlgeschlagen",
        "comment": f"overall_sentiment_score={score}" if score is not None else "Wert fehlt",
    })

    # 3. Scenarios probability sum
    scenarios = _extract(risk_output, "scenarios", [])
    if scenarios:
        total = sum(
            s.get("probability_pct", 0) if isinstance(s, dict) else s.probability_pct
            for s in scenarios
        )
        checks.append({
            "check": "Szenario-Wahrscheinlichkeiten summieren auf 100%",
            "result": "bestanden" if abs(total - 100) < 0.5 else "Warnung",
            "comment": f"Summe={total}%" if abs(total - 100) >= 0.5 else "OK",
        })
    else:
        checks.append({
            "check": "Szenario-Wahrscheinlichkeiten summieren auf 100%",
            "result": "Warnung",
            "comment": "Keine Szenarien im Risk-Output gefunden",
        })

    # 4. Macro risks reflected check
    macro_ignored = _extract(risk_output, "macro_risks_ignored", [])
    checks.append({
        "check": "Makro-Risiken aus News-Agent in Fundamentalanalyse berücksichtigt",
        "result": "Warnung" if macro_ignored else "bestanden",
        "comment": f"{len(macro_ignored)} ignorierte Makro-Risiken" if macro_ignored else "Keine unberücksichtigten Makro-Risiken",
    })

    # 5. Recommendation direction check
    fund_rec = _extract(fundamental_output, "recommendation", "")
    risk_rec = _extract(risk_output, "original_recommendation", "")
    consistent = fund_rec == risk_rec
    checks.append({
        "check": "Empfehlung konsistent zwischen Fundamental- und Risk-Agent",
        "result": "bestanden" if consistent else "Warnung",
        "comment": f"Fundamental={fund_rec}, Risk={risk_rec}",
    })

    return checks


def _scenario_expected_price(risk_output) -> float | None:
    """
    Quick-Fix: Berechnet den probabilitäts-gewichteten Erwartungswert des
    Price Targets aus den Bear/Base/Bull-Szenarien des Risk-Agenten.

    Returns:
        float: Σ (probability_i/100 × price_target_i), oder
        None: wenn Szenarien fehlen/unvollständig sind oder die
              Wahrscheinlichkeiten nicht plausibel auf ~100 summieren.
    """
    scenarios = _extract(risk_output, "scenarios", [])
    if not scenarios or len(scenarios) < 2:
        return None

    total_prob = 0.0
    weighted_sum = 0.0
    for s in scenarios:
        if isinstance(s, dict):
            prob = s.get("probability_pct")
            target = s.get("price_target")
        else:
            prob = getattr(s, "probability_pct", None)
            target = getattr(s, "price_target", None)
        if not isinstance(prob, (int, float)) or not isinstance(target, (int, float)):
            return None
        if target <= 0:
            return None
        total_prob += float(prob)
        weighted_sum += float(prob) / 100.0 * float(target)

    if not (95.0 <= total_prob <= 105.0):
        return None

    return round(weighted_sum, 2)


def _build_aggregation_block(
    fundamental_output,
    news_output,
    risk_output,
    business_model_classification: dict | None,
    agent_confidence_scores: dict | None,
    revised_estimates: dict | None = None,
    forward_estimates: dict | None = None,
    thematic_analysis: dict | None = None,
    optionality_analysis: dict | None = None,
) -> str:
    """
    Berechnet die finalen Gewichte für die Synthese DETERMINISTISCH und
    formatiert sie als Direktive für den Supervisor-Prompt.

    Logik:
      1) Basis-Gewichte aus Classifier (oder Fallback 0.75/0.10/0.15)
      2) Confidence-Adjustment: jeder Agent wird mit seinem self_confidence
         multipliziert, dann re-normalisiert.
      3) Sentiment-Override: bei sehr schlechtem Sentiment (≤3/10) wird
         News/Risk angehoben (wie bisher).
      4) DCF-Cap: bei dcf_applicable=False wird das Fundamental-Gewicht
         auf 0.45 gedeckelt.
      5) Phase 2: Makro-revidierte Estimates werden als Direktive eingebettet.
    """
    # ── 1) Basis-Gewichte aus Classifier ──────────────────────────────────
    bmt = "growth_with_revenue"
    dcf_applicable = True
    base_weights = {"fundamental": 0.75, "news": 0.10, "risk": 0.15}

    # Thematic nur als Bucket aufnehmen, wenn eine Thematic-Analyse vorliegt
    _has_thematic = bool(thematic_analysis and isinstance(thematic_analysis, dict)
                         and thematic_analysis.get("trends"))

    if business_model_classification and isinstance(business_model_classification, dict):
        bmt = business_model_classification.get("business_model_type", bmt)
        dcf_applicable = bool(business_model_classification.get("dcf_applicable", True))
        suggested = business_model_classification.get("suggested_weights", {})
        if isinstance(suggested, dict) and suggested:
            base_weights = {
                "fundamental": float(suggested.get("fundamental", base_weights["fundamental"])),
                "news":        float(suggested.get("news",        base_weights["news"])),
                "risk":        float(suggested.get("risk",        base_weights["risk"])),
            }
            _tw = float(suggested.get("thematic", 0.0) or 0.0)
            if _has_thematic and _tw > 0:
                base_weights["thematic"] = _tw
            s = sum(base_weights.values()) or 1.0
            base_weights = {k: v / s for k, v in base_weights.items()}

    # ── 2) Confidence-Adjustment ──────────────────────────────────────────
    conf = {"fundamental": 0.70, "news": 0.70, "risk": 0.70}
    if "thematic" in base_weights:
        conf["thematic"] = 0.60  # Default; Trends inhärent unsicherer
    if agent_confidence_scores and isinstance(agent_confidence_scores, dict):
        for k in list(conf.keys()):
            v = agent_confidence_scores.get(k)
            if isinstance(v, (int, float)):
                conf[k] = max(0.0, min(1.0, float(v)))
    # Thematic-Confidence direkt aus der Analyse, falls vorhanden
    if _has_thematic and isinstance(thematic_analysis.get("self_confidence"), (int, float)):
        conf["thematic"] = max(0.0, min(1.0, float(thematic_analysis["self_confidence"])))

    adj_weights = {k: base_weights[k] * conf[k] for k in base_weights}
    s_adj = sum(adj_weights.values()) or 1.0
    adj_weights = {k: v / s_adj for k, v in adj_weights.items()}

    # ── 3) Sentiment-Override (≤3/10) ─────────────────────────────────────
    sentiment_score = None
    if isinstance(news_output, dict):
        sentiment_score = news_output.get("overall_sentiment_score")
    elif news_output is not None:
        sentiment_score = getattr(news_output, "overall_sentiment_score", None)

    sentiment_override_applied = False
    if isinstance(sentiment_score, (int, float)) and sentiment_score <= 3:
        shift = min(0.15, adj_weights["fundamental"] - 0.30)
        if shift > 0:
            adj_weights["fundamental"] -= shift
            adj_weights["news"] += shift / 2
            adj_weights["risk"] += shift / 2
            sentiment_override_applied = True
        s2 = sum(adj_weights.values()) or 1.0
        adj_weights = {k: v / s2 for k, v in adj_weights.items()}

    # ── 4) DCF-Cap bei nicht anwendbarem DCF ──────────────────────────────
    dcf_cap_applied = False
    if not dcf_applicable and adj_weights["fundamental"] > 0.45:
        overflow = adj_weights["fundamental"] - 0.45
        adj_weights["fundamental"] = 0.45
        adj_weights["news"] += overflow * 0.6
        adj_weights["risk"] += overflow * 0.4
        s3 = sum(adj_weights.values()) or 1.0
        adj_weights = {k: v / s3 for k, v in adj_weights.items()}
        dcf_cap_applied = True

    # ── Format Block ──────────────────────────────────────────────────────
    def _pct(x: float) -> str:
        return f"{x*100:.1f}%"

    notes = []
    notes.append(f"Geschäftsmodell-Typ: **{bmt}**")
    notes.append(f"DCF anwendbar: **{'JA' if dcf_applicable else 'NEIN'}**")
    if sentiment_override_applied:
        notes.append(
            f"⚠ Sentiment-Override aktiv (Score {sentiment_score}/10 ≤ 3): "
            f"News + Risk angehoben."
        )
    if dcf_cap_applied:
        notes.append(
            "⚠ DCF-Cap aktiv: Fundamental-Gewicht auf 45% gedeckelt, "
            "weil DCF strukturell unsicher ist (Pre-Revenue/Optionality)."
        )
    notes.append(
        f"Confidence-Adjustment: Fund={conf['fundamental']:.2f}, "
        f"News={conf['news']:.2f}, Risk={conf['risk']:.2f}"
        + (f", Thematic={conf['thematic']:.2f}" if "thematic" in adj_weights else "")
    )

    _thematic_weight_line = (
        f"- **Thematic/Megatrends: {_pct(adj_weights['thematic'])}**\n"
        if "thematic" in adj_weights else ""
    )
    _thematic_formula = (
        f" + (Thematic_Component × {adj_weights['thematic']:.3f})"
        if "thematic" in adj_weights else ""
    )
    _thematic_score_def = (
        "  Thematic_Component (aus net_thematic_assessment):\n"
        "    starker rückenwind: +20\n"
        "    rückenwind:         +10\n"
        "    neutral:             0\n"
        "    gegenwind:          -10\n"
        "    starker gegenwind:  -20\n"
        if "thematic" in adj_weights else ""
    )

    _avg_conf = sum(conf.values()) / len(conf)

    block = (
        "\n## AGGREGATIONS-DIREKTIVE (DETERMINISTISCH, ZWINGEND ANWENDEN)\n\n"
        f"### Effektive Gewichte für diese Analyse:\n"
        f"- **Fundamental: {_pct(adj_weights['fundamental'])}**\n"
        f"- **News/Sentiment: {_pct(adj_weights['news'])}**\n"
        f"- **Risk/Advocatus: {_pct(adj_weights['risk'])}**\n"
        f"{_thematic_weight_line}\n"
        f"### Begründung:\n"
        + "\n".join(f"- {n}" for n in notes)
        + "\n\n"
        "### Score-Berechnung (NUTZE DIESE FORMEL):\n"
        "  Upside_Pct = (fair_value − current_price) / current_price × 100\n"
        "  Sentiment_Component = (overall_sentiment_score / 10 × 100 − 50)  # zentriert um 0\n"
        "  Risk_Component:\n"
        "    Keine Conviction Killers aktiv: +10\n"
        "    1 Conviction Killer aktiv:        0\n"
        "    2+ Conviction Killers aktiv:    -15\n"
        "    Makro headwind:                   -5\n"
        "    Makro tailwind:                   +5\n"
        "    Industry tailwind:                +5\n"
        "    Industry headwind:                -5\n"
        + _thematic_score_def
        + f"\n  Score = (Upside_Pct × {adj_weights['fundamental']:.3f})"
        f" + (Sentiment_Component × {adj_weights['news']:.3f})"
        f" + (Risk_Component × {adj_weights['risk']:.3f})"
        f"{_thematic_formula}\n\n"
        "### Score → Empfehlung:\n"
        "  Score > 12:        KAUFEN\n"
        "  Score 4 bis 12:    ÜBERGEWICHTEN\n"
        "  Score -4 bis 4:    HALTEN\n"
        "  Score -12 bis -4:  UNTERGEWICHTEN\n"
        "  Score < -12:       VERKAUFEN\n\n"
        "### Conviction Level:\n"
        "  hoch:    durchschnittliche Agent-Confidence ≥ 0.75 UND klare Score-Richtung\n"
        f"  (Ø-Confidence aktuell: {_avg_conf:.2f})\n"
        "  mittel:  Ø-Confidence 0.55–0.75\n"
        "  niedrig: Ø-Confidence < 0.55 ODER Score nahe Schwelle\n\n"
    )

    # ── Phase 2 Fix: Sondereffekt-Warnung (unabhängig von Adjustments) ─────
    if revised_estimates and isinstance(revised_estimates, dict) \
            and revised_estimates.get("oneoff_flags"):
        flags = revised_estimates["oneoff_flags"]
        oneoff_block = (
            "### ⚠ SONDEREFFEKT-WARNUNG (automatisch erkannt):\n"
        )
        for fl in flags:
            oneoff_block += (
                f"  • {fl.get('year', '?')} ({fl.get('severity', '?')}): "
                f"{fl.get('detail', '')}\n"
            )
        oneoff_block += (
            "ANWEISUNG: Erwähne diesen Sondereffekt EXPLIZIT im final_reasoning "
            "und in einer quality_checks-Zeile. Stelle klar, dass das betroffene "
            "Ist-Jahr nicht repräsentativ für die operative Ertragskraft ist und "
            "die Forward-Estimates bewusst auf normalisierten Werten beruhen.\n\n"
        )
        block += oneoff_block

    # ── Phase 2: Makro-Revisions-Direktive ────────────────────────────────
    if revised_estimates and isinstance(revised_estimates, dict) \
            and revised_estimates.get("adjustments_applied"):
        re_block = (
            "### MAKRO-REVIDIERTE FORWARD-ESTIMATES (Phase 2 — deterministisch berechnet):\n"
            f"{revised_estimates.get('summary', '')}\n\n"
            "Angewendete Treiber (mit Transmission-Chain):\n"
        )
        for a in revised_estimates["adjustments_applied"]:
            re_block += (
                f"  • [{a.get('driver_category', '?')}] {a.get('driver', '?')}: "
                f"{a.get('applied_delta_pct', 0):+.2f}pp auf {a.get('affected_metric', '?')} "
                f"(Range {a.get('delta_range_pct')}, Conf: {a.get('confidence')}, "
                f"Dämpfung: {a.get('dampening_factor')})\n"
                f"    Kette: {a.get('transmission_chain', '-')}\n"
            )
        ifv = revised_estimates.get("indicative_fair_value_adjusted")
        re_block += (
            "\nANWEISUNGEN:\n"
            "  1. Nutze in der consensus_estimates-Tabelle die REVIDIERTEN Werte für "
            "die Forward-Jahre (E) und markiere sie in der source-Spalte als "
            "'Makro-revidiert'.\n"
            "  2. Erwähne die wichtigsten Treiber + Transmission-Chains explizit "
            "im final_reasoning unter 'Makro:'.\n"
        )
        if ifv is not None and dcf_applicable:
            re_block += (
                f"  3. Der makro-adjustierte indikative Fair Value beträgt {ifv:.2f} "
                f"(EPS-Effekt {revised_estimates.get('eps_delta_pct', 0):+.2f}% linear "
                f"auf den Fundamental-Fair-Value). Nutze für Upside_Pct in der "
                f"Score-Formel DIESEN adjustierten Wert statt des originalen "
                f"fair_value — und weise die Differenz im final_reasoning aus.\n"
            )
        elif ifv is not None:
            re_block += (
                f"  3. Indikativer makro-adjustierter Fair Value: {ifv:.2f} — bei "
                f"diesem Unternehmen (DCF nicht anwendbar) NUR als Kontext erwähnen, "
                f"das Price Target folgt dem Szenario-Erwartungswert (siehe unten).\n"
            )
        block += re_block + "\n"

    # ── Forward-Estimate-Agent: hergeleitete Wachstums-Projektion ──────────
    if forward_estimates and isinstance(forward_estimates, dict) \
            and forward_estimates.get("projections"):
        fe = forward_estimates
        fe_block = (
            "### FORWARD-ESTIMATES (Wachstums-Projektion — HÖCHSTE PRIORITÄT für Estimates):\n"
            f"These: {fe.get('overall_thesis', '')}\n"
            f"Basis-Jahr: {fe.get('base_year', '?')} "
            f"(Umsatz {fe.get('base_revenue_bn', '?')} Mrd"
            f"{', normalisiert' if fe.get('base_year_is_normalized') else ''})\n"
            f"Zentrale Treiber: {', '.join(fe.get('key_growth_drivers', []))}\n\n"
            "Projizierte Jahre:\n"
        )
        for p in fe["projections"]:
            flag = p.get("plausibility_flag", "")
            dev = p.get("deviation_from_consensus", "")
            fe_block += (
                f"  • {p.get('year','?')}: Umsatz {p.get('revenue_bn','?')} Mrd "
                f"({p.get('revenue_growth_pct','?'):+.1f}% YoY), "
                f"EBITDA-Marge {p.get('ebitda_margin_pct','?')}%, "
                f"EPS {p.get('eps','?')}\n"
                f"    Begründung: {p.get('growth_rationale','')}\n"
            )
            if dev:
                fe_block += f"    vs. Konsens: {dev}\n"
            if flag:
                fe_block += f"    {flag}\n"
        fe_block += (
            "\nANWEISUNGEN:\n"
            "  1. Diese Forward-Estimates sind die PRIMÄRE Quelle für die "
            "consensus_estimates-Tabelle der Forward-Jahre (E). Sie spiegeln eine "
            "echte Wachstums-These wider, nicht eine Median-Fortschreibung.\n"
            "  2. Das 12-Monats-Kursziel/der Fair Value MUSS auf diesen Projektionen "
            "beruhen (Forward-EPS × angemessenes Multiple, bzw. DCF mit diesen Cashflows).\n"
            "  3. Erkläre die Wachstums-These im final_reasoning unter 'Fundamental:'.\n"
            "  4. Bei Plausibilitäts-Warnungen: prüfe die Begründung kritisch und "
            "erwähne die Unsicherheit, aber kappe das Wachstum NICHT automatisch.\n"
            "  5. Konsens-Abweichungen sind legitim und sollen als bewusster "
            "Unterschied zur Street ausgewiesen werden (Wettbewerbsvorteil).\n"
            "  6. VORRANG-REGEL: Diese Projektion ERSETZT die deterministische "
            "Makro-Revision oben für die Forward-Jahres-Werte (Umsatz/EBITDA/EPS). "
            "Die Makro-Revision dient nur noch als Cross-Check — wenn beide stark "
            "abweichen, erwähne das, aber nutze die Wachstums-Projektion als Basis. "
            "Die fortgeschriebenen Effizienz-Ratios (ROIC, ND/EBITDA, FCF-Marge) aus "
            "der Makro-Revision bleiben gültig und werden auf die projizierten "
            "Umsätze angewandt.\n\n"
        )
        block += fe_block

    # ── Phase 3: Thematic-Kontext ─────────────────────────────────────────
    if thematic_analysis and isinstance(thematic_analysis, dict) \
            and thematic_analysis.get("trends"):
        ta = thematic_analysis
        th_block = (
            "### THEMATISCHE ANALYSE (Megatrends, Phase 3):\n"
            f"Netto-Einschätzung: {ta.get('net_thematic_assessment', '?')}\n"
            f"These: {ta.get('thematic_thesis', '')}\n"
            f"Wachstums-Implikation: {ta.get('growth_rate_implication', '')}\n\n"
            "Identifizierte Trends:\n"
        )
        for t in ta["trends"]:
            th_block += (
                f"  • {t.get('trend','?')} ({t.get('relevance','?')}, "
                f"{t.get('adoption_stage','?')}): {t.get('growth_contribution','')}\n"
                f"    Positionierung: {t.get('company_positioning','')}\n"
            )
        th_block += (
            "\nANWEISUNGEN:\n"
            "  1. Die thematische Einschätzung fliesst über die Thematic_Component "
            "in den Score ein (siehe Formel oben).\n"
            "  2. Erwähne die zentralen Trends im final_reasoning unter 'Thematic:'.\n"
            "  3. In der macro_ampel: nutze die Trends für die Kategorie 'Branche'.\n"
            "  4. Die Trends sind bereits in die Forward-Estimates eingeflossen — "
            "vermeide Doppelzählung im Fair Value.\n\n"
        )
        block += th_block

    block += "### WICHTIG für Price Target:\n"
    if not dcf_applicable:
        # Phase 4: Optionality-Bewertung hat Vorrang (präziser als Szenario-Mittel)
        _opt_val = None
        if optionality_analysis and isinstance(optionality_analysis, dict):
            _ov = optionality_analysis.get("probability_weighted_value")
            if isinstance(_ov, (int, float)):
                _opt_val = float(_ov)

        _ev = _scenario_expected_price(risk_output)

        if _opt_val is not None:
            runway = optionality_analysis.get("runway_months", "n/v")
            risk_lvl = optionality_analysis.get("dilution_risk", "?")
            block += (
                f"  ⚠ OPTIONALITY-BEWERTUNG (Phase 4) ist hier der PRIMÄRE Anker —\n"
                f"  DCF ist ungültig (Pre-Revenue). Das Price Target basiert auf der\n"
                f"  wahrscheinlichkeitsgewichteten Real-Options-Bewertung:\n"
                f"\n"
                f"    price_target = {_opt_val:.2f}\n"
                f"    (= Σ Szenario-Pfad-Wahrscheinlichkeit × Wert je Aktie,\n"
                f"     inkl. Cash-Runway {runway} Monate, Verwässerungsrisiko {risk_lvl})\n"
                f"\n"
                f"  Setze EXAKT diesen Wert als price_target und berechne upside_downside_pct.\n"
                f"  Begründe im final_reasoning: 'Price Target = Real-Options-Erwartungswert\n"
                f"  (TAM × Adoption × Marktanteil, Cash-Runway-bereinigt); DCF verworfen.'\n"
                f"  ⚠ Erwähne die binäre Natur: Totalverlust ist ein realistisches Szenario.\n"
            )
            if _ev is not None and abs(_ev - _opt_val) / max(_opt_val, 0.01) > 0.30:
                block += (
                    f"  (Cross-Check: Risk-Szenario-Mittel {_ev:.2f} weicht >30% ab — "
                    f"erwähne die Spannbreite als Unsicherheit.)\n"
                )
        elif _ev is not None:
            block += (
                f"  ⚠ DCF-Fair-Value ist hier UNGÜLTIG und darf NICHT ins Price Target\n"
                f"  einfliessen — auch nicht als Mittelwert-Komponente, Anker oder\n"
                f"  'konservative Abrundung'. Das Price Target ist DETERMINISTISCH:\n"
                f"\n"
                f"    price_target = {_ev:.2f}\n"
                f"    (= Σ probability_i × target_i aus den Risk-Szenarien)\n"
                f"\n"
                f"  Setze EXAKT diesen Wert in das Feld price_target und berechne\n"
                f"  upside_downside_pct gegen den aktuellen Kurs.\n"
                f"  Begründe im final_reasoning: 'Price Target = Szenario-Erwartungswert;\n"
                f"  DCF verworfen wegen Pre-Revenue/Optionality (dcf_applicable=False).'\n"
            )
        else:
            block += (
                "  ⚠ DCF-basiertes Price Target ist hier NICHT zulässig.\n"
                "  Risk-Szenarien fehlen oder sind unplausibel — nutze als Fallback\n"
                "  Peer-Multiples-Median × Forward-Umsatz und markiere die strukturelle\n"
                "  Unsicherheit explizit im final_reasoning.\n"
            )
    else:
        block += (
            "  DCF-Fair-Value ist primärer Anker, plausibilisiert durch Multiples-Range.\n"
            "  Bei Diskrepanz >20% zwischen DCF und Peer-Median-Multiple: "
            "nimm Mittelwert und erkläre die Diskrepanz.\n"
        )
    return block


def synthesize_memo(
    ticker: str,
    fundamental_output,
    news_output,
    risk_output,
    quality_checks=None,
    consistency_score=None,
    business_model_classification: dict | None = None,
    agent_confidence_scores: dict | None = None,
    revised_estimates: dict | None = None,
    forward_estimates: dict | None = None,
    thematic_analysis: dict | None = None,
    optionality_analysis: dict | None = None,
    anomaly_flags: list | None = None,
    structural_context: str | None = None,
) -> dict:
    """
    Führt nur die Supervisor-Synthese durch — Agenten-Outputs bereits vorhanden.
    Wird von app.py und vom LangGraph supervisor_node genutzt.

    quality_checks: falls None, werden sie intern berechnet (Rückwärtskompatibilität)
    consistency_score: falls übergeben, wird er als Kontext an den LLM weitergegeben

    business_model_classification: Output des Phase-1-Classifiers (suggested_weights,
        business_model_type, dcf_applicable etc.). None → Fallback 75/10/15.
    agent_confidence_scores: {"fundamental": float, "news": float, "risk": float}
    revised_estimates: Output der Phase-2-Estimate-Revision-Engine (oder None).
    """
    if quality_checks is None:
        quality_checks = _build_quality_checks(fundamental_output, news_output, risk_output)

    macro_indicators = _extract(news_output, "macro_indicators", [])
    industry_factors = _extract(news_output, "industry_factors", [])
    macro_risks_ignored = _extract(risk_output, "macro_risks_ignored", [])
    conviction_killers = _extract(risk_output, "conviction_killers", [])

    macro_context = ""
    if macro_indicators:
        macro_context = "\n### MAKRO-INDIKATOREN (News-Agent):\n"
        for m in macro_indicators:
            if isinstance(m, dict):
                macro_context += f"  • [{m.get('impact_on_company')}] {m.get('indicator')}: {m.get('mechanism')}\n"
            else:
                macro_context += f"  • [{m.impact_on_company}] {m.indicator}: {m.mechanism}\n"

    industry_context = ""
    if industry_factors:
        industry_context = "\n### INDUSTRIE-FAKTOREN (News-Agent):\n"
        for f in industry_factors:
            if isinstance(f, dict):
                industry_context += f"  • [{f.get('direction')}] {f.get('topic')}: {f.get('mechanism')}\n"
            else:
                industry_context += f"  • [{f.direction}] {f.topic}: {f.mechanism}\n"

    risk_context = ""
    if macro_risks_ignored:
        risk_context = "\n### VOM FUNDAMENTAL-AGENT IGNORIERTE MAKRO-RISIKEN:\n"
        for r in macro_risks_ignored:
            risk_context += f"  • {r}\n"

    killer_context = ""
    if conviction_killers:
        killer_context = "\n### CONVICTION KILLERS (Risk-Agent):\n"
        for k in conviction_killers:
            if isinstance(k, dict):
                killer_context += f"  [!]{k.get('description')} → Monitor: {k.get('monitoring_indicator')}\n"
            else:
                killer_context += f"  [!]{k.description} → Monitor: {k.monitoring_indicator}\n"

    quality_context = "\n### QUALITÄTSPRÜFUNG ERGEBNISSE:\n"
    for c in quality_checks:
        quality_context += f"  [{c['result']}] {c['check']}: {c['comment']}\n"
    if consistency_score is not None:
        quality_context += f"  [info] Vorab-Konsistenz-Score (deterministisch): {consistency_score}/10\n"

    # ── Neue Felder: Full Financials + Peer Comparison ────────────────────────
    full_financials  = _extract(fundamental_output, "_full_financials",  [])
    peer_comparison  = _extract(fundamental_output, "_peer_comparison",  {})

    fin_context = ""
    if full_financials:
        fin_context = "\n### VOLLSTÄNDIGE FINANZÜBERSICHT (6 Jahre, direkt übernehmen):\n"
        fin_context += json.dumps(full_financials, ensure_ascii=False) + "\n"

    peer_context = ""
    if peer_comparison:
        peer_context = "\n### PEER-VERGLEICH (direkt übernehmen):\n"
        peer_context += json.dumps(peer_comparison, ensure_ascii=False) + "\n"
        vs_avg = peer_comparison.get("subject_vs_avg", {})
        if vs_avg:
            peer_context += "Subject vs. Sektor-Ø: " + ", ".join(
                f"{k}: {v}" for k, v in vs_avg.items()
            ) + "\n"

    # ── Anomalie-Kontext (corporate_actions_node) ──────────────────────────────
    anomaly_context = ""
    if anomaly_flags:
        anomaly_context = "\n### ⚠ STRUKTURELLE ANOMALIEN (automatisch erkannt):\n"
        for fl in anomaly_flags:
            if isinstance(fl, dict):
                anomaly_context += f"  • [{fl.get('type', '?')}] {fl.get('note', '')}\n"
            else:
                anomaly_context += f"  • {fl}\n"
        if structural_context:
            anomaly_context += (
                f"\nKontext / Erklärung (Corporate Actions):\n{structural_context}\n"
                "ANWEISUNG: Erwähne diese strukturellen Anomalien im final_reasoning "
                "und in einem quality_check-Eintrag. YoY-Vergleiche ggf. als "
                "Pro-forma-Basis kennzeichnen.\n"
            )
        anomaly_context += "\n"

    # ── Phase 1/2: Confidence-gewichtete Aggregation (deterministisch) ────────
    aggregation_block = _build_aggregation_block(
        fundamental_output=fundamental_output,
        news_output=news_output,
        risk_output=risk_output,
        business_model_classification=business_model_classification,
        agent_confidence_scores=agent_confidence_scores,
        revised_estimates=revised_estimates,
        forward_estimates=forward_estimates,
        thematic_analysis=thematic_analysis,
        optionality_analysis=optionality_analysis,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SUPERVISOR_PROMPT),
        ("human", """Synthetisiere das finale Investment Memo für {ticker} ({company}).

{aggregation_block}

## FUNDAMENTAL-ANALYSE:
{fundamental_json}

## NEWS/SENTIMENT-ANALYSE:
{news_json}

## RISK/ADVOCATUS-DIABOLI-ANALYSE:
{risk_json}

{anomaly_context}
{macro_context}
{industry_context}
{risk_context}
{killer_context}
{quality_context}
{fin_context}
{peer_context}

AUFGABEN:
1. Übernimm die quality_checks aus dem Qualitätsprüfungs-Kontext oben (ergänze ggf.)
2. Baue die valuation_table aus den key_metrics der Fundamentalanalyse
3. Baue consensus_estimates: 2 Jahre Actual aus key_metrics + 3 Jahre Estimate aus consensus_estimates/Finanzkennzahlen — bei vorhandener Makro-Revision die REVIDIERTEN Forward-Werte verwenden
4. Übernimm scenarios aus dem Risk-Agent (Bear/Base/Bull, Summe=100%)
5. Baue macro_ampel mit genau 4 Einträgen: Makro, Branche, Unternehmen, Konkurrenz
6. Übernimm conviction_killers aus dem Risk-Agent
7. Treffe finale Empfehlung mit dynamisch gewichtetem Conviction Level
8. final_reasoning im Format: "Fundamental: [X] | Makro: [Y] | Risk: [Z] | Gewichtetes Fazit: [W]"
9. Übernimm full_financials EXAKT aus dem Kontext oben (keine Änderungen)
10. Übernimm peer_comparison EXAKT aus dem Kontext oben (keine Änderungen)
11. Erwähne in final_reasoning ob Peer-Bewertung Empfehlung stützt oder widerspricht
12. ⚠️ NUTZE die AGGREGATIONS-DIREKTIVE oben — die finalen Gewichte und (falls
    vorgegeben) das Price Target sind dort deterministisch vorgegeben. Berechne
    den Score gemäss Formel und mappe auf die Empfehlung. Erwähne in
    final_reasoning explizit die effektiven Gewichte.
13. executive_summary: Schreibe 3-5 Sätze in EINFACHER, ALLTÄGLICHER Sprache
    für einen interessierten Laien OHNE Finanzausbildung. VERBOTEN sind
    Fachbegriffe wie EV/EBITDA, DCF, Multiple, Forward-P/E, Conviction.
    Stattdessen: "Die Aktie ist im Vergleich zu ähnlichen Firmen eher teuer/
    günstig", "Das Unternehmen verdient stabil/wenig Geld", etc.
    Beantworte: (a) Was macht die Firma in einem Satz? (b) Ist die Aktie
    aktuell teuer oder günstig und warum? (c) Was empfehlen wir und was ist
    der EINE wichtigste Grund? (d) Was ist das grösste Risiko?
    Stell dir vor, du erklärst es einem klugen Freund, der nichts mit Finanzen
    am Hut hat. Schreibe flüssige Sätze, keine Stichworte.
14. summary_bottom_line: EIN Satz (max. 25 Wörter), die Kernaussage in
    einfacher Sprache. Das ist das Erste, was der Leser sieht.

WICHTIG zur Lesbarkeit:
- final_reasoning bleibt technisch (für Experten), aber schreibe die einzelnen
  Teile (Fundamental/Makro/Risk/Fazit) als VOLLSTÄNDIGE SÄTZE, nicht als
  abgehackte Stichwort-Fragmente. Auch der Experte will lesen können.
- executive_summary und summary_bottom_line sind die laienverständliche Ebene.

Datum heute: {today}
Gib das Ergebnis als JSON zurück."""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker": ticker,
        "company": _extract(fundamental_output, "company", ticker),
        "aggregation_block": aggregation_block,
        "fundamental_json": json.dumps(
            {k: v for k, v in (fundamental_output.items() if isinstance(fundamental_output, dict)
                               else fundamental_output.__dict__.items())
             if not k.startswith("_")},
            indent=2, ensure_ascii=False
        ),
        "news_json": json.dumps(news_output, indent=2, ensure_ascii=False),
        "risk_json": json.dumps(risk_output, indent=2, ensure_ascii=False),
        "anomaly_context": anomaly_context,
        "macro_context": macro_context,
        "industry_context": industry_context,
        "risk_context": risk_context,
        "killer_context": killer_context,
        "quality_context": quality_context,
        "fin_context": fin_context,
        "peer_context": peer_context,
        "today": date.today().isoformat(),
        "format_instructions": parser.get_format_instructions(),
    })

    # Neue Felder direkt aus fundamental_output übernehmen wenn LLM sie weglässt
    if isinstance(result, dict):
        if not result.get("full_financials") and full_financials:
            result["full_financials"] = full_financials
        if not result.get("peer_comparison") and peer_comparison:
            result["peer_comparison"] = peer_comparison

    # ── Hartes Price-Target-Override bei dcf_applicable=False ──────────────
    # Doppelter Boden: falls der LLM die Aggregations-Direktive ignoriert hat,
    # wird das Price Target deterministisch gesetzt. Vorrang:
    #   1. Optionality-Bewertung (Phase 4, präziser: Cash-Runway + TAM)
    #   2. Szenario-Erwartungswert (Quick-Fix-Fallback)
    if (
        isinstance(result, dict)
        and business_model_classification
        and isinstance(business_model_classification, dict)
        and not business_model_classification.get("dcf_applicable", True)
    ):
        _target = None
        _method = None
        if optionality_analysis and isinstance(optionality_analysis, dict):
            _ov = optionality_analysis.get("probability_weighted_value")
            if isinstance(_ov, (int, float)):
                _target = float(_ov)
                _method = "optionality_real_options"
        if _target is None:
            _ev = _scenario_expected_price(risk_output)
            if _ev is not None:
                _target = _ev
                _method = "scenario_expected_value"

        if _target is not None:
            _old_pt = result.get("price_target")
            if not isinstance(_old_pt, (int, float)) or abs(_old_pt - _target) / max(_target, 0.01) > 0.02:
                result["price_target"] = _target
                result["price_target_method"] = _method
                result["price_target_llm_original"] = _old_pt
                cp = result.get("current_price")
                if not isinstance(cp, (int, float)) or cp <= 0:
                    cp = _extract(fundamental_output, "current_price", None)
                if isinstance(cp, (int, float)) and cp > 0:
                    result["upside_downside_pct"] = round((_target - cp) / cp * 100, 2)
                _label = ("Real-Options-Erwartungswert" if _method == "optionality_real_options"
                          else "Szenario-Erwartungswert")
                result["final_reasoning"] = (
                    result.get("final_reasoning", "")
                    + f" │ [Override] Price Target deterministisch auf {_target:.2f} gesetzt "
                    f"({_label}; LLM-Wert {_old_pt} verworfen, da dcf_applicable=False)."
                )

    # ── Harte Degradation bei gescheitertem Fundamental-Agent ───────────────
    # Kein "stilles" Memo mit falscher Sicherheit: Flag setzen + Conviction
    # deterministisch auf "niedrig" begrenzen, unabhängig davon was der LLM
    # dazu geschrieben hat.
    if isinstance(result, dict):
        if _fundamental_failed(fundamental_output):
            missing = list(result.get("missing_components") or [])
            if "fundamental" not in missing:
                missing.append("fundamental")
            result["missing_components"]  = missing
            result["analysis_incomplete"] = True
            result["conviction_level"]    = "niedrig"
            result["final_reasoning"] = (
                result.get("final_reasoning", "")
                + " │ [ANALYSE UNVOLLSTÄNDIG] Fundamentalanalyse nach allen Retries "
                "fehlgeschlagen — Conviction auf 'niedrig' begrenzt."
            )
        else:
            result.setdefault("analysis_incomplete", False)
            result.setdefault("missing_components", [])

    return result


def run_supervisor(ticker: str) -> dict:
    """Wrapper für Rückwärtskompatibilität — delegiert an LangGraph."""
    from graph.graph import run_analysis
    return run_analysis(ticker)


def format_investment_memo(result: dict) -> str:
    """Wandelt den JSON Output in ein lesbares Investment Memo um."""
    currency = result.get("currency", "")
    memo = f"""
{'='*60}
INVESTMENT MEMO — {result.get('company')} ({result.get('ticker')})
{'='*60}

EMPFEHLUNG:  {result.get('final_recommendation')}
CONVICTION:  {result.get('conviction_level')}
PRICE TARGET: {currency} {result.get('price_target')}
AKT. KURS:   {currency} {result.get('current_price')}
UPSIDE/DOWN: {result.get('upside_downside_pct')}%
DATUM:       {result.get('date')}

{'─'*60}
QUALITÄTSPRÜFUNG (Konsistenz: {result.get('data_consistency_score')}/10)
{'─'*60}
{result.get('consistency_notes')}

{'─'*60}
UNTERNEHMENSBESCHREIBUNG
{'─'*60}
{result.get('company_description')}

{'─'*60}
INVESTMENT CASE
{'─'*60}
{chr(10).join(
    f"• {p['point']} [{p.get('source','')}]" if isinstance(p, dict) else f"• {p}"
    for p in result.get('investment_case', [])
)}

{'─'*60}
SZENARIEN
{'─'*60}
{chr(10).join(f"[{s['name']} {s['probability_pct']}%] Kursziel: {s['price_target']} | {s['key_assumption']}" for s in result.get('scenarios', []))}

{'─'*60}
RISIKEN
{'─'*60}
{chr(10).join(f'• {r}' for r in result.get('key_risks', []))}

{'─'*60}
ADVOCATUS DIABOLI
{'─'*60}
{result.get('advocatus_diaboli_summary')}

{'─'*60}
MONITORING CHECKLIST
{'─'*60}
{chr(10).join(f'□ {c}' for c in result.get('monitoring_checklist', []))}

{'─'*60}
FINALE BEGRÜNDUNG
{'─'*60}
{result.get('final_reasoning')}

{'─'*60}
QUELLEN
{'─'*60}
{chr(10).join(f'- {s}' for s in result.get('sources', []))}

{'='*60}
"""
    return memo


if __name__ == "__main__":
    result = run_supervisor("HOLN.SW")

    with open("output_memo.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    memo = format_investment_memo(result)
    print(memo)

    with open("output_memo.txt", "w", encoding="utf-8") as f:
        f.write(memo)

    print("[OK] Memo gespeichert: output_memo.json & output_memo.txt")
