"""
Growth Sub-Agent — Revenue-Trajektorie, Margen-Expansion

Erhält vorgeladene Daten vom Fundamental-Orchestrator.
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

_llm = ChatOpenAI(model="gpt-5.4-mini")

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Du bist ein spezialisierter Growth-Analyst.
Fokus: Umsatzwachstum, Margendynamik, organisches vs. akquisitorisches Wachstum.
Antworte AUSSCHLIESSLICH mit validem JSON — kein erklärender Text."""),
    ("human", """Ticker: {ticker} | Sektor: {sector}

HISTORISCHE FINANZDATEN (5J):
{hist_data}

ESTIMATE-ANKER (deterministisch):
{estimate_anchors}

FORWARD-SCHÄTZUNGEN:
{forward_estimates}

PEER-VERGLEICH:
{peer_summary}

IR-DATEN (Guidance & Statements):
{ir_growth}

{ir_annual_block}

Erstelle folgendes JSON:
{{
  "revenue_cagr_3y_pct": <float oder null>,
  "ebitda_margin_trend": "<expanding|stable|contracting>",
  "margin_expansion_pp_pa": <float oder null>,
  "growth_quality": "<organic|mixed|acquisitive>",
  "growth_score": <int 0-100>,
  "growth_assessment": "<2-3 Sätze: Kernaussage zur Wachstumsqualität>",
  "forward_growth_outlook": "<1-2 Sätze Ausblick>",
  "vs_peers": "<outperform|inline|underperform>",
  "key_growth_metrics": {{
    "3Y Revenue CAGR": "<Wert>%",
    "EBITDA Margin aktuell": "<Wert>%",
    "EBITDA Margin 3J-Trend": "<+/- pp p.a.>",
    "Peer Revenue Growth Median": "<Wert>%"
  }}
}}

Regeln:
- CAGR aus hist_data berechnen (letztes verfügbares Jahr vs. 3J zuvor)
- Margendynamik: Trend der letzten 3 Jahre bestimmt ebitda_margin_trend
- Wenn Wachstum signifikant unter Peer-Median: growth_score −15
- Management Guidance priorisieren wenn vorhanden
"""),
])


def run_growth_agent(
    ticker: str,
    sector: str,
    hist_data: dict,
    forward_estimates: dict,
    estimate_anchors: dict,
    peer_comparison: dict | list,
    ir_analysis: dict,
    ir_annual_history: list | None = None,
) -> dict:
    print(f"      [Growth] Analysiere Umsatz / Margen / Trajektorie...")

    peer_summary = _summarize_peers(peer_comparison)

    ir_growth = {
        k: ir_analysis.get(k)
        for k in ("guidance_2026", "guidance_2027", "revenue_bn", "ebitda_margin_pct",
                  "management_tone", "key_statements")
        if ir_analysis.get(k)
    }

    # Build compact IR multi-year block (source: audited annual reports)
    ir_annual_block = ""
    if ir_annual_history:
        lines = ["IR-JAHRESBERICHTE (geprüft, Priorität gegenüber yfinance):"]
        for yr in ir_annual_history:
            fy = yr.get("fiscal_year", "?")
            rev = yr.get("revenue_bn", "n/a")
            ebitda_m = yr.get("ebitda_margin_pct", "n/a")
            eps = yr.get("adjusted_eps", "n/a")
            fcf = yr.get("free_cashflow_bn", "n/a")
            lines.append(
                f"  FY{fy}: Revenue={rev}Bn | EBITDA-Marge={ebitda_m}% | "
                f"Adj.EPS={eps} | FCF={fcf}Bn"
            )
        ir_annual_block = "\n".join(lines)

    chain = _PROMPT | _llm | StrOutputParser()
    raw = chain.invoke({
        "ticker":            ticker,
        "sector":            sector,
        "hist_data":         json.dumps(hist_data,          ensure_ascii=False)[:2500],
        "estimate_anchors":  json.dumps(estimate_anchors,   ensure_ascii=False)[:1500],
        "forward_estimates": json.dumps(forward_estimates,  ensure_ascii=False)[:2000],
        "peer_summary":      json.dumps(peer_summary,       ensure_ascii=False)[:2000],
        "ir_growth":         json.dumps(ir_growth,          ensure_ascii=False),
        "ir_annual_block":   ir_annual_block,
    })

    return _parse(raw, ticker, "growth")


def _summarize_peers(peer_comparison) -> list:
    if isinstance(peer_comparison, list):
        return peer_comparison[:5]
    if isinstance(peer_comparison, dict):
        peers = peer_comparison.get("peers", peer_comparison.get("data", []))
        return peers[:5] if isinstance(peers, list) else []
    return []


def _parse(raw: str, ticker: str, agent: str) -> dict:
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(raw[start:end])
    except Exception as e:
        print(f"      [{agent}] Parse-Fehler: {e}")
    return {"ticker": ticker, "error": f"{agent}_parse_failed", "raw": raw[:500]}
