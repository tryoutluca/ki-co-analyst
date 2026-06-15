"""
Optionality Sub-Agent — Phase 4.

Bewertet Pre-Revenue / Deep-Tech / Optionality-Plays (Rigetti, IonQ, Joby …)
über Real-Options-Logik statt DCF. Ein DCF auf ein Unternehmen ohne stabile
Cashflows produziert Garbage — der wahre Wert liegt in der OPTION auf eine
mögliche grosse Zukunft.

Drei Bausteine:
  1. Cash-Runway (DETERMINISTISCH, Python): Wie lange reicht die Liquidität?
     Das ist die harte Realitätsprüfung — egal wie gross die Vision, wenn das
     Geld in 9 Monaten alle ist, droht Verwässerung oder Pleite.
  2. TAM × Adoption × Marktanteil (LLM): Wie gross ist die Chance, und wie
     wahrscheinlich ist sie?
  3. Szenario-Pfade → wahrscheinlichkeitsgewichteter Wert (LLM + Python):
     Erfolg / Teilerfolg / Misserfolg / Total-Loss, ehrlich gewichtet.

Läuft NUR bei business_model_type == 'optionality_play' (bzw.
requires_optionality_analysis == True). Bei allen anderen Unternehmen
übersprungen — ein reifes Cashflow-Unternehmen braucht keine Optionality-Logik.
"""

from __future__ import annotations

import os
import sys

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.schemas import OptionalityOutput

llm = ChatOpenAI(model="gpt-5.4-mini")


