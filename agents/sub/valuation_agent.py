"""
Valuation Sub-Agent — Multiples + DCF + Sum-of-Parts

Erhält vorgeladene Daten vom Fundamental-Orchestrator.
Ist bewusst DCF-agnostisch — übernimmt business_model_context vom Classifier.
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Hinweis: gpt-5-Modelle (ausser gpt-5-chat) erzwingen temperature=1 —
# langchain-openai verwirft temperature=0 hier still, keine echte
# Determinismus-Garantie (siehe fundamental_agent.py für Details).
_llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Du bist ein spezialisierter Valuation-Analyst.
Fokus: Fair Value ableiten via Multiples, DCF, Sum-of-Parts.
Antworte AUSSCHLIESSLICH mit validem JSON — kein erklärender Text."""),
    ("human", """Ticker: {ticker} | Sektor: {sector} | Kurs: {current_price}

GESCHÄFTSMODELL-KONTEXT (vom Classifier):
{bm_context}

DETERMINISTISCH BERECHNETE MULTIPLES:
{all_multiples}

DCF-ERGEBNIS (Valuation Engine):
{dcf_result}

FORWARD-SCHÄTZUNGEN:
{forward_estimates}

IR-FAIR-VALUE-HINWEISE:
{ir_valuation}

SENIOR-FEEDBACK (falls vorhanden — gezielt adressieren, falls es deinen Bereich betrifft):
{supervisor_critique}

Erstelle folgendes JSON:
{{
  "fair_value_estimate": <float — primärer Fair-Value-Anker>,
  "fair_value_range_low": <float>,
  "fair_value_range_high": <float>,
  "upside_downside_pct": <float — (fair_value - current_price) / current_price * 100>,
  "valuation_assessment": "<unterbewertet|fair bewertet|überbewertet>",
  "primary_method": "<DCF|EV/EBITDA|P/E|EV/Sales|P/B|Sum-of-Parts>",
  "valuation_confidence": <float 0.0-1.0>,
  "valuation_narrative": "<2-3 Sätze: Herleitung Fair Value>",
  "valuation_table": [
    {{
      "metric": "<Name>",
      "current_value": "<Wert>",
      "peer_average": "<Wert oder ->",
      "historical_average": "<Wert oder ->",
      "assessment": "<DISCOUNT|FAIR|ELEVATED>",
      "calculation": "<Formel>",
      "source": "<Quelle>"
    }}
  ]
}}

REGELN:
- DCF nicht anwendbar bei optionality_play oder financial_institution → primary_method = EV/Sales oder P/B
- fair_value_estimate muss numerisch und plausibel sein (nicht 0 oder null)
- Upside > +10%: valuation_assessment = "unterbewertet"
- Upside < -10%: valuation_assessment = "überbewertet"
- Sonst: "fair bewertet"
- valuation_table: mind. 3, max. 6 Einträge
"""),
])


def run_valuation_agent(
    ticker: str,
    sector: str,
    stock_info: dict,
    all_multiples: dict,
    forward_estimates: dict,
    cashflow_data: dict,
    financials: dict,
    ir_analysis: dict,
    business_model_context: dict | None,
    dcf_result: dict | None,
    supervisor_critique: str | None = None,
) -> dict:
    print(f"      [Valuation] Berechne Fair Value / Multiples-Assessment...")

    current_price = (
        all_multiples.get("_price_data", {}).get("current_price")
        or stock_info.get("currentPrice")
        or stock_info.get("regularMarketPrice")
        or 0
    )

    bm_context = {}
    if business_model_context:
        bm_context = {
            "type":    business_model_context.get("business_model_type", "unknown"),
            "dcf_ok":  business_model_context.get("dcf_applicable", True),
            "methods": business_model_context.get("valuation_methods_recommended", []),
        }

    ir_valuation = {
        k: ir_analysis.get(k)
        for k in ("revenue_bn", "ebitda_margin_pct", "net_debt_bn",
                  "consensus_eps_2026", "consensus_eps_2027", "pe_distortion_explanation")
        if ir_analysis.get(k)
    }

    multiples_slim = {
        k: v for k, v in all_multiples.items()
        if not k.startswith("_") or k in ("_price_data", "_enterprise_value")
    }

    chain = _PROMPT | _llm | StrOutputParser()
    raw = chain.invoke({
        "ticker":           ticker,
        "sector":           sector,
        "current_price":    current_price,
        "bm_context":       json.dumps(bm_context,         ensure_ascii=False),
        "all_multiples":    json.dumps(multiples_slim,     ensure_ascii=False)[:3000],
        "dcf_result":       json.dumps(dcf_result or {},   ensure_ascii=False)[:2000],
        "forward_estimates": json.dumps(forward_estimates, ensure_ascii=False)[:2000],
        "ir_valuation":     json.dumps(ir_valuation,       ensure_ascii=False),
        "supervisor_critique": supervisor_critique or "keines",
    })

    return _parse(raw, ticker, "valuation")


def _parse(raw: str, ticker: str, agent: str) -> dict:
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"      [{agent}] Parse-Fehler: {e}")
    return {"ticker": ticker, "error": f"{agent}_parse_failed", "raw": raw[:500]}
