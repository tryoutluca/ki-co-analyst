"""
Fundamental Agent — Orchestrator + Lead-Synthese

Architektur:
  1. Daten einmalig laden (Finanz-Tools, IR-RAG, MultiplesEngine)
  2. 4 Sub-Agents parallel via ThreadPoolExecutor:
       Quality · Growth · Valuation · Capital Allocation
  3. Lead-LLM synthetisiert Sub-Agent-Outputs → FundamentalAgentOutput

Öffentliche Schnittstelle run_fundamental_agent() unverändert.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.finance_tools import (
    build_estimate_anchors,
    get_cashflow_data,
    get_financial_statements,
    get_historical_financials,
    get_historical_multiples,
    get_peer_financials,
    get_price_history,
    get_stock_info,
)
from tools.ir_rag_tool import consensus_estimates_from_ir, get_ir_analysis
from tools.multiples_engine import MultiplesEngine
from tools.schemas import FundamentalAgentOutput
from tools.valuation_engine import build_valuation_table, run_dcf

from agents.sub.capital_allocation_agent import run_capital_allocation_agent
from agents.sub.growth_agent import run_growth_agent
from agents.sub.quality_agent import run_quality_agent
from agents.sub.valuation_agent import run_valuation_agent

load_dotenv()

_llm    = ChatOpenAI(model="gpt-5.4-mini")
_parser = JsonOutputParser(pydantic_object=FundamentalAgentOutput)

# ── Lead-Syntheseprompt ───────────────────────────────────────────────────────

_LEAD_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Du bist der Fundamental-Lead eines Buy-Side-Research-Teams.
Vier spezialisierte Sub-Agenten haben ihre Analyse abgeliefert.
Deine Aufgabe: synthetisiere deren Ergebnisse zu einem kohärenten Investment-Urteil.

DATENPRIORITÄT:
1. IR-Dokumente (geprüfte Zahlen)
2. Sub-Agent-Outputs (spezialisierte Analyse)
3. yfinance (Ergänzung)

EMPFEHLUNGS-LOGIK (basierend auf Valuation Sub-Agent):
  upside > +10% → KAUFEN
  +5% bis +10%  → ÜBERGEWICHTEN
  -5% bis +5%   → HALTEN
  -10% bis -5%  → UNTERGEWICHTEN
  < -10%        → VERKAUFEN

Adjustiere ±1 Stufe wenn:
- Quality Score < 50 → eine Stufe schlechter
- FCF Conversion < 70% oder > 130% → eine Stufe schlechter
- Capital Allocation Score > 80 → eine Stufe besser

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON.
{format_instructions}"""),

    ("human", """Ticker: {ticker} | Sektor: {sector} | Kurs: {current_price}

══════════════════════════════════════════
QUALITY SUB-AGENT:
{quality_output}

══════════════════════════════════════════
GROWTH SUB-AGENT:
{growth_output}

══════════════════════════════════════════
VALUATION SUB-AGENT:
{valuation_output}

══════════════════════════════════════════
CAPITAL ALLOCATION SUB-AGENT:
{capital_output}

══════════════════════════════════════════
KERNDATEN FÜR SYNTHESE:
{core_data}

══════════════════════════════════════════
SENIOR-FEEDBACK (falls vorhanden):
{senior_feedback}

AUFGABEN:
1. Leite fair_value_estimate aus Valuation Sub-Agent ab.
2. Setze recommendation nach Empfehlungs-Logik (oben).
3. investment_case: 3-5 Punkte aus Quality + Growth + CapAlloc, mit Zahlen.
4. risks: 2-3 Punkte aus allen Sub-Agents.
5. key_metrics: kombiniere key_quality_metrics + key_growth_metrics + key_allocation_metrics.
6. cashflow_metrics: aus Quality Sub-Agent.
7. self_confidence: Durchschnitt der Sub-Agent-Scores / 100, adjustiert für Datenlücken.
8. company_description: max. 3 Sätze aus core_data.
"""),
])


# ── Öffentliche Schnittstelle (unverändert) ───────────────────────────────────

