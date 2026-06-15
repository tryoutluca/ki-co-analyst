"""
Classifier Agent — Phase 1 Foundation

Klassifiziert ein Unternehmen vor der Hauptanalyse in eines von 5
Geschäftsmodell-Archetypen. Daraus folgt:
  - welche Bewertungsmethoden überhaupt sinnvoll sind
  - wie der Supervisor die drei Junior-Agenten gewichtet
  - ob spezielle Sub-Engines (z.B. Optionality) später aktiviert werden

Output ist bewusst leichtgewichtig: ein einzelner LLM-Call mit
deterministischen Inputs aus get_stock_info() + get_financial_statements().

Phase 2 Erweiterung: suggested_peers — der Classifier schlägt echte
Vergleichsunternehmen vor (z.B. IonQ/D-Wave für Rigetti statt
Seagate/Western Digital aus der yfinance-Sektor-Logik).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Literal

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.finance_tools import get_stock_info, get_financial_statements


llm = ChatOpenAI(model="gpt-5.4-mini")


# ── Schema ───────────────────────────────────────────────────────────────────

BusinessModelType = Literal[
    "mature_cashflow",       # Holcim, Nestlé, Roche — stabile FCF, DCF dominant
    "growth_with_revenue",   # Snowflake, Palantir — Wachstum + reale Umsätze
    "optionality_play",      # Rigetti, IonQ, Joby — Pre-Revenue/Deep-Tech
    "cyclical",              # Bauunternehmen, Stahl, Halbleiter — Zyklus-Logik
    "financial_institution", # Banken, Versicherungen — P/B + ROE statt DCF
]


class SuggestedWeights(BaseModel):
    """Empfohlene Gewichte für die Junior-Agenten. Summe ≈ 1.0."""
    fundamental: float = Field(ge=0.0, le=1.0)
    news:        float = Field(ge=0.0, le=1.0)
    risk:        float = Field(ge=0.0, le=1.0)
    thematic:    float = Field(ge=0.0, le=1.0)


class BusinessModelClassification(BaseModel):
    """Output des Classifier-Agenten."""

    business_model_type: BusinessModelType = Field(
        description="Archetyp des Geschäftsmodells"
    )
    classification_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Sicherheit der Klassifikation (0.0–1.0)"
    )
    rationale: str = Field(
        description="Kurzbegründung (max. 3 Sätze) mit konkreten Kennzahlen"
    )

    # Welche Bewertungsmethoden sind sinnvoll?
    valuation_methods_recommended: list[str] = Field(
        description=(
            "Liste der primären Bewertungsmethoden, z.B. "
            "['DCF', 'EV/EBITDA', 'Peer Multiples'] oder "
            "['Real Options', 'TAM x Adoption', 'Sum-of-Parts']"
        )
    )
    dcf_applicable: bool = Field(
        description="Ob ein DCF überhaupt aussagekräftige Resultate liefert"
    )

    # Empfohlene Supervisor-Gewichtung (wird im Supervisor weiterverarbeitet)
    suggested_weights: SuggestedWeights = Field(
        description=(
            "Empfohlene Gewichte für die Junior-Agenten, "
            "Summe muss 1.0 ergeben."
        )
    )

    # Phase 2: Echte Vergleichsunternehmen (Geschäftsmodell-Peers)
    suggested_peers: list[str] = Field(
        default_factory=list,
        description=(
            "3-6 Ticker-Symbole ECHTER Geschäftsmodell-Peers (gleiches "
            "Geschäftsmodell/Endmarkt, NICHT nur gleicher GICS-Sektor). "
            "Beispiel Rigetti: ['IONQ', 'QBTS', 'QUBT'] statt Seagate/WDC. "
            "Beispiel Holcim: ['HEI.DE', 'CRH', 'SIKA.SW']. "
            "US-Ticker ohne Suffix, europäische mit Exchange-Suffix "
            "(.SW, .DE, .PA etc.). Nur liquide, börsennotierte Unternehmen."
        )
    )

    # Sekundäre Signale für spätere Phasen
    requires_optionality_analysis: bool = Field(
        default=False,
        description="Triggert in Phase 4 den Optionality-Sub-Agenten"
    )
    cycle_position: Literal["early", "mid", "late", "trough", "unknown"] = Field(
        default="unknown",
        description="Position im Konjunkturzyklus (nur relevant bei cyclical)"
    )


# ── Prompt ───────────────────────────────────────────────────────────────────

CLASSIFIER_PROMPT = """Du bist ein erfahrener Buy-Side-Analyst, der Unternehmen
vor jeder Bewertung erst KLASSIFIZIERT — denn die Bewertungsmethode muss zum
Geschäftsmodell passen, sonst produziert sie Garbage-In-Garbage-Out.

