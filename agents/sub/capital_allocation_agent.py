"""
Capital Allocation Sub-Agent — Buybacks, M&A, Dividenden, Capex-Disziplin

Erhält vorgeladene Daten vom Fundamental-Orchestrator.
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

_llm = ChatOpenAI(model="gpt-5.4-mini")

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Du bist ein spezialisierter Capital-Allocation-Analyst.
Fokus: Kapitalrückführung an Aktionäre, M&A-Track-Record, Capex-Effizienz, ROIC vs. WACC.
Antworte AUSSCHLIESSLICH mit validem JSON — kein erklärender Text."""),
    ("human", """Ticker: {ticker} | Sektor: {sector}

CASHFLOW-DATEN:
{cashflow_data}

FINANZKENNZAHLEN:
{financials}

HISTORISCHE DATEN (5J):
{hist_data}

IR-DATEN (Dividenden, Buybacks, M&A-Hinweise):
{ir_capital}

STOCK-INFO (Shares, Dividende):
{stock_summary}

SENIOR-FEEDBACK (falls vorhanden — gezielt adressieren, falls es deinen Bereich betrifft):
{supervisor_critique}

Erstelle folgendes JSON:
{{
  "buyback_yield_pct": <float oder null>,
  "dividend_yield_pct": <float oder null>,
  "total_shareholder_yield_pct": <float oder null>,
  "capex_as_pct_revenue": <float oder null>,
  "capex_intensity": "<niedrig|mittel|hoch>",
  "ma_track_record": "<accretive|mixed|destructive|keine M&A>",
  "roic_vs_wacc": "<ROIC > WACC|ROIC ≈ WACC|ROIC < WACC|unklar>",
  "allocation_score": <int 0-100>,
  "allocation_assessment": "<2-3 Sätze: Kernaussage zur Kapitalallokation>",
  "shareholder_return_flags": ["<Flag1>", "..."],
  "key_allocation_metrics": {{
    "Buyback Yield": "<Wert>%",
    "Dividend Yield": "<Wert>%",
    "Payout Ratio": "<Wert>%",
    "Capex/Revenue": "<Wert>%",
    "FCF nach Capex": "<Wert> Mrd."
  }}
}}

REGELN:
- Total Shareholder Yield = Buyback Yield + Dividend Yield
- ROIC > 12%: allocation_score Bonus +10 (schafft Wert über WACC)
- Hohe M&A-Aktivität ohne klaren Track-Record: ma_track_record = "mixed", −10 Score
- Payout Ratio > 100%: shareholder_return_flag "⚠ Dividende durch Schulden finanziert"
- Capex/Revenue > 15%: capex_intensity = "hoch"
- Wenn keine Dividende und keine Buybacks: total_shareholder_yield_pct = 0
"""),
])


def run_capital_allocation_agent(
    ticker: str,
    sector: str,
    cashflow_data: dict,
    financials: dict,
    hist_data: dict,
    stock_info: dict,
    ir_analysis: dict,
    supervisor_critique: str | None = None,
) -> dict:
    print(f"      [CapAlloc] Analysiere Buybacks / Dividenden / M&A / Capex...")

    stock_summary = {
        k: stock_info.get(k)
        for k in ("dividendYield", "dividendRate", "sharesOutstanding",
                  "floatShares", "buybackYield", "payoutRatio", "trailingAnnualDividendYield")
        if stock_info.get(k) is not None
    }

    ir_capital = {
        k: ir_analysis.get(k)
        for k in ("dps", "dividend_per_share", "buyback_program",
                  "net_debt_bn", "free_cashflow_bn", "key_statements", "management_tone")
        if ir_analysis.get(k)
    }

    chain = _PROMPT | _llm | StrOutputParser()
    raw = chain.invoke({
        "ticker":        ticker,
        "sector":        sector,
        "cashflow_data": json.dumps(cashflow_data,  ensure_ascii=False)[:2500],
        "financials":    json.dumps(financials,     ensure_ascii=False)[:1500],
        "hist_data":     json.dumps(hist_data,      ensure_ascii=False)[:2000],
        "ir_capital":    json.dumps(ir_capital,     ensure_ascii=False),
        "stock_summary": json.dumps(stock_summary,  ensure_ascii=False),
        "supervisor_critique": supervisor_critique or "keines",
    })

    return _parse(raw, ticker, "capital_allocation")


def _parse(raw: str, ticker: str, agent: str) -> dict:
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"      [{agent}] Parse-Fehler: {e}")
    return {"ticker": ticker, "error": f"{agent}_parse_failed", "raw": raw[:500]}