def run_fundamental_agent(
    ticker: str,
    supervisor_critique: str | None = None,
    structural_context: str | None  = None,
    business_model_context: dict | None = None,
) -> FundamentalAgentOutput:
    """
    Orchestriert 4 parallele Sub-Agents und synthetisiert deren Outputs.
    Signatur identisch zur Vorgänger-Version.
    """

    # ── 1. Daten einmalig laden ───────────────────────────────────────────────
    print(f"      Hole Unternehmensdaten...")
    stock_info    = get_stock_info.invoke(ticker)
    financials    = get_financial_statements.invoke(ticker)
    price_history = get_price_history.invoke(ticker)

    print(f"      Hole Cashflow-Daten...")
    cashflow_data = get_cashflow_data.invoke(ticker)

    print(f"      Hole historische Multiples...")
    historical_multiples = get_historical_multiples.invoke(ticker)

    print(f"      Analysiere IR-Dokumente (RAG)...")
    ir_analysis = get_ir_analysis.invoke(ticker)

    print(f"      Hole historische Finanzdaten...")
    hist_data = get_historical_financials.invoke(ticker)

    sector = stock_info.get("sector", "N/A")

    print(f"      Berechne Multiples via MultiplesEngine...")
    try:
        engine = MultiplesEngine.from_ticker(
            ticker           = ticker,
            ir_analysis      = ir_analysis or {},
            financial_source = (
                f"IR-Dokument {ir_analysis.get('document_date', '')}"
                if ir_analysis else "yfinance"
            ),
            hist_data        = hist_data,
        )
        all_multiples = engine.compute_all()
        _sum  = all_multiples.get("_summary", {})
        _pm   = all_multiples.get("_price_data", {})
        print(
            f"      ✅ MultiplesEngine: "
            f"{_sum.get('valid',0)}/{_sum.get('total_calculated',0)} Kennzahlen | "
            f"Kurs: {_pm.get('current_price')} {_pm.get('currency')}"
        )
    except Exception as e:
        print(f"      ⚠ MultiplesEngine Fehler: {e}")
        all_multiples = {}

    print(f"      Berechne Konsensschätzungen...")
    forward_estimates = consensus_estimates_from_ir(
        ticker, ir_analysis, historical_multiples, sector,
    )

    _fwd_price = all_multiples.get("_price_data", {}).get("current_price") if all_multiples else None
    if _fwd_price and forward_estimates.get("estimates"):
        for _yr in forward_estimates["estimates"].values():
            try:
                _eps = float(_yr.get("eps") or 0)
                if _eps > 0:
                    _yr["forward_pe"] = round(_fwd_price / _eps, 1)
            except (TypeError, ValueError):
                pass

    print(f"      Erstelle Peer-Vergleich...")
    _suggested_peers = None
    if business_model_context and isinstance(business_model_context, dict):
        _sp = business_model_context.get("suggested_peers")
        if isinstance(_sp, list) and _sp:
            _suggested_peers = _sp
    peer_comparison = get_peer_financials(ticker, peers_override=_suggested_peers)

    print(f"      Berechne Estimate-Anker...")
    estimate_anchors = build_estimate_anchors(
        ticker          = ticker,
        hist_data       = hist_data,
        ir_analysis     = ir_analysis or {},
        peer_comparison = peer_comparison,
    )

    dcf_result = run_dcf(ir_analysis, financials, cashflow_data, stock_info)

    # ── 2. Sub-Agents parallel ────────────────────────────────────────────────
    print(f"      🚀 Starte 4 Sub-Agents parallel...")

    sub_results: dict[str, dict] = {}

    tasks = {
        "quality": lambda: run_quality_agent(
            ticker, sector, cashflow_data, financials,
            hist_data, all_multiples, ir_analysis or {},
        ),
        "growth": lambda: run_growth_agent(
            ticker, sector, hist_data, forward_estimates,
            estimate_anchors, peer_comparison, ir_analysis or {},
        ),
        "valuation": lambda: run_valuation_agent(
            ticker, sector, stock_info, all_multiples,
            forward_estimates, cashflow_data, financials,
            ir_analysis or {}, business_model_context, dcf_result,
        ),
        "capital_allocation": lambda: run_capital_allocation_agent(
            ticker, sector, cashflow_data, financials,
            hist_data, stock_info, ir_analysis or {},
        ),
    }

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                sub_results[name] = future.result()
                print(f"      ✅ {name.upper()} Sub-Agent abgeschlossen")
            except Exception as exc:
                print(f"      ❌ {name.upper()} Sub-Agent Fehler: {exc}")
                sub_results[name] = {"error": str(exc)}

    # ── 3. Lead-Synthese ──────────────────────────────────────────────────────
    print(f"      Lead synthetisiert Sub-Agent-Outputs...")

    current_price = (
        all_multiples.get("_price_data", {}).get("current_price")
        or stock_info.get("currentPrice")
        or 0
    )

    senior_feedback = ""
    if supervisor_critique:
        senior_feedback = f"⚠️ SENIOR-ANALYST FEEDBACK:\n{supervisor_critique}"
    if structural_context:
        senior_feedback += f"\n\nCORPORATE ACTIONS:\n{structural_context}"

    core_data = {
        "company":       stock_info.get("name", ticker),
        "description":   stock_info.get("longBusinessSummary", "")[:400],
        "current_price": current_price,
        "currency":      stock_info.get("currency", ""),
        "market_cap":    stock_info.get("marketCap"),
        "sector":        sector,
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "price_3m":      price_history,
        "ir_quality":    (ir_analysis or {}).get("data_quality"),
    }

    lead_chain = _LEAD_PROMPT | _llm | _parser
    result = lead_chain.invoke({
        "ticker":           ticker,
        "sector":           sector,
        "current_price":    current_price,
        "quality_output":   json.dumps(sub_results.get("quality",{}),           ensure_ascii=False),
        "growth_output":    json.dumps(sub_results.get("growth",{}),            ensure_ascii=False),
        "valuation_output": json.dumps(sub_results.get("valuation",{}),         ensure_ascii=False),
        "capital_output":   json.dumps(sub_results.get("capital_allocation",{}), ensure_ascii=False),
        "core_data":        json.dumps(core_data,                               ensure_ascii=False),
        "senior_feedback":  senior_feedback,
        "format_instructions": _parser.get_format_instructions(),
    })

    # ── 4. Post-Processing (deterministisch, wie bisher) ─────────────────────
    if isinstance(result, dict):
        # Valuation-Engine-Werte überschreiben LLM-Output
        if all_multiples:
            result["valuation_table"] = _build_valuation_table(all_multiples, sector)
            result["all_multiples"]   = all_multiples
        p = all_multiples.get("_price_data", {}) if all_multiples else {}
        if p.get("current_price"):
            result["current_price"] = p["current_price"]
        if p.get("market_cap_bn"):
            result["market_cap_bn"] = p["market_cap_bn"]

        # Sub-Agent-Outputs für Supervisor anhängen
        result["_sub_agents"] = sub_results

        # Vollständige Finanzübersicht
        print(f"      Erstelle vollständige Finanzübersicht...")
        forward_list = _build_forward_list(forward_estimates, all_multiples, ir_analysis, stock_info)
        result["_full_financials"] = build_full_financials(
            hist_data         = hist_data,
            ir_analysis       = ir_analysis or {},
            forward_estimates = forward_list,
            n_years           = 5,
        )
        result["_peer_comparison"]  = peer_comparison
        result["_valuation_engine"] = {
            "dcf_inputs":      dcf_result,
            "valuation_table": build_valuation_table(dcf_result),
        }

    return result