UNTERNEHMEN: {company_name} ({ticker})
SEKTOR: {sector}
INDUSTRIE: {industry}

KERNDATEN (gemischt aus Finnhub + yfinance):
{financial_snapshot}

UNTERNEHMENSBESCHREIBUNG:
{description}

────────────────────────────────────────────────────────────────────────────
DEINE AUFGABE: Ordne das Unternehmen GENAU EINEM der 5 Archetypen zu.
────────────────────────────────────────────────────────────────────────────

1) **mature_cashflow** — Stabile, etablierte Cashflow-Maschine
   Indikatoren:
   - Positive, vorhersehbare FCF seit mindestens 3 Jahren
   - Umsatz > 1 Mrd. USD/CHF/EUR
   - ROIC > 8%, FCF-Margin > 5%
   - Niedrige bis moderate Umsatzwachstumsraten (0–10% p.a.)
   - Etablierte Marktposition, oft Dividendenzahler
   → DCF dominant. Fundamental-Gewicht 0.70–0.80.
   Beispiele: Holcim, Nestlé, Roche, Unilever, J&J

2) **growth_with_revenue** — Wachstumsunternehmen mit echtem Umsatz
   Indikatoren:
   - Umsatzwachstum > 15% p.a.
   - Realer Umsatz > 100 Mio. USD
   - Möglicherweise noch negativ in GAAP-Earnings, aber FCF improving
   - Hohe Bruttomargen (>50% bei SaaS, >25% bei Hardware)
   → Hybrid: DCF mit hohem Terminal Value + EV/Sales-Multiple. News + Thematic wichtig.
   Fundamental-Gewicht 0.55–0.65.
   Beispiele: Snowflake, Palantir, Tesla, Datadog

3) **optionality_play** — Pre-Revenue / Deep-Tech / Tech-Adoption-Wette
   Indikatoren:
   - Umsatz < 100 Mio. USD oder negativ wachsend
   - Negative FCF, oft negatives EBITDA
   - Hohes R&D als % vom Umsatz (>30%)
   - Bewertung primär getrieben von Zukunftsoptionen, nicht Cashflows
   → DCF NICHT anwendbar. Real Options + TAM × Adoption Probability + Cash-Runway.
   Fundamental-Gewicht 0.30–0.45. Thematic/News stark.
   Beispiele: Rigetti, IonQ, Joby Aviation, Archer, viele Biotechs ohne FDA-Approval

4) **cyclical** — Stark vom Konjunkturzyklus abhängig
   Indikatoren:
   - Sektor: Baumaterial, Stahl, Chemie, Halbleiter (Equipment), Auto, Schifffahrt, Banken (z.T.)
   - Hohe Margen-Volatilität (Standardabweichung Operating Margin > 5pp)
   - Umsatz stark korrelliert mit BIP oder Industrie-PMI
   → Mid-Cycle EPS × Normalisiertes Multiple. Macro-Sensitivität ENTSCHEIDEND.
   Fundamental-Gewicht 0.55–0.65, News 0.20–0.30 (Makro!).
   Beispiele: Holcim (Cycle-Komponente), ArcelorMittal, Caterpillar, ASML, Sika
   HINWEIS: Holcim ist Grenzfall — kann mature_cashflow ODER cyclical sein.
   Wähle cyclical wenn Makro-Sensitivität in der aktuellen Phase dominiert.

