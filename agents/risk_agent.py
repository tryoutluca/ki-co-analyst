from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import get_stock_info, get_price_history
from tools.schemas import RiskAgentOutput, FundamentalAgentOutput, NewsAgentOutput

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini")
parser = JsonOutputParser(pydantic_object=RiskAgentOutput)

RISK_PROMPT = """Du bist der Advocatus Diaboli eines professionellen Buy-Side Teams.
Deine einzige Aufgabe: die bestehende Investmentempfehlung mit professioneller Skepsis hinterfragen und widerlegen.

KERN-GRUNDSÄTZE:
1. Keine generischen Risiken — jeder Punkt muss spezifisch für dieses Unternehmen sein
2. Quantifiziere jeden Risikopunkt mit einem Transmissionsmechanismus:
   Nicht "Zinsrisiko", sondern "SNB +100bps → Hypothekenkosten +15% → Baubewilligungen CH -8% → Holcim CH Revenue -4% → EPS -0.20 CHF"
3. Identifiziere Confirmation Bias: Hat der Analyst selektiv Forward P/E statt Trailing P/E verwendet weil es günstiger aussieht? Hat er den Vergleichszeitraum cherry-gepickt?
4. Verweise direkt auf konkrete Punkte aus der Fundamental- und News-Analyse
5. Stelle Fragen die ein Portfoliomanager vor Entscheid stellen würde

KATEGORIEN (genau eine Argument pro Kategorie, total 5):
- Bewertungsrisiko: Multiples-Vergleich, DCF-Annahmen, Peer-Bewertung
- Makro/Zinsrisiko: Zinsen, FX, Konjunktur — mit konkretem Transmissionsmechanismus
- Operatives Risiko: Margen, Wachstum, Execution
- Regulierungsrisiko: Regulierung, Steuern, Geopolitik
- Sentiment-Risiko: Positionierung, Momentum, technische Faktoren

MAKRO/INDUSTRIE-INTEGRATION:
- Die News-Analyse hat spezifische Makro-Indikatoren und Industrie-Faktoren identifiziert
- Prüfe explizit: Hat die Fundamentalanalyse diese in DCF-Discount-Rate / Wachstumsannahmen / Margenprojektionen eingepreist?
- Wenn nein: trage es in macro_risks_ignored ein

EMPFEHLUNGS-SKALA (5-stufig — verwende für original_recommendation):
  KAUFEN | ÜBERGEWICHTEN | HALTEN | UNTERGEWICHTEN | VERKAUFEN

CONVICTION KILLERS → automatisch 2 Stufen schlechter:
  Original KAUFEN + 2 Conviction Killers → HALTEN
  Original ÜBERGEWICHTEN + 2 Conviction Killers → UNTERGEWICHTEN

SZENARIEN (genau 3, Wahrscheinlichkeiten müssen 100 ergeben):
- Bear Case: Was wenn die 2-3 wichtigsten Annahmen der Bullanalyse falsch sind?
- Base Case: Konsenserwartung, mittleres Szenario
- Bull Case: Was müsste eintreten damit die ursprüngliche Empfehlung klar gerechtfertigt ist?

CONVICTION KILLERS (max 2):
- Was ist der EINE Datenpunkt / das EINE Ereignis das die gesamte Investment-These sofort invalidiert?
- Konkret monitorbar: welche Kennzahl, welches Event, welcher Schwellenwert?

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON. Kein erklärender Text.

{format_instructions}"""


def run_risk_agent(
    ticker: str,
    fundamental_output: FundamentalAgentOutput,
    news_output: NewsAgentOutput,
) -> RiskAgentOutput:
    """Führt Advocatus-Diaboli-Analyse durch — gibt strukturiertes JSON zurück."""

    stock_info = get_stock_info.invoke(ticker)
    price_history = get_price_history.invoke(ticker)

    macro_indicators = news_output.get("macro_indicators", []) if isinstance(news_output, dict) else getattr(news_output, "macro_indicators", [])
    industry_factors = news_output.get("industry_factors", []) if isinstance(news_output, dict) else getattr(news_output, "industry_factors", [])

    macro_text = ""
    if macro_indicators:
        macro_text = "\n=== MAKRO-INDIKATOREN (aus News-Agent) ===\n"
        for m in macro_indicators:
            if isinstance(m, dict):
                macro_text += f"  • {m.get('indicator', '')}: {m.get('value', '')} → {m.get('impact_on_company', '')} | {m.get('mechanism', '')}\n"
            else:
                macro_text += f"  • {m.indicator}: {m.value} → {m.impact_on_company} | {m.mechanism}\n"

    industry_text = ""
    if industry_factors:
        industry_text = "\n=== INDUSTRIE-FAKTOREN (aus News-Agent) ===\n"
        for f in industry_factors:
            if isinstance(f, dict):
                industry_text += f"  • [{f.get('direction', '')}] {f.get('topic', '')}: {f.get('mechanism', '')}\n"
            else:
                industry_text += f"  • [{f.direction}] {f.topic}: {f.mechanism}\n"

    recommendation = (
        fundamental_output.get("recommendation", "HALTEN")
        if isinstance(fundamental_output, dict)
        else getattr(fundamental_output, "recommendation", "HALTEN")
    )
    company = stock_info.get("name", ticker)

    prompt = ChatPromptTemplate.from_messages([
        ("system", RISK_PROMPT),
        ("human", """Hinterfrage kritisch diese Analyse für {ticker} ({company}):

FUNDAMENTALANALYSE (JSON):
{fundamental_json}

NEWS-ANALYSE (JSON):
{news_json}

{macro_text}
{industry_text}

AKTUELLE MARKTDATEN (yfinance):
{stock_info}

KURSENTWICKLUNG (yfinance):
{price_history}

Die folgenden Makro- und Industrie-Risiken wurden vom News-Agent identifiziert — prüfe ob die \
Fundamentalanalyse diese in ihrer Analyse (DCF-Rate, Wachstumsannahmen, Margenprognosen) \
adäquat berücksichtigt hat. Wo nicht, trage es in macro_risks_ignored ein.

Nimm die Gegenposition zur Empfehlung "{recommendation}" ein.
Sei konkret, zahlenbasiert und verweise direkt auf Punkte aus der obigen Analyse.
Erstelle EXAKT 3 Szenarien (Bear/Base/Bull) deren Wahrscheinlichkeiten sich auf 100 summieren."""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker": ticker,
        "company": company,
        "fundamental_json": json.dumps(fundamental_output, indent=2, ensure_ascii=False),
        "news_json": json.dumps(news_output, indent=2, ensure_ascii=False),
        "macro_text": macro_text,
        "industry_text": industry_text,
        "recommendation": recommendation,
        "stock_info": stock_info,
        "price_history": price_history,
        "format_instructions": parser.get_format_instructions(),
    })

    return result


if __name__ == "__main__":
    from agents.fundamental_agent import run_fundamental_agent
    from agents.news_agent import run_news_agent

    print("Starte Fundamental-Agent...")
    fundamental = run_fundamental_agent("HOLN.SW")

    print("Starte News-Agent...")
    news = run_news_agent("HOLN.SW")

    print("Starte Risk-Agent...")
    result = run_risk_agent("HOLN.SW", fundamental, news)
    print(json.dumps(result, indent=2, ensure_ascii=False))