def _num(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        import re
        m = re.search(r"-?\d+[.,]?\d*", val.replace(",", "."))
        return float(m.group()) if m else None
    return None


def _compute_cash_runway(stock_info: dict, financials: dict) -> dict:
    """
    Deterministische Cash-Runway-Berechnung.

    Returns dict mit cash_mn, burn_mn, runway_months, dilution_risk.
    """
    cash = _num(stock_info.get("total_cash")) or _num(financials.get("total_cash_bn"))
    # total_cash kann absolut (USD) oder in Mrd sein — normalisieren auf Mio
    if cash is not None:
        # Heuristik: > 1e6 → absolut in USD, sonst in Mrd
        if cash > 1e6:
            cash_mn = cash / 1e6
        else:
            cash_mn = cash * 1000.0  # Mrd → Mio
    else:
        cash_mn = None

    fcf = _num(stock_info.get("free_cashflow_ttm")) or _num(financials.get("free_cashflow_ttm"))
    op_cf = _num(stock_info.get("operating_cashflow_ttm")) or _num(financials.get("operating_cashflow_ttm"))
    burn_source = fcf if fcf is not None else op_cf
    if burn_source is not None:
        if abs(burn_source) > 1e6:
            burn_mn = burn_source / 1e6
        else:
            burn_mn = burn_source * 1000.0
    else:
        burn_mn = None

    runway_months = None
    dilution_risk = "mittel"
    if cash_mn is not None and burn_mn is not None:
        if burn_mn < 0:  # echter Burn
            annual_burn = abs(burn_mn)
            runway_months = round(cash_mn / annual_burn * 12.0, 1)
            if runway_months < 12:
                dilution_risk = "akut"
            elif runway_months < 24:
                dilution_risk = "hoch"
            elif runway_months < 48:
                dilution_risk = "mittel"
            else:
                dilution_risk = "niedrig"
        else:
            # Positiver FCF — kein Burn
            runway_months = 999.0
            dilution_risk = "niedrig"

    return {
        "cash_mn": round(cash_mn, 1) if cash_mn is not None else "n/v",
        "burn_mn": round(burn_mn, 1) if burn_mn is not None else "n/v",
        "runway_months": runway_months if runway_months is not None else "n/v",
        "dilution_risk": dilution_risk,
    }


OPTIONALITY_PROMPT = """Du bist ein Deep-Tech-Investmentanalyst, spezialisiert
auf die Bewertung von Pre-Revenue-Unternehmen über REAL OPTIONS — nicht über
DCF. Ein DCF wäre hier wertlos, weil es keine stabilen Cashflows gibt. Der
Wert liegt in der OPTION auf eine mögliche grosse Zukunft.

UNTERNEHMEN: {company} ({ticker})
SEKTOR: {sector} | INDUSTRIE: {industry}
AKTUELLER KURS: {current_price} {currency}
MARKTKAPITALISIERUNG: {market_cap}

UNTERNEHMENSBESCHREIBUNG:
{description}

=== CASH-RUNWAY (deterministisch berechnet) ===
Liquide Mittel:        {cash_mn} Mio.
Jährlicher Burn:       {burn_mn} Mio.
Runway:                {runway_months} Monate
Verwässerungsrisiko:   {dilution_risk}

=== THEMATISCHE SIGNALE (Adoptionskurven) ===
{thematic_block}

=== NEWS / MAKRO-SIGNALE ===
{news_block}

────────────────────────────────────────────────────────────────────────────
DEINE AUFGABE: Bewerte dieses Unternehmen über Real-Options-Logik.

1. CASH-RUNWAY beurteilen (runway_assessment):
   - Übernimm die berechneten Werte oben.
   - Beurteile in 1-2 Sätzen, wie kritisch die Lage ist. Ein Runway < 12
     Monaten bedeutet akutes Verwässerungs- oder Pleiterisiko.

2. TAM × ADOPTION schätzen:
   - tam_estimate_bn: Wie gross ist der adressierbare Gesamtmarkt zum
     Zielhorizont (z.B. Quantencomputing-Markt 2032)? Nutze die thematischen
     Signale. Quantifiziere in Mrd.
   - tam_horizon_year: Für welches Jahr?
   - adoption_probability_pct: Wie wahrscheinlich setzt sich die Technologie
     kommerziell durch? Sei ehrlich — bei früher Deep-Tech oft 10-40%.
   - expected_market_share_pct: Welchen Marktanteil erreicht DIESES Unternehmen
     bei Erfolg? (Wettbewerb beachten!)

3. SZENARIO-PFADE (scenario_paths): Erstelle 3-4 Pfade, die sich auf 100%
   summieren. Typisch:
   - Durchbruch/Erfolg: Technologie skaliert, Unternehmen gewinnt → hoher Wert
   - Teilerfolg: Nische erreicht, aber kein Massenmarkt → moderater Wert
   - Misserfolg: Adoption verzögert, Verwässerung → niedriger Wert
   - Total-Loss: Pleite/Übernahme zu Schleuderpreis → ~0
   Bei Pre-Revenue mit kurzem Runway MUSS ein realistisch hoher Total-Loss-
   bzw. Misserfolgs-Anteil enthalten sein (oft 40-60% kombiniert).
   Für jeden Pfad: value_per_share (Wert je Aktie) + key_milestone.

4. probability_weighted_value: Σ(probability_i/100 × value_per_share_i).
   Das ist der faire Wert je Aktie. Rechne sauber.

5. upside_downside_pct: (probability_weighted_value − current_price) / current_price × 100

6. optionality_thesis: 2-3 Sätze. Worauf wettet der Investor konkret?

7. binary_risk_warning: Warne explizit vor dem binären Charakter — bei
   Optionality-Plays ist ein Totalverlust ein realistisches Szenario, kein
   Randrisiko.

8. self_confidence: Niedrig (0.3-0.55), denn Optionality-Bewertung ist
   inhärent spekulativ. Das ist Ehrlichkeit, kein Versagen.

WICHTIG:
- Sei NICHT euphorisch. Deep-Tech-Optionality-Plays scheitern häufiger als sie
  gelingen. Die hohe Verlustwahrscheinlichkeit muss sich in den Szenario-
  Wahrscheinlichkeiten widerspiegeln.
- Der Cash-Runway ist die harte Realitätsprüfung: kurzer Runway → höherer
  Misserfolgs-/Verwässerungsanteil.
- Quantifiziere wo möglich, aber gib zu, wenn etwas spekulativ ist.

{format_instructions}

Antworte ausschliesslich als JSON nach dem Schema."""


def run_optionality_agent(
    ticker: str,
    fundamental_output: dict | None = None,
    thematic_context: dict | None = None,
    news_output: dict | None = None,
    business_model_context: dict | None = None,
    stock_info: dict | None = None,
) -> dict | None:
    """
    Bewertet ein Optionality-Play über Real-Options-Logik.

    Returns dict im OptionalityOutput-Schema, oder None wenn nicht anwendbar
    (kein optionality_play) oder fehlgeschlagen.
    """
    # Gate: nur bei optionality_play / requires_optionality_analysis
    is_optionality = False
    if business_model_context and isinstance(business_model_context, dict):
        bmt = business_model_context.get("business_model_type")
        req = business_model_context.get("requires_optionality_analysis", False)
        is_optionality = (bmt == "optionality_play") or bool(req)

    if not is_optionality:
        print("[optionality] ⏭ Kein optionality_play — übersprungen")
        return None

    print(f"[optionality] Real-Options-Bewertung für {ticker}...")

    # Stammdaten
    if not stock_info:
        try:
            from tools.finance_tools import get_stock_info
            stock_info = get_stock_info.invoke({"ticker": ticker}) \
                if hasattr(get_stock_info, "invoke") else get_stock_info(ticker)
        except Exception:
            stock_info = {}
    if not isinstance(stock_info, dict):
        stock_info = {}

    financials = {}
    try:
        from tools.finance_tools import get_financial_statements
        financials = get_financial_statements.invoke({"ticker": ticker}) \
            if hasattr(get_financial_statements, "invoke") else {}
    except Exception:
        financials = {}
    if not isinstance(financials, dict):
        financials = {}

    # Cash-Runway deterministisch
    runway = _compute_cash_runway(stock_info, financials)

    company = stock_info.get("name", ticker)
    current_price = _num(stock_info.get("current_price"))

    # Thematic-Kontext (Adoptionskurven)
    thematic_block = "Keine thematischen Signale verfügbar."
    if thematic_context and isinstance(thematic_context, dict):
        parts = []
        if thematic_context.get("thematic_thesis"):
            parts.append(f"These: {thematic_context['thematic_thesis']}")
        for t in thematic_context.get("trends", [])[:4]:
            tt = t if isinstance(t, dict) else {}
            parts.append(
                f"  • {tt.get('trend','?')} ({tt.get('adoption_stage','?')}): "
                f"{tt.get('tam_impact','')} | {tt.get('company_positioning','')}"
            )
        if parts:
            thematic_block = "\n".join(parts)

    news_block = "Keine News-Signale."
    if news_output and isinstance(news_output, dict):
        if news_output.get("macro_summary"):
            news_block = news_output["macro_summary"]

    parser = PydanticOutputParser(pydantic_object=OptionalityOutput)
    prompt = ChatPromptTemplate.from_messages([("human", OPTIONALITY_PROMPT)])
    chain = prompt | llm | parser

    try:
        result = chain.invoke({
            "ticker": ticker,
            "company": company,
            "sector": stock_info.get("sector", "N/A"),
            "industry": stock_info.get("industry", "N/A"),
            "current_price": current_price if current_price is not None else "n/v",
            "currency": stock_info.get("currency", ""),
            "market_cap": stock_info.get("market_cap", "n/v"),
            "description": (stock_info.get("description") or "")[:1200],
            "cash_mn": runway["cash_mn"],
            "burn_mn": runway["burn_mn"],
            "runway_months": runway["runway_months"],
            "dilution_risk": runway["dilution_risk"],
            "thematic_block": thematic_block,
            "news_block": news_block,
            "format_instructions": parser.get_format_instructions(),
        })
        output = result.model_dump()
    except Exception as e:
        print(f"[optionality] ⚠ Fehler: {e}")
        return None

    # Deterministische Werte überschreiben LLM (Cash-Runway ist gerechnet)
    output["cash_position_mn"] = runway["cash_mn"]
    output["annual_burn_mn"] = runway["burn_mn"]
    output["runway_months"] = runway["runway_months"]
    output["dilution_risk"] = runway["dilution_risk"]
    output["current_price"] = current_price if current_price is not None else "n/v"

    # Wahrscheinlichkeits-gewichteten Wert verifizieren (Python)
    pwv = _verify_weighted_value(output.get("scenario_paths", []))
    if pwv is not None:
        output["probability_weighted_value"] = pwv
        if current_price and current_price > 0:
            output["upside_downside_pct"] = round((pwv - current_price) / current_price * 100, 1)

    n_paths = len(output.get("scenario_paths", []))
    print(
        f"[optionality] → {n_paths} Pfade | "
        f"Fair Value: {output.get('probability_weighted_value', 'n/v')} | "
        f"Runway: {runway['runway_months']} Mt | Risiko: {runway['dilution_risk']}"
    )
    return output


def _verify_weighted_value(paths: list) -> float | None:
    """Rechnet Σ(prob × value) sauber nach (vertraut nicht dem LLM-Wert)."""
    if not paths:
        return None
    total_prob = 0.0
    weighted = 0.0
    for p in paths:
        pp = p if isinstance(p, dict) else (p.model_dump() if hasattr(p, "model_dump") else {})
        prob = _num(pp.get("probability_pct"))
        val = _num(pp.get("value_per_share"))
        if prob is None or val is None:
            return None
        total_prob += prob
        weighted += prob / 100.0 * val
    if not (90.0 <= total_prob <= 110.0):
        return None
    return round(weighted, 2)
