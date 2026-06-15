"""
Thematic Agent — 4. Junior-Agent (Phase 3).

Mappt strukturelle Megatrends auf das Unternehmen und quantifiziert ihren
Beitrag zu den Forward-Wachstumsraten. Das ist der Agent, der einen
"KI-Rechenzentren-Boom → +60% Umsatz bei NAND-Herstellern" überhaupt erst
sauber herleiten kann — er denkt in Adoptionskurven und TAM-Verschiebungen,
nicht in Quartalszahlen.

Rolle im System:
  - Speist `thematic_context` in den Forward-Estimate-Agenten ein
    (der die Wachstumsraten daraus mitableitet)
  - Aktiviert das im Classifier reservierte `thematic`-Gewicht im Supervisor
  - Nutzt Web-Search für aktuelle Trend-Evidenz (Tavily, wenn verfügbar)
"""

from __future__ import annotations

import os
import sys

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.schemas import ThematicAgentOutput

llm = ChatOpenAI(model="gpt-5.4-mini")


THEMATIC_PROMPT = """Du bist ein Thematic-Analyst, spezialisiert auf
strukturelle Megatrends und ihre Wirkung auf einzelne Unternehmen. Deine
Analyse fliesst DIREKT in die Forward-Wachstumsschätzungen ein — du lieferst
das "Big Picture", das Quartalszahlen nicht zeigen.

DENKWEISE: Du denkst in Adoptionskurven (S-Kurven) und TAM-Verschiebungen.
Ein Trend in der "beschleunigung"-Phase liefert den stärksten
Wachstumsbeitrag. Du fragst: Welche strukturellen Kräfte verändern den
adressierbaren Markt dieses Unternehmens über die nächsten 3-5 Jahre, und
wie gut ist es positioniert, davon zu profitieren?

UNTERNEHMEN: {company} ({ticker})
SEKTOR: {sector} | INDUSTRIE: {industry}
GESCHÄFTSMODELL-TYP: {business_model_type}

UNTERNEHMENSBESCHREIBUNG:
{description}

=== AKTUELLE TREND-RECHERCHE (Web) ===
{research_block}

=== MAKRO-/SEKTOR-SIGNALE (vom News-Agent) ===
{news_block}

────────────────────────────────────────────────────────────────────────────
DEINE AUFGABE: Identifiziere 1-4 strukturelle Megatrends mit Bezug zum
Unternehmen. Für jeden Trend:

1. trend: Name des Megatrends
2. relevance: kern / moderat / peripher (für die These des Unternehmens)
3. time_horizon: kurz-/mittel-/langfristig
4. adoption_stage: früh / beschleunigung / reife / saettigung
   (beschleunigung = steilster Punkt der S-Kurve = max. Wachstumsbeitrag)
5. tam_impact: Wirkung auf den adressierbaren Markt, quantifiziert
6. company_positioning: Wie gut profitiert DIESES Unternehmen konkret?
7. growth_contribution: Beitrag zum Umsatzwachstum für die Forward-Estimates
   — quantifiziert in Prozentpunkten, z.B. "+15-25pp FY26-27"
8. evidence: Quelle/Beleg

Dann die Gesamtsicht:
- net_thematic_assessment: Netto-Rückenwind oder Gegenwind?
- thematic_thesis: die übergreifende thematische These (2-3 Sätze)
- growth_rate_implication: KONKRETE Implikation für Forward-Wachstumsraten,
  die der Forward-Estimate-Agent direkt nutzen kann
- summary: kompakte Zusammenfassung mit den wichtigsten Trends + ihren
  quantifizierten Wachstumsbeiträgen (das ist der Input für den Forward-Agent)

WICHTIG:
- Sei KONKRET und quantifiziert. "KI ist wichtig" ist nutzlos. "KI-Capex der
  Hyperscaler wächst +40% p.a., treibt NAND-Nachfrage, Unternehmen mit 15%
  Marktanteil → +20-30pp Umsatzwachstum" ist brauchbar.
- Unterscheide echte strukturelle Trends von zyklischem Rauschen.
- Eine LEERE oder kurze Trend-Liste ist valide, wenn das Unternehmen nicht
  trend-getrieben ist (z.B. regionaler Versorger, Basiskonsumgüter).
- Berücksichtige auch GEGENWIND-Trends (Disruption, Substitution, Regulierung),
  nicht nur Rückenwind.
- Übertreibe nicht: Trends entfalten sich über Jahre, nicht über Nacht.

{format_instructions}

Antworte ausschliesslich als JSON nach dem Schema."""


