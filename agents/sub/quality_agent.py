"""
Quality Sub-Agent — ROIC, FCF-Conversion, Bilanzqualität

Erhält vorgeladene Daten vom Fundamental-Orchestrator.
Gibt strukturiertes Dict zurück (kein Pydantic — internes Format).
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

_llm = ChatOpenAI(model="gpt-5.4-mini")

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Du bist ein spezialisierter Quality-Analyst.
Fokus: ROIC, FCF-Conversion, Bilanzstärke, Accruals.
Antworte AUSSCHLIESSLICH mit validem JSON — kein erklärender Text."""),
    ("human", """Ticker: {ticker} | Sektor: {sector}

CASHFLOW-DATEN:
{cashflow_data}

FINANZKENNZAHLEN:
{financials}

HISTORISCHE DATEN (5J):
{hist_data}

DETERMINISTISCH BERECHNETE MULTIPLES:
{multiples_summary}

IR-DATEN:
{ir_summary}

SENIOR-FEEDBACK (falls vorhanden — gezielt adressieren, falls es deinen Bereich betrifft):
{supervisor_critique}

Erstelle folgendes JSON:
{{
  "roic_pct": <float oder null>,
  "fcf_conversion_pct": <float oder null>,
  "balance_sheet_score": "<stark|solide|schwach>",
  "quality_score": <int 0-100>,
  "quality_assessment": "<2-3 Sätze: Kernaussage zur Ergebnisqualität>",
  "quality_flags": ["<Flag1>", "..."],
  "accruals_warning": "<string oder null>",
  "key_quality_metrics": {{
    "ND/EBITDA": "<Wert>",
    "Current Ratio": "<Wert>",
    "Gross Margin": "<Wert>",
    "ROIC": "<Wert>"
  }}
}}

Regeln:
- FCF Conversion < 70%: quality_flag "⚠ Niedrige FCF-Conversion — potenzielle Ergebnisqualitäts-Warnung"
- FCF Conversion > 130%: quality_flag "⚠ Hohe FCF-Conversion — Working-Capital-Anomalie prüfen"
- ROIC > WACC (ca. 8%): quality_score Bonus +10
- Nettoverschuldung > 3x EBITDA: quality_flag "⚠ Erhöhte Verschuldung"
"""),
])


def run_quality_agent(
    ticker: str,
    sector: str,
    cashflow_data: dict,
    financials: dict,
    hist_data: dict,
    all_multiples: dict,
    ir_analysis: dict,
    supervisor_critique: str | None = None,
) -> dict:
    print(f"      [Quality] Analysiere ROIC / FCF / Bilanz...")

    multiples_summary = {
        k: all_multiples[k]
        for k in ("roic", "roe", "fcf_conversion", "nd_ebitda", "fcf_yield", "p_fcf")
        if k in all_multiples
    }

    ir_summary = {
        k: ir_analysis.get(k)
        for k in ("net_debt_bn", "free_cashflow_bn", "ebitda_margin_pct",
                  "revenue_bn", "adjusted_eps", "data_quality")
        if ir_analysis.get(k)
    }

    chain = _prompt_chain()
    raw = chain.invoke({
        "ticker":           ticker,
        "sector":           sector,
        "cashflow_data":    json.dumps(cashflow_data,     ensure_ascii=False)[:3000],
        "financials":       json.dumps(financials,        ensure_ascii=False)[:2000],
        "hist_data":        json.dumps(hist_data,         ensure_ascii=False)[:2000],
        "multiples_summary": json.dumps(multiples_summary, ensure_ascii=False),
        "ir_summary":       json.dumps(ir_summary,        ensure_ascii=False),
        "supervisor_critique": supervisor_critique or "keines",
    })

    return _parse(raw, ticker, "quality")


def _prompt_chain():
    return _PROMPT | _llm | StrOutputParser()


def _parse(raw: str, ticker: str, agent: str) -> dict:
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"      [{agent}] Parse-Fehler: {e}")
    return {"ticker": ticker, "error": f"{agent}_parse_failed", "raw": raw[:500]}