# ── Hilfsfunktionen (unverändert) ────────────────────────────────────────────

def _build_forward_list(
    forward_estimates: dict,
    all_multiples: dict,
    ir_analysis: dict | None,
    stock_info: dict,
) -> list:
    def _sf(v):
        try:
            return float(v) if v not in (None, "-", "n/v", "not found", "") else None
        except (TypeError, ValueError):
            return None

    _net_debt_bn = _sf((ir_analysis or {}).get("net_debt_bn"))
    if _net_debt_bn is None:
        _d = _sf(stock_info.get("totalDebt"))
        _c = _sf(stock_info.get("totalCash"))
        if _d is not None:
            _net_debt_bn = round((_d or 0) / 1e9 - (_c or 0) / 1e9, 2)

    _mc_bn = (all_multiples or {}).get("_price_data", {}).get("market_cap_bn")
    _ev_bn = round(_mc_bn + _net_debt_bn, 2) if (_mc_bn and _net_debt_bn is not None) else None

    _last_dps = _sf((ir_analysis or {}).get("dividend_per_share"))

    rows = []
    for yr, est in (forward_estimates.get("estimates") or {}).items():
        rev      = _sf(est.get("revenue_bn"))
        ebitda_m = _sf(est.get("ebitda_margin_pct"))
        ebit_m   = _sf(est.get("ebit_margin_pct"))
        fcf_fwd  = _sf(est.get("fcf_bn"))

        ebitda_bn     = round(rev * ebitda_m / 100, 2) if (rev and ebitda_m) else None
        ev_ebitda_fwd = round(_ev_bn / ebitda_bn, 1) if (_ev_bn and ebitda_bn and ebitda_bn > 0) else None
        nd_ebitda_fwd = round(_net_debt_bn / ebitda_bn, 2) if (_net_debt_bn is not None and ebitda_bn and ebitda_bn > 0) else None

        rows.append({
            "year":              yr,
            "type":              "E",
            "revenue_bn":        rev,
            "ebitda_bn":         ebitda_bn,
            "ebitda_margin_pct": ebitda_m,
            "ebit_margin_pct":   ebit_m,
            "eps_adj":           est.get("eps"),
            "dps":               _last_dps,
            "fcf_bn":            fcf_fwd,
            "net_debt_bn":       _net_debt_bn,
            "nd_ebitda":         nd_ebitda_fwd,
            "ev_ebitda_fwd":     ev_ebitda_fwd,
            "forward_pe":        est.get("forward_pe"),
            "source":            est.get("source", forward_estimates.get("source", "-")),
        })
    return rows