def _research_trends(ticker: str, company: str, sector: str, industry: str) -> str:
    """Holt aktuelle Trend-Evidenz via Tavily (wenn verfügbar)."""
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        search = TavilySearchResults(max_results=4)
        query = f"{company} {industry} structural growth trends outlook 2026 2027 market"
        results = search.invoke(query)
        if isinstance(results, list) and results:
            parts = []
            for r in results[:4]:
                if isinstance(r, dict):
                    content = r.get("content", "")[:400]
                    url = r.get("url", "")
                    parts.append(f"  • {content} [{url}]")
            return "\n".join(parts) if parts else "Keine Trend-Recherche verfügbar."
    except Exception as e:
        return f"Trend-Recherche nicht verfügbar ({e})."
    return "Keine Trend-Recherche verfügbar."


def run_thematic_agent(
    ticker: str,
    fundamental_output: dict | None = None,
    news_output: dict | None = None,
    business_model_context: dict | None = None,
    stock_info: dict | None = None,
) -> dict | None:
    """
    Führt die thematische Analyse durch.

    Returns:
        dict im ThematicAgentOutput-Schema (inkl. 'summary' für den
        Forward-Agent), oder None wenn fehlgeschlagen.
    """
    print(f"[thematic] Analysiere Megatrends für {ticker}...")

    # Stammdaten beschaffen
    if not stock_info:
        try:
            from tools.finance_tools import get_stock_info
            stock_info = get_stock_info.invoke({"ticker": ticker}) \
                if hasattr(get_stock_info, "invoke") else get_stock_info(ticker)
        except Exception:
            stock_info = {}
    if not isinstance(stock_info, dict):
        stock_info = {}

    company = stock_info.get("name", ticker)
    sector = stock_info.get("sector", "N/A")
    industry = stock_info.get("industry", "N/A")
    description = (stock_info.get("description") or "")[:1200]

    # Web-Recherche für aktuelle Trends
    research_block = _research_trends(ticker, company, sector, industry)

    # News-Signale als Kontext
    news_block = "Keine News-Signale verfügbar."
    if news_output and isinstance(news_output, dict):
        parts = []
        if news_output.get("macro_summary"):
            parts.append(f"Makro: {news_output['macro_summary']}")
        for f in news_output.get("industry_factors", [])[:4]:
            ff = f if isinstance(f, dict) else {}
            desc = ff.get("factor") or ff.get("description") or str(f)[:120]
            parts.append(f"  • {desc}")
        if parts:
            news_block = "\n".join(parts)

    bmt = "unknown"
    if business_model_context and isinstance(business_model_context, dict):
        bmt = business_model_context.get("business_model_type", "unknown")

    parser = PydanticOutputParser(pydantic_object=ThematicAgentOutput)
    prompt = ChatPromptTemplate.from_messages([("human", THEMATIC_PROMPT)])
    chain = prompt | llm | parser

    try:
        result = chain.invoke({
            "ticker": ticker,
            "company": company,
            "sector": sector,
            "industry": industry,
            "business_model_type": bmt,
            "description": description,
            "research_block": research_block,
            "news_block": news_block,
            "format_instructions": parser.get_format_instructions(),
        })
        output = result.model_dump()
    except Exception as e:
        print(f"[thematic] ⚠ Fehler: {e}")
        return None

    n_trends = len(output.get("trends", []))
    print(
        f"[thematic] → {n_trends} Trends | "
        f"Netto: {output.get('net_thematic_assessment', '?')} | "
        f"Conf: {output.get('self_confidence', 0):.2f}"
    )
    return output
