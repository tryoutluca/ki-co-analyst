from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import (
    get_recent_news, get_stock_info,
    get_macro_indicators, get_industry_indicators,
    get_strategic_milestones,
)
from tools.schemas import NewsAgentOutput

load_dotenv()

llm = ChatOpenAI(model="gpt-5.4")
parser = JsonOutputParser(pydantic_object=NewsAgentOutput)

NEWS_PROMPT = """Du bist ein Senior Buy-Side Analyst. Trenne Signal von Rauschen — strukturelle \
Meilensteine zählen mehr als tagesaktuelle Headlines.

DATENPRIORITÄT (höchste zuerst):
1. Strategische Meilensteine (letzte 12 Monate): CEO/CFO-Wechsel, M&A, Spin-offs, \
   regulatorische Entscheide, strategische Pivots — dauerhafter Einfluss auf den Investment Case
2. Industrie-Dynamiken: sektorale Trends und Wettbewerbsveränderungen
3. Makro-Indikatoren: zyklische Rücken-/Gegenwinde
4. Tagesaktuelle News: nur relevant bei unmittelbarer, materialspezifischer Kursauswirkung

ANALYSE-FRAMEWORK (Gewichtung des Gesamt-Sentiments):
  • Strategische Meilensteine:     30%
  • Industriespezifische Faktoren: 30%
  • Makroökonomische Indikatoren:  25%
  • Tagesaktuelle News:            15%

WICHTIGE GRUNDSÄTZE:
1. Gib für JEDE News die EXAKTE URL und EXAKTE Headline an — fehlt die URL: "nicht verfügbar"
2. Tagge bei jeder News den betroffenen Revenue-Bereich in eckigen Klammern
3. Quell-Bewertung: Bloomberg/Reuters/FT/WSJ = sehr hoch; cash.ch/Handelsblatt = hoch; \
   Yahoo Finance = mittel; Social Media = niedrig
4. Tägliches Rauschen EXPLIZIT von strukturellen Veränderungen trennen
5. Ein strukturell negativer Meilenstein (z.B. CEO-Vakuum, Kartellverfahren) kann gute \
   Fundamentaldaten überstimmen

MAKRO-ANALYSE (macro_indicators):
- Erkläre IMMER den Transmissionsmechanismus: WARUM und über welchen Kanal
- Beispiel: "Steigende SNB-Zinsen → höhere Hypothekenkosten → gedämpfte Bauaktivität \
  → niedrigere Zementnachfrage → Gegenwind für Holcim"

INDUSTRIE-ANALYSE (industry_factors):
- Belege jedes Thema mit der relevantesten Headline aus den Daten
- Bewerte ob sektorale Dynamiken das spezifische Geschäftsmodell stärken oder schwächen

SENTIMENT-BERECHNUNG:
- overall_sentiment_score (1-10) gemäss obiger 4-Ebenen-Gewichtung
- overall_macro_direction: aggregiertes Urteil über alle Makro-Indikatoren
- overall_industry_direction: aggregiertes Urteil über alle Industrie-Faktoren

sentiment_vs_fundamentals_reasoning MUSS Fundamentaldaten aktiv mit News-Signalen kontrastieren:
"Fundamental: [konkrete Kennzahl + Wert aus dem Kontext, z.B. EV/EBITDA 8x vs Peer 10x] | \
Strategisch: [wichtigster Meilenstein der letzten 12 Monate] | \
Makro: [tailwind/neutral/headwind] | Industrie: [tailwind/neutral/headwind] | \
Fazit: [z.B. Solide Zahlen, aber CEO-Vakuum erhöht Ausführungsrisiko]"

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON. Kein erklärender Text.

{format_instructions}"""


def _format_macro_text(macro_data: dict) -> str:
    lines = ["=== MAKROÖKONOMISCHE DATEN ==="]

    fx = macro_data.get("fx_rates", {})
    if fx:
        lines.append("\n[FX-Kurse (yfinance)]")
        for pair, d in fx.items():
            lines.append(f"  {pair}: {d.get('value')} (5d-Veränderung: {d.get('change_5d_pct')}%, Trend: {d.get('trend')})")

    rates = macro_data.get("rate_proxies", {})
    if rates:
        lines.append("\n[Zins-Proxies (yfinance)]")
        for name, d in rates.items():
            lines.append(f"  {name}: {d.get('value_pct')}% (10d-Änderung: {d.get('change_10d_bp')}bp, Trend: {d.get('trend')})")

    cal = macro_data.get("economic_calendar", [])
    if cal:
        lines.append("\n[Wirtschaftskalender]")
        for e in cal:
            lines.append(f"  {e.get('date')} | {e.get('event')}: Aktuell={e.get('actual')} Schätzung={e.get('estimate')} Vorherig={e.get('previous')}")

    news = macro_data.get("macro_news", [])
    if news:
        lines.append("\n[Makro-News]")
        for i, item in enumerate(news, 1):
            lines.append(f"  {i}. [{item.get('published')}] {item.get('headline')} (Quelle: {item.get('source')})")
            if item.get("summary"):
                lines.append(f"     {item.get('summary')[:150]}")

    return "\n".join(lines)