5) **financial_institution** — Banken, Versicherungen, Asset Manager
   Indikatoren:
   - Sektor explizit: "Financial Services" mit Banken-/Versicherungs-Geschäft
   - Bilanzsumme >> Marktkapitalisierung
   - DCF nicht direkt anwendbar
   → Dividend Discount Model + P/B + ROE. Regulierungs-Sensitivität hoch.
   Beispiele: UBS, JPMorgan, Allianz, Swiss Re

────────────────────────────────────────────────────────────────────────────
PEER-AUSWAHL (suggested_peers):
Nenne 3-6 ECHTE Geschäftsmodell-Peers — Unternehmen mit gleichem Endmarkt
und Geschäftsmodell, nicht nur gleichem GICS-Sektor. Ein Quantum-Hardware-
Startup vergleicht man mit anderen Quantum-Pure-Plays (IONQ, QBTS), NICHT
mit Festplattenherstellern. Ein Schweizer Zementhersteller mit anderen
Baustoffkonzernen (CRH, HEI.DE), nicht mit beliebigen Industrials.
Nur liquide, börsennotierte Ticker. Im Zweifel weniger, aber korrekte Peers.

WICHTIG:
- Wähle die Klasse, die das aktuelle Profil AM BESTEN beschreibt — nicht das,
  was das Unternehmen mal werden möchte.
- Wenn ein Unternehmen zwischen zwei Klassen sitzt: wähle die, deren
  Bewertungsmethode aktuell die belastbarere Aussage liefert.
- Confidence-Score muss ehrlich sein: Grenzfälle bekommen 0.55–0.70,
  klare Fälle 0.85+.

GEWICHTUNGSRICHTLINIEN (Summe = 1.0):
- mature_cashflow:       fundamental 0.75, news 0.10, risk 0.15, thematic 0.00
- growth_with_revenue:   fundamental 0.55, news 0.20, risk 0.15, thematic 0.10
- optionality_play:      fundamental 0.35, news 0.20, risk 0.25, thematic 0.20
- cyclical:              fundamental 0.55, news 0.25, risk 0.15, thematic 0.05
- financial_institution: fundamental 0.65, news 0.15, risk 0.20, thematic 0.00

(thematic-Slot existiert für Phase 3. In Phase 1/2 setzt der Supervisor das
thematic-Gewicht automatisch auf 0 zurück und re-normalisiert.)

