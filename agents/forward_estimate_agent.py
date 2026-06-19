"""
Forward Estimate Agent — das Herzstück der Analyse.

Leitet die Forward-Estimates (Umsatz, EBITDA, EPS für die nächsten ~3 Jahre)
aus einer ECHTEN Wachstums-These her — nicht aus dem Median der Vergangenheit.

Die zentrale Idee: Ein Analyst projiziert nicht "Durchschnitt der letzten
Jahre", sondern fragt "wohin geht dieses Unternehmen, gegeben alles was wir
über Sektor-Nachfrage, Makro-Umfeld, thematische Treiber und die
Unternehmensposition wissen?". Ein KI-Rechenzentren-Boom kann +60% Umsatz
bedeuten — der Median der NAND-Krisenjahre würde das Gegenteil suggerieren.

Inputs (alles was die vorgelagerten Agenten wissen):
  - Historische Finanzdaten (Basis-Jahr, Trajektorie, Sondereffekte)
  - Geschäftsmodell-Klassifikation (Wachstums-Profil, Zyklik)
  - News-Agent: estimate_adjustments + Makro/Sektor-Signale
  - Analysten-Konsens (NUR als Fussnote/Abgleich, nicht als Anker)

Architektur: LLM leitet pro Forward-Jahr eine begründete Wachstumsrate her,
Python rechnet die absoluten Werte sauber durch und setzt Plausibilitäts-Flags.
"""

from __future__ import annotations

import os
import sys

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.schemas import ForwardEstimateOutput
from tools.estimate_revision import detect_oneoff_effects, _num

llm = ChatOpenAI(model="gpt-5.4-mini")

# Plausibilitäts-Schwelle: oberhalb wird gewarnt (nicht gedeckelt)
_PLAUSIBILITY_YOY_WARN = 80.0   # % YoY-Umsatzwachstum


