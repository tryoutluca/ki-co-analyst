"""
tools/valuation_engine.py

Forward-Estimate Engine: synthetisiert 2026E/2027E/2028E Schätzungen aus
IR-Daten, Makro/News-Signalen und Risk-Agent-Szenarien.

Hauptfunktionen:
  derive_forward_estimates()   — 3-Jahres-Schätzung (Kern-Logik)
  build_peer_forward_table()   — Peer-Vergleichstabelle via yfinance
"""

from __future__ import annotations

import re
import yfinance as yf


# ── Helpers ───────────────────────────────────────────────────────────────────

_NOT_FOUND = {"not found", "n/v", "N/A", "nicht verfügbar", "", None}


def _safe_float(value) -> float | None:
    """Converts any value to float; returns None for missing/invalid data."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() in _NOT_FOUND:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_valid(value) -> bool:
    return _safe_float(value) is not None


def _get(obj, key: str, default=None):
    """Attribute or dict access with fallback."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _pct(value: float | None) -> str:
    """Format float as rounded percentage string or 'n/v'."""
    return f"{round(value * 100, 2)}" if value is not None else "n/v"


def _round2(value: float | None) -> float | str:
    return round(value, 2) if value is not None else "n/v"


def _round1(value: float | None) -> float | str:
    return round(value, 1) if value is not None else "n/v"


# ── Year extraction ───────────────────────────────────────────────────────────

def _extract_two_years(
    historical_financials: dict,
    ir_data: dict,
) -> tuple[dict, dict]:
    """
    Returns (year1_data, year2_data) dicts with keys:
      revenue_bn, ebitda_margin_pct, eps, fcf_bn

    Supports three input formats for historical_financials:
      1. Year-keyed: {"2023A": {...}, "2024A": {...}}
      2. Finnhub time-series (get_historical_multiples output):
         {"revenue_growth": [{"period": "2024-12-31", "v": 0.06}, ...], ...}
      3. Fallback: derive year1 from ir_data + revenue_growth series
    """
    # Format 1: Year-keyed dict
    year_keys = sorted(
        k for k in historical_financials
        if re.match(r"20[12]\d[AE]?$", k)
    )
    if len(year_keys) >= 2:
        y1 = historical_financials[year_keys[-2]]
        y2 = historical_financials[year_keys[-1]]
        return dict(y1), dict(y2)

    # Build year2 from ir_data (most recent actual)
    y2 = {
        "revenue_bn":        _safe_float(ir_data.get("revenue_bn")),
        "ebitda_margin_pct": _safe_float(ir_data.get("ebitda_margin_pct")),
        "eps":               _safe_float(ir_data.get("adjusted_eps")),
        "fcf_bn":            _safe_float(ir_data.get("free_cashflow_bn")),
    }

    # Format 2: Finnhub time-series — back-calculate year1 revenue
    rev_growth_series = historical_financials.get("revenue_growth", [])
    y1: dict = {}
    if rev_growth_series and isinstance(rev_growth_series, list):
        latest_growth_entry = rev_growth_series[0] if rev_growth_series else {}
        g = _safe_float(latest_growth_entry.get("v") or latest_growth_entry.get("value"))
        if g is not None and y2["revenue_bn"] is not None and (1 + g) != 0:
            y1["revenue_bn"] = y2["revenue_bn"] / (1 + g)

    # Try net_margin to derive year1 EBITDA margin (rough proxy)
    net_margin_series = historical_financials.get("net_margin", [])
    if len(net_margin_series) >= 2 and isinstance(net_margin_series[0], dict):
        m_cur  = _safe_float(net_margin_series[0].get("v") or net_margin_series[0].get("value"))
        m_prev = _safe_float(net_margin_series[1].get("v") or net_margin_series[1].get("value"))
        if m_cur is not None and m_prev is not None and y2["ebitda_margin_pct"] is not None:
            delta_net = m_cur - m_prev
            y1["ebitda_margin_pct"] = y2["ebitda_margin_pct"] - delta_net * 100

    return y1, y2


# ── Core function ─────────────────────────────────────────────────────────────