def build_full_financials(
    hist_data: dict,
    ir_analysis: dict,
    forward_estimates: list,
    n_years: int = 5,
) -> list:
    if not hist_data:
        return forward_estimates or []

    last_year = max(hist_data.keys())

    def safe_ir(key):
        val = ir_analysis.get(key)
        if val and str(val) not in ("n/v", "not found", "", "-", "N/A"):
            try:
                return float(val)
            except Exception:
                return None
        return None

    overrides = {
        "revenue_bn":        safe_ir("revenue_bn"),
        "ebitda_margin_pct": safe_ir("ebitda_margin_pct"),
        "net_debt_bn":       safe_ir("net_debt_bn"),
        "fcf_bn":            safe_ir("free_cashflow_bn"),
        "eps":               safe_ir("adjusted_eps"),
        "dps":               safe_ir("dps"),
    }

    applied = [k for k, v in overrides.items() if v is not None]
    for key in applied:
        hist_data[last_year][key] = overrides[key]

    if "ebitda_margin_pct" in applied or "revenue_bn" in applied:
        rev = hist_data[last_year].get("revenue_bn")
        m   = hist_data[last_year].get("ebitda_margin_pct")
        if rev and m:
            hist_data[last_year]["ebitda_bn"] = round(rev * m / 100, 4)

    if applied:
        hist_data[last_year]["source"] = "IR-Dokument (bereinigt)"
        print(f"      IR-Override {last_year}: {applied}")

    years = sorted(hist_data.keys(), reverse=True)[:n_years]
    result = []
    for yr in sorted(years):
        d = hist_data[yr]
        result.append({
            "year":              f"{yr}A",
            "type":              "A",
            "revenue_bn":        d.get("revenue_bn"),
            "ebitda_bn":         d.get("ebitda_bn"),
            "ebitda_margin_pct": d.get("ebitda_margin_pct"),
            "ebit_bn":           d.get("ebit_bn"),
            "ebit_margin_pct":   d.get("ebit_margin_pct"),
            "net_income_bn":     d.get("net_income_bn"),
            "eps_adj":           d.get("eps"),
            "dps":               d.get("dps"),
            "fcf_bn":            d.get("fcf_bn"),
            "net_debt_bn":       d.get("net_debt_bn"),
            "nd_ebitda":         d.get("nd_ebitda"),
            "roe_pct":           d.get("roe_pct"),
            "roic_pct":          d.get("roic_pct"),
            "capex_bn":          d.get("capex_bn"),
            "gross_margin_pct":  d.get("gross_margin_pct"),
            "source":            d.get("source", "yfinance"),
        })
    result.extend(forward_estimates or [])
    return result


def _build_valuation_table(all_multiples: dict, sector: str) -> list:
    sector_lower = sector.lower()

    if any(w in sector_lower for w in ["bank", "versicher", "financ"]):
        primary = [("P/B", "pb_ratio"), ("ROE", "roe"), ("P/E", "pe_ratio")]
    elif any(w in sector_lower for w in ["immobil", "reit", "real estate"]):
        primary = [("EV/EBITDA", "ev_ebitda"), ("Div-Yield", "dividend_yield"), ("P/B", "pb_ratio")]
    elif any(w in sector_lower for w in ["tech", "software", "saas"]):
        primary = [("EV/Sales", "ev_sales"), ("EV/EBITDA", "ev_ebitda"), ("P/FCF", "p_fcf")]
    else:
        primary = [
            ("EV/EBITDA", "ev_ebitda"), ("P/E", "pe_ratio"),
            ("EV/Sales",  "ev_sales"),  ("P/FCF", "p_fcf"),
            ("Div-Yield", "dividend_yield"),
        ]

    table = []
    for label, key in primary:
        m = all_multiples.get(key, {})
        if m.get("valid"):
            table.append({
                "metric":             label,
                "current_value":      str(m["value"]),
                "peer_average":       "-",
                "historical_average": "-",
                "assessment":         "FAIR",
                "calculation":        m["formula"],
                "source":             m["source"],
            })
    return table


if __name__ == "__main__":
    result = run_fundamental_agent("HOLN.SW")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