FORWARD_PROMPT = """Du bist ein Senior Equity Analyst und erstellst die
FORWARD-ESTIMATES — das Herzstück jeder Aktienanalyse. Diese Schätzungen
bestimmen direkt das 12-Monats-Kursziel.

PERIODEN-REGEL (ZWINGEND):
Das Quartalssignal unten ist ein MOMENTUM-HINWEIS, kein Jahreswert.
- Nutze run_rate_ttm als Niveau-Anker für FY+1, NICHT das raw_q_value.
- Wenn prior_year_comp_depressed=True ODER der Geschäftsmodelltyp zyklisch ist
  (memory/commodity/semis/cycl): dämpfe das YoY-Momentum stark Richtung Mid-Cycle.
  Ein +60%-Quartal aus einem Trough ist kein fortschreibbarer Run-Rate.
- Das Quartalssignal fliesst NUR in E-Spalten (Forward-Schätzungen) ein,
  NICHT in Actuals (A-Spalten) und NICHT in MultiplesEngine-Inputs.

GRUNDPRINZIP: Du projizierst NICHT den Durchschnitt der Vergangenheit.
Du leitest her, WOHIN das Unternehmen geht — basierend auf der konkreten
aktuellen Situation: Sektor-Nachfrage, thematische Treiber, Makro-Umfeld,
Zyklusposition und der spezifischen Position des Unternehmens.

Ein Beispiel der Denkweise: Steht ein NAND-Speicher-Hersteller vor einem
KI-Rechenzentren-Boom, dann kann der Forward-Umsatz +50-60% wachsen — auch
wenn der historische Schnitt flach oder negativ war. Die Vergangenheit ist
Kontext, nicht die Antwort. Umgekehrt: Droht eine Rezession und das
Unternehmen ist zyklisch, projizierst du den Abschwung, nicht die
Boom-Jahre davor.

UNTERNEHMEN: {company} ({ticker})
GESCHÄFTSMODELL-TYP: {business_model_type}
ZYKLUSPOSITION: {cycle_position}

=== HISTORISCHE FINANZDATEN (Basis & Trajektorie) ===
{historical_block}

{oneoff_block}

=== BASIS-JAHR FÜR PROJEKTION ===
Projiziere AUSGEHEND von diesem Jahr (letztes Ist, ggf. normalisiert):
  Basis-Jahr: {base_year}
  Basis-Umsatz: {base_revenue} Mrd
  Basis-EBITDA-Marge: {base_margin}%

=== MAKRO- & SEKTOR-TREIBER (vom News-Agent identifiziert) ===
{drivers_block}

=== THEMATISCHE & QUALITATIVE SIGNALE ===
{thematic_block}

=== ANALYSTEN-KONSENS (NUR FUSSNOTE — NICHT dein Anker!) ===
{consensus_block}
Der Konsens ist Referenz, nicht Ziel. Deine eigene begründete Projektion
ist das Ziel. Wenn du abweichst, ist das legitim und sogar erwünscht —
aber begründe die Abweichung in deviation_from_consensus.

=== QUARTALSSIGNAL (NUR Forward-Logik, NICHT für Actuals) ===
{quarterly_block}

────────────────────────────────────────────────────────────────────────────
DEINE AUFGABE:
Projiziere die nächsten 3 Forward-Jahre. Für JEDES Jahr:

1. revenue_growth_pct: Die Wachstumsrate YoY. Leite sie aktiv her aus:
   - struktureller Sektor-Nachfrage (wächst/schrumpft der Endmarkt?)
   - thematischen Treibern (KI-Boom, Energiewende, Bauboom, etc.)
   - Makro-Adjustments (Zinsen, FX, Konjunktur)
   - Unternehmensposition (Marktanteil, Pipeline, Guidance)
   - Zyklusposition (early/mid/late/trough)
   Wachstum kann hoch positiv ODER negativ sein. Sei realistisch zur Situation.

2. revenue_bn: Vorjahr × (1 + revenue_growth_pct/100). Rechne sauber.
   (Für das erste Jahr: Basis-Umsatz × (1 + Wachstum))

3. ebitda_margin_pct: Projizierte Marge. Berücksichtige Operating Leverage
   (bei starkem Wachstum oft Margenexpansion) oder Kostendruck.

4. ebitda_bn: revenue_bn × ebitda_margin_pct/100

5. eps: Projiziertes EPS, konsistent zur EBITDA-Entwicklung.

6. growth_rationale: KONKRETE Begründung der Wachstumsrate mit Zahlen.
   z.B. "Sektor-TAM +35% durch KI-Capex (Quelle X), Unternehmen hält 12%
   Marktanteil und gewinnt durch neue Produktlinie → +48% Umsatz FY26"

7. margin_rationale: Begründung der Margenannahme.

8. deviation_from_consensus: Falls Konsens vorliegt und du abweichst —
   Richtung + Grund. Sonst leer.

Zusätzlich:
- base_year_is_normalized: true wenn du das Basisjahr um Sondereffekte
  bereinigt hast (siehe Sondereffekt-Warnung oben).
- key_growth_drivers: die 3-5 wichtigsten Treiber, absteigend.
- overall_thesis: die übergreifende Wachstums-These in 2-3 Sätzen.
- self_confidence: wie sicher ist die Projektion? Hoch bei klaren Treibern
  und guter Datenlage, niedrig bei spekulativen Annahmen.

WICHTIG:
- Erfinde keine Wachstumsraten. Jede Zahl muss aus einem benannten Treiber folgen.
- Wenn die Treiber moderates Wachstum nahelegen, projiziere moderat.
- Wenn ein struktureller Boom/Bust vorliegt, projiziere ihn — auch wenn er
  vom historischen Schnitt stark abweicht.
- Extreme Raten (>80% YoY) sind möglich, müssen aber besonders stark
  begründet sein.

{format_instructions}

Antworte ausschliesslich als JSON nach dem Schema."""


def _build_historical_block(hist_rows: list) -> str:
    """Formatiert die historischen Ist-Jahre kompakt."""
    if not hist_rows:
        return "Keine historischen Daten verfügbar."
    lines = []
    for r in hist_rows:
        rr = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else {})
        if rr.get("type") != "A":
            continue
        lines.append(
            f"  {rr.get('year','?')}: Umsatz {rr.get('revenue_bn','-')} Mrd, "
            f"EBITDA-Marge {rr.get('ebitda_margin_pct','-')}%, "
            f"EPS {rr.get('eps_adj','-')}, ROIC {rr.get('roic_pct','-')}%"
        )
    return "\n".join(lines) if lines else "Keine Ist-Jahre gefunden."


def _pick_base_year(hist_rows: list, oneoff_flags: list) -> dict | None:
    """
    Wählt das Basisjahr: das letzte Ist-Jahr. Falls dieses als Sondereffekt
    geflaggt ist, wird der Umsatz beibehalten (Umsatz ist selten verzerrt),
    aber die Marge/EPS-Basis wird als 'normalisierungsbedürftig' markiert.
    """
    actuals = []
    for r in hist_rows:
        rr = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else {})
        if rr.get("type") == "A":
            actuals.append(rr)
    if not actuals:
        return None
    return actuals[-1]