def derive_forward_estimates(
    ir_data: dict,
    news_data: dict,
    risk_data: dict,
    historical_financials: dict,
    sector: str,
) -> dict:
    """
    Synthetisiert 3-Jahres Forward-Schätzungen (2026E/2027E/2028E) aus drei Quellen:
      1. IR-Daten (Basis-Wachstum + Guidance Override)
      2. Makro/News-Signale (Adjustment)
      3. Risk-Agent-Szenarien (Probability-Weighted Growth)

    Args:
        ir_data:               Output von get_ir_analysis()
        news_data:             Output von run_news_agent() — NewsAgentOutput
        risk_data:             Output von run_risk_agent() — RiskAgentOutput
        historical_financials: 2-Jahres-Dict oder get_historical_multiples() Output
        sector:                Sektor-String z.B. "Basic Materials"

    Returns:
        Strukturiertes dict mit method, assumptions, estimates (3 Jahre),
        peer_comparison, market_vs_system_note, disclaimer.
    """

    # ── Schritt 1: Basis-Wachstum aus IR-Daten (2 Jahre) ─────────────────────

    y1, y2 = _extract_two_years(historical_financials, ir_data)

    rev_y1 = _safe_float(y1.get("revenue_bn"))
    rev_y2 = _safe_float(y2.get("revenue_bn")) or _safe_float(ir_data.get("revenue_bn"))
    margin_y1 = _safe_float(y1.get("ebitda_margin_pct"))
    margin_y2 = (
        _safe_float(y2.get("ebitda_margin_pct"))
        or _safe_float(ir_data.get("ebitda_margin_pct"))
    )
    eps_y1 = _safe_float(y1.get("eps"))
    eps_y2 = _safe_float(y2.get("eps")) or _safe_float(ir_data.get("adjusted_eps"))

    revenue_cagr: float | None = None
    if rev_y1 and rev_y2 and rev_y1 != 0:
        revenue_cagr = rev_y2 / rev_y1 - 1

    ebitda_margin_trend: float = 0.0
    if margin_y1 is not None and margin_y2 is not None:
        ebitda_margin_trend = margin_y2 - margin_y1

    eps_cagr: float | None = None
    if eps_y1 and eps_y2 and eps_y1 != 0:
        eps_cagr = eps_y2 / eps_y1 - 1

    # IR-Guidance Override: consensus revenue 2026 from IR takes precedence
    ir_guidance_used = False
    consensus_rev_2026 = _safe_float(ir_data.get("consensus_revenue_2026_bn"))
    if consensus_rev_2026 and rev_y2 and rev_y2 != 0:
        revenue_cagr = consensus_rev_2026 / rev_y2 - 1
        ir_guidance_used = True
    elif ir_data.get("guidance_2026") not in _NOT_FOUND:
        # Guidance string present — mark as used even if we can't parse a number from it
        ir_guidance_used = True

    base_growth = revenue_cagr if revenue_cagr is not None else 0.05

    # ── Schritt 2: Makro/Sentiment Adjustment ────────────────────────────────

    macro_direction  = _get(news_data, "overall_macro_direction",  "neutral")
    industry_direction = _get(news_data, "overall_industry_direction", "neutral")

    _macro_map    = {"tailwind": 0.01,  "neutral": 0.0, "headwind": -0.01}
    _industry_map = {"tailwind": 0.005, "neutral": 0.0, "headwind": -0.005}

    macro_adj    = _macro_map.get(str(macro_direction),    0.0)
    industry_adj = _industry_map.get(str(industry_direction), 0.0)

    adjusted_growth = base_growth + macro_adj + industry_adj

    # ── Schritt 3: Szenario-Gewichtung aus Risk-Agent ────────────────────────

    scenarios_raw = _get(risk_data, "scenarios", [])
    if not isinstance(scenarios_raw, list):
        scenarios_raw = []

    bear_prob = base_prob = bull_prob = None
    bear_target = base_target = bull_target = None

    for s in scenarios_raw:
        name   = str(_get(s, "name", ""))
        prob   = _safe_float(_get(s, "probability_pct", None))
        target = _safe_float(_get(s, "price_target",    None))
        if "Bear" in name:
            bear_prob, bear_target = prob, target
        elif "Base" in name:
            base_prob, base_target = prob, target
        elif "Bull" in name:
            bull_prob, bull_target = prob, target

    final_growth = adjusted_growth  # default if scenario data missing

    if all(
        x is not None
        for x in [bear_target, base_target, bull_target, bear_prob, base_prob, bull_prob]
    ) and base_target and base_target != 0:
        growth_premium = (bull_target - bear_target) / base_target

        # Implied growth per scenario: scale adjusted_growth by target ratio vs base
        bear_growth = adjusted_growth * (bear_target / base_target)
        bull_growth = adjusted_growth * (bull_target / base_target)

        # Probability-weighted
        final_growth = (
            bear_prob * bear_growth
            + base_prob * adjusted_growth
            + bull_prob * bull_growth
        ) / 100

    # ── 3-Jahres Projektion ───────────────────────────────────────────────────

    # Marginal deceleration over the 3-year horizon (standard equity research)
    _growth_decay = [1.0, 0.92, 0.85]

    ebit_margin_base = (
        _safe_float(ir_data.get("recurring_ebit_margin_pct"))
        or (margin_y2 * 0.80 if margin_y2 is not None else None)
    )

    fcf_y2_val = _safe_float(ir_data.get("free_cashflow_bn"))
    fcf_to_revenue = (
        (fcf_y2_val / rev_y2)
        if (fcf_y2_val and rev_y2 and rev_y2 != 0)
        else 0.08
    )

    # Forward margin trend: apply half the historical trend (conservatism)
    fwd_margin_step = ebitda_margin_trend * 0.5

    estimates: dict = {}
    prev_rev = rev_y2
    prev_eps = eps_y2
    eps_growth_base = eps_cagr if eps_cagr is not None else final_growth

    for i, year in enumerate(["2026E", "2027E", "2028E"]):
        decay  = _growth_decay[i]
        g_rev  = final_growth    * decay
        g_eps  = eps_growth_base * decay

        rev    = (prev_rev * (1 + g_rev)) if prev_rev is not None else None
        ebitda = (margin_y2 + fwd_margin_step * (i + 1)) if margin_y2 is not None else None
        ebit   = (ebit_margin_base + fwd_margin_step * 0.8 * (i + 1)) if ebit_margin_base is not None else None
        eps    = (prev_eps * (1 + g_eps))  if prev_eps is not None else None
        fcf    = (rev * fcf_to_revenue)    if rev is not None else None

        consensus_note = (
            f"LLM +{round(g_rev * 100, 1)}% — "
            "Kein Bloomberg/FactSet Konsens verfügbar"
        )

        estimates[year] = {
            "revenue_bn":              _round2(rev),
            "ebitda_margin_pct":       _round1(ebitda),
            "ebit_margin_pct":         _round1(ebit),
            "eps":                     _round2(eps),
            "fcf_bn":                  _round2(fcf),
            "growth_vs_consensus_note": consensus_note,
        }
        prev_rev = rev
        prev_eps = eps

    # ── Market-vs-System Note ────────────────────────────────────────────────

    sys_growth_pct = round(final_growth * 100, 1)
    valuation_signal = (
        "=> Aktie erscheint unterbewertet wenn System-Annahme korrekt"
        if sys_growth_pct > 0
        else "=> Aktie erscheint überbewertet wenn System-Annahme korrekt"
    )
    ir_override_note = " | IR-Guidance als Revenue-Override verwendet." if ir_guidance_used else ""
    market_vs_system_note = (
        f"System schätzt +{sys_growth_pct}% Umsatzwachstum "
        f"(IR-Basis{ir_override_note} + Makro {round(macro_adj * 100, 1)}% "
        f"+ Industrie {round(industry_adj * 100, 1)}% + Szenario-Gewichtung) "
        f"vs implizierter Markterwartung: Kein Bloomberg/FactSet Konsens verfügbar. "
        f"{valuation_signal}"
    )

    return {
        "method": "IR-Basis + Makro-Adjustment + Risk-Gewichtung",
        "assumptions": {
            "historical_revenue_cagr_pct": (
                round(revenue_cagr * 100, 2) if revenue_cagr is not None else "n/v"
            ),
            "macro_adjustment_pct":    round(macro_adj    * 100, 2),
            "industry_adjustment_pct": round(industry_adj * 100, 2),
            "scenario_weights": {
                "bear": int(bear_prob) if bear_prob is not None else "n/v",
                "base": int(base_prob) if base_prob is not None else "n/v",
                "bull": int(bull_prob) if bull_prob is not None else "n/v",
            },
            "ir_guidance_used": ir_guidance_used,
        },
        "estimates": estimates,
        "peer_comparison": {},
        "market_vs_system_note": market_vs_system_note,
        "disclaimer": (
            "Keine Bloomberg/FactSet Konsensdaten verfügbar — "
            "LLM-Ableitung aus IR + Makro + Risikoszenarien"
        ),
    }