def _format_industry_text(industry_data: dict) -> str:
    lines = ["=== INDUSTRIESPEZIFISCHE INDIKATOREN ==="]
    lines.append(f"Sektor: {industry_data.get('sector')} | Industrie: {industry_data.get('industry')}")
    lines.append(f"Relevante Themen: {', '.join(industry_data.get('topics', []))}")

    news_per_topic = industry_data.get("news_per_topic", {})
    for topic, articles in news_per_topic.items():
        lines.append(f"\n[{topic}]")
        if articles:
            for a in articles:
                lines.append(f"  • [{a.get('published')}] {a.get('headline')} (Quelle: {a.get('source')})")
        else:
            lines.append("  Keine aktuellen News gefunden.")

    return "\n".join(lines)


def _format_milestones_text(milestones: list) -> str:
    lines = ["=== STRATEGISCHE MEILENSTEINE (Letzte 12 Monate) ==="]
    if not milestones or ("info" in milestones[0] or "error" in milestones[0]):
        lines.append(milestones[0].get("info") or milestones[0].get("error", "Keine Daten verfügbar."))
        return "\n".join(lines)
    for i, item in enumerate(milestones, 1):
        title   = item.get("title", "N/A")
        url     = item.get("url", "nicht verfügbar")
        content = item.get("content", "")
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {url}")
        if content:
            lines.append(f"   {content[:300]}")
    return "\n".join(lines)


def run_news_agent(ticker: str, fundamental_summary: str = "") -> NewsAgentOutput:
    """Analysiert News, Makro und Industrie-Faktoren — gibt strukturiertes JSON zurück."""

    # Batch 1: News + Stock-Info parallel (Stock-Info zuerst nötig für Swiss-Check)
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_news = ex.submit(get_recent_news.invoke, ticker)
        fut_info = ex.submit(get_stock_info.invoke, ticker)

    news_yfinance = fut_news.result()
    stock_info    = fut_info.result()

    currency     = stock_info.get("currency", "USD")
    sector       = stock_info.get("sector", "N/A")
    industry     = stock_info.get("industry", "N/A")
    company_name = stock_info.get("name", ticker)

    # Batch 2: Makro + Industrie + Meilensteine parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_macro      = ex.submit(get_macro_indicators.invoke, currency)
        fut_industry   = ex.submit(get_industry_indicators.invoke, {"sector": sector, "industry": industry})
        fut_milestones = ex.submit(get_strategic_milestones.invoke, {"ticker": ticker, "company_name": company_name})

    macro_data    = fut_macro.result()
    industry_data = fut_industry.result()
    milestones    = fut_milestones.result()

    # Unternehmensnews als Text aufbereiten
    news_text = "=== YAHOO FINANCE / FINNHUB NEWS ===\n"
    for i, item in enumerate(news_yfinance, 1):
        news_text += f"{i}. Headline: {item.get('headline') or item.get('title', 'N/A')}\n"
        news_text += f"   Summary: {item.get('summary', 'N/A')}\n"
        news_text += f"   Published: {item.get('published', 'N/A')}\n"
        news_text += f"   URL: {item.get('url', 'nicht verfügbar')}\n\n"

    milestones_text = _format_milestones_text(milestones)
    macro_text      = _format_macro_text(macro_data)
    industry_text   = _format_industry_text(industry_data)

    fundamental_context = ""
    if fundamental_summary:
        fundamental_context = f"\n=== KONTEXT FUNDAMENTALANALYSE ===\n{fundamental_summary}\n"

    prompt = ChatPromptTemplate.from_messages([
        ("system", NEWS_PROMPT),
        ("human", """Analysiere {ticker} ({company}, Sektor: {sector}, Industrie: {industry}, Währung: {currency}).

{milestones_text}

{news_text}

{macro_text}

{industry_text}
{fundamental_context}

Erstelle die vollständige Analyse als JSON.
- Gewichte strategische Meilensteine am stärksten (30%)
- macro_indicators: mindestens 3 Einträge basierend auf den Makrodaten
- industry_factors: mindestens 3 Einträge basierend auf den Industrie-News
- Bei fehlenden URLs: schreibe "nicht verfügbar"
- sentiment_vs_fundamentals_reasoning: kontrastiere aktiv Fundamentaldaten mit News-Signalen"""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker":            ticker,
        "company":           company_name,
        "sector":            sector,
        "industry":          industry,
        "currency":          currency,
        "milestones_text":   milestones_text,
        "news_text":         news_text,
        "macro_text":        macro_text,
        "industry_text":     industry_text,
        "fundamental_context": fundamental_context,
        "format_instructions": parser.get_format_instructions(),
    })

    return result


if __name__ == "__main__":
    result = run_news_agent("HOLN.SW")
    print(json.dumps(result, indent=2, ensure_ascii=False))