def run_forward_estimate_agent(
    ticker: str,
    fundamental_output: dict,
    news_output: dict | None = None,
    business_model_context: dict | None = None,
    thematic_context: dict | None = None,
    consensus_estimates: dict | None = None,
    quarterly_signal: dict | None = None,
) -> dict:
    """
    Erstellt die Forward-Estimates aus einer hergeleiteten Wachstums-These.

    Returns:
        dict im ForwardEstimateOutput-Schema, plus berechnete absolute Werte
        und Plausibilitäts-Flags.
    """
    print(f"[forward_estimate] Projiziere Forward-Estimates für {ticker}...")

    company = fundamental_output.get("company", ticker) if isinstance(fundamental_output, dict) else ticker
    hist_rows = (fundamental_output.get("_full_financials")
                 or fundamental_output.get("full_financials") or []) if isinstance(fundamental_output, dict) else []

    # Sondereffekt-Erkennung (für Basis-Normalisierung)
    oneoff_flags = detect_oneoff_effects(hist_rows)
    oneoff_block = ""
    if oneoff_flags:
        oneoff_block = "⚠ SONDEREFFEKT-WARNUNG (Basisjahr ggf. normalisieren):\n"
        for f in oneoff_flags:
            oneoff_block += f"  • {f['year']}: {f['detail']}\n"

    base = _pick_base_year(hist_rows, oneoff_flags)
    if not base:
        print("[forward_estimate] ⚠ Keine Basisdaten — Agent übersprungen")
        return None

    base_year = base.get("year", "?")
    base_revenue = _num(base.get("revenue_bn"))
    base_margin = _num(base.get("ebitda_margin_pct"))

    # Treiber-Block aus News-Agent
    drivers_block = "Keine spezifischen Makro-Treiber identifiziert."
    if news_output and isinstance(news_output, dict):
        adjs = news_output.get("estimate_adjustments", [])
        macro_sum = news_output.get("macro_summary", "")
        parts = []
        if macro_sum:
            parts.append(f"Makro-Zusammenfassung: {macro_sum}")
        for a in adjs:
            aa = a if isinstance(a, dict) else (a.model_dump() if hasattr(a, "model_dump") else {})
            parts.append(
                f"  • [{aa.get('driver_category','?')}] {aa.get('driver','?')} "
                f"→ {aa.get('affected_metric','?')} {aa.get('delta_pct_low','?')}–"
                f"{aa.get('delta_pct_high','?')}pp ({aa.get('confidence','?')}): "
                f"{aa.get('transmission_chain','')}"
            )
        if parts:
            drivers_block = "\n".join(parts)

    # Thematic-Block (Phase 3 — optional, jetzt schon angebunden)
    thematic_block = "Noch kein Thematic-Agent aktiv (Phase 3)."
    if thematic_context and isinstance(thematic_context, dict):
        thematic_block = thematic_context.get("summary", str(thematic_context))

    # Konsens-Block (nur Fussnote)
    consensus_block = "Kein Analysten-Konsens verfügbar."
    if consensus_estimates and isinstance(consensus_estimates, dict):
        rev_est = consensus_estimates.get("revenue_estimates", [])
        eps_est = consensus_estimates.get("eps_estimates", [])
        parts = []
        for e in rev_est[:3]:
            parts.append(f"  Umsatz {e.get('period','?')}: Konsens {e.get('consensus','-')} "
                         f"({e.get('num_analysts','?')} Analysten)")
        for e in eps_est[:3]:
            parts.append(f"  EPS {e.get('period','?')}: Konsens {e.get('consensus','-')}")
        if parts:
            consensus_block = "\n".join(parts)

    bmt = "unknown"
    cycle = "unknown"
    if business_model_context and isinstance(business_model_context, dict):
        bmt = business_model_context.get("business_model_type", "unknown")
        cycle = business_model_context.get("cycle_position", "unknown")

    # Build quarterly signal block for the prompt
    quarterly_block = "Kein Quartalssignal verfügbar."
    if quarterly_signal and isinstance(quarterly_signal, dict):
        _is_cyclical = any(
            x in bmt.lower()
            for x in ["cycl", "memory", "commodity", "semi", "mining", "oil", "gas"]
        )
        _qs = quarterly_signal
        _metric = _qs.get("source_metric", "fcf")
        _ttm    = _qs.get("run_rate_ttm")
        _yoy    = _qs.get("yoy_comparable_growth")
        _qoq    = _qs.get("qoq_growth")
        _dep    = _qs.get("prior_year_comp_depressed", False)
        _parts  = [f"Quartalssignal ({_metric}):"]
        if _ttm is not None:
            _parts.append(f"  run_rate_ttm: {_ttm:.2f} Mrd (Summe letzte 4 Quartale) → Niveau-Anker für FY+1")
        if _yoy is not None:
            _damp = " → STARK GEDÄMPFT (Basiseffekt/Zyklus)" if (_dep or _is_cyclical) else ""
            _parts.append(f"  YoY-Wachstum letztes Q: {_yoy:+.1f}%{_damp}")
        if _qoq is not None:
            _parts.append(f"  QoQ-Wachstum: {_qoq:+.1f}%")
        if _dep:
            _parts.append(
                "  ⚠ prior_year_comp_depressed=True — Vorjahres-Q war anomal niedrig; "
                "hohes YoY überschätzt Momentum erheblich"
            )
        if _is_cyclical:
            _parts.append(
                "  ⚠ Zyklisches Geschäftsmodell — Quartalsmomentum NICHT linear "
                "fortschreiben; Richtung Mid-Cycle dämpfen"
            )
        _parts.append(
            "  STRIKT: Dieser Block fliesst NUR in E-Spalten ein, NICHT in A-Spalten "
            "und NICHT als Denomininator in der MultiplesEngine."
        )
        quarterly_block = "\n".join(_parts)

    parser = PydanticOutputParser(pydantic_object=ForwardEstimateOutput)
    prompt = ChatPromptTemplate.from_messages([("human", FORWARD_PROMPT)])
    chain = prompt | llm | parser

    try:
        result = chain.invoke({
            "ticker": ticker,
            "company": company,
            "business_model_type": bmt,
            "cycle_position": cycle,
            "historical_block": _build_historical_block(hist_rows),
            "oneoff_block": oneoff_block or "Keine Sondereffekte erkannt.",
            "base_year": base_year,
            "base_revenue": base_revenue if base_revenue is not None else "n/v",
            "base_margin": base_margin if base_margin is not None else "n/v",
            "drivers_block": drivers_block,
            "thematic_block": thematic_block,
            "consensus_block": consensus_block,
            "quarterly_block": quarterly_block,
            "format_instructions": parser.get_format_instructions(),
        })
        output = result.model_dump()
    except Exception as e:
        print(f"[forward_estimate] ⚠ Fehler: {e}")
        return None

    # ── Python-seitige Verifikation + Plausibilitäts-Flags ──────────────────
    output = _verify_and_flag(output, base_revenue)

    n_proj = len(output.get("projections", []))
    warns = sum(1 for p in output["projections"] if p.get("plausibility_flag"))
    print(
        f"[forward_estimate] → {n_proj} Jahre projiziert, "
        f"Conf: {output.get('self_confidence', 0):.2f}, "
        f"Plausibilitäts-Warnungen: {warns}"
    )
    return output