# ── Peer Forward Table ────────────────────────────────────────────────────────

def build_peer_forward_table(
    ticker: str,
    peers: list[str],
    year: str = "2026E",
) -> list[dict]:
    """
    Baut Peer-Vergleichstabelle mit Forward-Kennzahlen aus yfinance.

    Args:
        ticker: Primäres Ticker-Symbol (erscheint zuerst in der Tabelle)
        peers:  Liste von Peer-Tickers
        year:   Zeithorizont-Label z.B. "2026E" (nur für Darstellung)

    Returns:
        Liste von dicts mit forward_pe und ev_ebitda je Ticker.
        Fehlende Werte werden als "n/v" ausgegeben (kein Halluzinieren).

    Hinweis: yfinance forwardPE ist auf 12 Monate vorausschauend (NTM),
    nicht kalendarisch 2026E. EV/EBITDA ist trailing. Beide gelten als
    Annäherung für den Forward-Vergleich.
    """
    all_tickers = [ticker] + [p for p in peers if p != ticker]
    rows: list[dict] = []

    for t in all_tickers:
        try:
            info = yf.Ticker(t).info
            fwd_pe  = _safe_float(info.get("forwardPE"))
            ev_ebitda = _safe_float(info.get("enterpriseToEbitda"))
            mktcap    = _safe_float(info.get("marketCap"))
            rows.append({
                "ticker":           t,
                "name":             info.get("longName", t),
                "year":             year,
                "forward_pe_2026e": _round1(fwd_pe),
                "ev_ebitda_2026e":  _round1(ev_ebitda),
                "market_cap_bn":    _round1(mktcap / 1e9) if mktcap else "n/v",
                "is_primary":       t == ticker,
            })
        except Exception:
            rows.append({
                "ticker":           t,
                "name":             t,
                "year":             year,
                "forward_pe_2026e": "n/v",
                "ev_ebitda_2026e":  "n/v",
                "market_cap_bn":    "n/v",
                "is_primary":       t == ticker,
            })

    return rows


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    # Minimal mock data for testing without running all agents
    mock_ir = {
        "revenue_bn": 28.4,
        "ebitda_margin_pct": 19.1,
        "adjusted_eps": 3.45,
        "free_cashflow_bn": 3.2,
        "recurring_ebit_margin_pct": 14.5,
        "guidance_2026": "Mid-single-digit organic growth expected",
        "consensus_revenue_2026_bn": "not found",
    }
    mock_historical = {
        "2023A": {"revenue_bn": 26.7, "ebitda_margin_pct": 18.2, "eps": 3.12, "fcf_bn": 2.9},
        "2024A": {"revenue_bn": 28.4, "ebitda_margin_pct": 19.1, "eps": 3.45, "fcf_bn": 3.2},
    }
    mock_news = {
        "overall_macro_direction": "neutral",
        "overall_industry_direction": "tailwind",
    }
    mock_risk = {
        "scenarios": [
            {"name": "Bear Case", "probability_pct": 25, "price_target": 65.0},
            {"name": "Base Case", "probability_pct": 55, "price_target": 82.0},
            {"name": "Bull Case", "probability_pct": 20, "price_target": 100.0},
        ]
    }

    result = derive_forward_estimates(
        ir_data=mock_ir,
        news_data=mock_news,
        risk_data=mock_risk,
        historical_financials=mock_historical,
        sector="Basic Materials",
    )
    peers = build_peer_forward_table("HOLN.SW", ["SIKA.SW", "STO"], year="2026E")
    result["peer_comparison"] = {row["ticker"]: row for row in peers}

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