Antworte STRIKT als JSON nach dem BusinessModelClassification-Schema.
Kein Text vorher oder nachher.
"""


# ── Runner ───────────────────────────────────────────────────────────────────

def _build_financial_snapshot(stock_info: dict, financials: dict) -> str:
    """Kompakte Daten-Zusammenfassung für den Classifier-Prompt."""
    def _fmt(val, suffix=""):
        if val in (None, "N/A", "-", ""):
            return "n/a"
        if isinstance(val, (int, float)):
            if abs(val) >= 1e9:
                return f"{val/1e9:.2f} Mrd{suffix}"
            if abs(val) >= 1e6:
                return f"{val/1e6:.1f} Mio{suffix}"
            return f"{val:.2f}{suffix}"
        return str(val)

    lines = [
        f"- Marktkapitalisierung: {_fmt(stock_info.get('market_cap'))}",
        f"- Aktueller Kurs: {_fmt(stock_info.get('current_price'))} {stock_info.get('currency', '')}",
        f"- Umsatz TTM: {_fmt(financials.get('revenue_ttm'))}",
        f"- EBITDA TTM: {_fmt(financials.get('ebitda_ttm'))}",
        f"- Net Income TTM: {_fmt(financials.get('net_income_ttm'))}",
        f"- Free Cashflow TTM: {_fmt(financials.get('free_cashflow_ttm'))}",
        f"- Gross Margin: {_fmt(financials.get('gross_margin'))}",
        f"- Operating Margin: {_fmt(financials.get('operating_margin'))}",
        f"- ROE: {_fmt(financials.get('roe'))}",
        f"- Revenue Growth (YoY): {_fmt(financials.get('revenue_growth'))}",
        f"- Earnings Growth (YoY): {_fmt(financials.get('earnings_growth'))}",
        f"- Debt/Equity: {_fmt(financials.get('debt_to_equity'))}",
        f"- Beta: {_fmt(stock_info.get('beta'))}",
        f"- Dividend Yield: {_fmt(stock_info.get('dividend_yield'))}",
        f"- EV/EBITDA: {_fmt(stock_info.get('ev_to_ebitda'))}",
        f"- Forward P/E: {_fmt(stock_info.get('forward_pe'))}",
    ]
    return "\n".join(lines)


def run_classifier_agent(ticker: str) -> dict:
    """
    Führt die Geschäftsmodell-Klassifikation durch.

    Returns:
        dict im BusinessModelClassification-Schema.
    """
    print(f"[classifier] Klassifiziere {ticker}...")

    # 1) Daten holen (deterministisch)
    try:
        stock_info = get_stock_info.invoke({"ticker": ticker}) \
            if hasattr(get_stock_info, "invoke") else get_stock_info(ticker)
    except Exception:
        stock_info = get_stock_info(ticker) if callable(get_stock_info) else {}

    try:
        financials = get_financial_statements.invoke({"ticker": ticker}) \
            if hasattr(get_financial_statements, "invoke") else {}
    except Exception:
        financials = {}

    if not isinstance(stock_info, dict):
        stock_info = {}
    if not isinstance(financials, dict):
        financials = {}

    snapshot = _build_financial_snapshot(stock_info, financials)

    prompt = CLASSIFIER_PROMPT.format(
        company_name=stock_info.get("name", ticker),
        ticker=ticker,
        sector=stock_info.get("sector", "N/A"),
        industry=stock_info.get("industry", "N/A"),
        financial_snapshot=snapshot,
        description=(stock_info.get("description") or "")[:1500],
    )

    # 2) LLM-Call mit Structured Output
    # method="function_calling": toleranter als der strikte JSON-Schema-Modus
    # (der verlangt additionalProperties=false und alle Felder required)
    structured_llm = llm.with_structured_output(
        BusinessModelClassification, method="function_calling"
    )

    try:
        result: BusinessModelClassification = structured_llm.invoke(prompt)
        output = result.model_dump()
    except Exception as e:
        # Defensive Fallback: behandle als growth_with_revenue mit niedriger Confidence
        print(f"[classifier] ⚠ Fallback wegen Fehler: {e}")
        output = {
            "business_model_type": "growth_with_revenue",
            "classification_confidence": 0.30,
            "rationale": f"Klassifikator-Fallback ausgelöst: {e}",
            "valuation_methods_recommended": ["DCF", "EV/EBITDA", "Peer Multiples"],
            "dcf_applicable": True,
            "suggested_weights": {
                "fundamental": 0.65,
                "news": 0.15,
                "risk": 0.15,
                "thematic": 0.05,
            },
            "suggested_peers": [],
            "requires_optionality_analysis": False,
            "cycle_position": "unknown",
        }

    # 3) Re-Normalisierung der Gewichte
    #    Phase 3: thematic-Gewicht bleibt erhalten (Thematic-Agent ist fester
    #    Bestandteil der Pipeline). Nur auf Summe 1.0 normalisieren.
    weights = output.get("suggested_weights", {})
    if isinstance(weights, dict):
        s = sum(weights.values())
        if s > 0:
            weights = {k: round(v / s, 3) for k, v in weights.items()}
        output["suggested_weights"] = weights

    # 4) Peer-Liste defensiv säubern (Tickerformat, Eigenausschluss, Dedupe)
    peers = output.get("suggested_peers") or []
    if isinstance(peers, list):
        clean = []
        for p in peers:
            if not isinstance(p, str):
                continue
            p = p.strip().upper()
            if not p or p == ticker.upper().strip():
                continue
            if len(p) > 12 or " " in p:
                continue
            if p not in clean:
                clean.append(p)
        output["suggested_peers"] = clean[:6]
    else:
        output["suggested_peers"] = []

    print(
        f"[classifier] → {output['business_model_type']} "
        f"(Confidence: {output['classification_confidence']:.2f}, "
        f"DCF anwendbar: {output['dcf_applicable']}, "
        f"Peers: {', '.join(output['suggested_peers']) or '-'})"
    )
    return output