def _verify_and_flag(output: dict, base_revenue: float | None) -> dict:
    """
    Rechnet die absoluten Werte aus den Wachstumsraten konsistent nach
    (vertraut nicht blind den LLM-Absolutwerten) und setzt Plausibilitäts-Flags.
    """
    projections = output.get("projections", [])
    prev_rev = base_revenue

    for p in projections:
        growth = _num(p.get("revenue_growth_pct"))
        margin = _num(p.get("ebitda_margin_pct"))

        # Umsatz aus Wachstumsrate konsistent nachrechnen
        if prev_rev is not None and growth is not None:
            calc_rev = round(prev_rev * (1 + growth / 100.0), 4)
            p["revenue_bn"] = calc_rev
            prev_rev = calc_rev
        else:
            prev_rev = _num(p.get("revenue_bn")) or prev_rev

        # EBITDA aus Umsatz × Marge
        cur_rev = _num(p.get("revenue_bn"))
        if cur_rev is not None and margin is not None:
            p["ebitda_bn"] = round(cur_rev * margin / 100.0, 4)

        # Plausibilitäts-Flag (weiche Grenze — Warnung, keine Deckelung)
        if growth is not None and abs(growth) > _PLAUSIBILITY_YOY_WARN:
            p["plausibility_flag"] = (
                f"⚠ Aussergewöhnliches Wachstum ({growth:+.0f}% YoY > "
                f"{_PLAUSIBILITY_YOY_WARN:.0f}%) — Begründung kritisch prüfen."
            )

    output["projections"] = projections
    return output
