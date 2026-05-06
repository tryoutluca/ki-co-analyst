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
from datetime import datetime
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


# ── DCF Inputs (IR > yfinance) ────────────────────────────────────────────────

def run_dcf(
    ir_analysis: dict,
    financials: dict,
    cashflow_data: dict,
    stock_info: dict,
) -> dict:
    """
    Berechnet DCF-Eingabewerte mit Priorität IR-Dokument > yfinance.
    Live-Werte (Kurs, MarktKap, Aktien) kommen aus stock_info — dort
    bereits Finnhub-primär nach get_stock_info().

    Returns:
        Dict mit ebitda, fcf, eps, net_debt, book_value_per_share
        plus je ein *_source-Feld zur Nachvollziehbarkeit.
    """
    _NF = {"not found", "n/v", "N/A", "nicht verfügbar", "", None}

    def _ir(key):
        v = ir_analysis.get(key)
        return None if v in _NF else v

    # Live-Werte aus stock_info (Finnhub-primär)
    current_price      = _safe_float(stock_info.get("current_price"))
    market_cap         = _safe_float(stock_info.get("market_cap"))
    shares_outstanding = _safe_float(stock_info.get("shares_outstanding"))
    currency           = stock_info.get("currency", "")

    # ── EBITDA: IR (revenue × margin) → yfinance ─────────────────────────────
    ebitda: float | None = None
    ebitda_source = "n/v"
    ir_margin  = _safe_float(_ir("ebitda_margin_pct"))
    ir_revenue = _safe_float(_ir("revenue_bn"))
    if ir_margin is not None and ir_revenue is not None:
        ebitda = ir_revenue * ir_margin / 100 * 1e9
        ebitda_source = f"IR-Dokument ({ir_revenue:.2f} Mrd. × {ir_margin:.1f}%)"
    if ebitda is None:
        ebitda = _safe_float(financials.get("ebitda_ttm"))
        if ebitda is not None:
            ebitda_source = "yfinance (EBITDA TTM)"

    # ── FCF: IR → yfinance cashflow_data ─────────────────────────────────────
    fcf: float | None = None
    fcf_source = "n/v"
    ir_fcf = _safe_float(_ir("free_cashflow_bn"))
    if ir_fcf is not None:
        fcf = ir_fcf * 1e9
        fcf_source = f"IR-Dokument ({ir_fcf:.2f} Mrd.)"
    if fcf is None:
        fcf = _safe_float(cashflow_data.get("free_cashflow"))
        if fcf is not None:
            fcf_source = "yfinance (FCF)"

    # ── EPS: IR adjusted → yfinance trailing ─────────────────────────────────
    eps: float | None = None
    eps_source = "n/v"
    ir_eps = _safe_float(_ir("adjusted_eps"))
    if ir_eps is not None:
        eps = ir_eps
        eps_source = f"IR-Dokument (adj. EPS {ir_eps:.2f} {currency})"
    if eps is None:
        eps = _safe_float(financials.get("eps_trailing"))
        if eps is not None:
            eps_source = f"yfinance (trailing EPS {eps:.2f} {currency})"

    # ── Net Debt: IR → yfinance (Schulden − Kasse) ───────────────────────────
    net_debt: float | None = None
    net_debt_source = "n/v"
    ir_nd = _safe_float(_ir("net_debt_bn"))
    if ir_nd is not None:
        net_debt = ir_nd * 1e9
        net_debt_source = f"IR-Dokument ({ir_nd:.2f} Mrd.)"
    if net_debt is None:
        total_debt = _safe_float(financials.get("total_debt")) or 0.0
        total_cash = _safe_float(financials.get("total_cash")) or 0.0
        net_debt = total_debt - total_cash
        net_debt_source = "yfinance (Schulden − Kasse)"

    # ── Book Value: yfinance (IR selten verfügbar) ────────────────────────────
    book_value_per_share = _safe_float(financials.get("book_value_per_share"))
    bvps_source = f"yfinance ({book_value_per_share:.2f} {currency})" if book_value_per_share else "n/v"

    return {
        "current_price":        current_price,
        "market_cap":           market_cap,
        "shares_outstanding":   shares_outstanding,
        "currency":             currency,
        "ebitda":               ebitda,
        "ebitda_source":        ebitda_source,
        "fcf":                  fcf,
        "fcf_source":           fcf_source,
        "eps":                  eps,
        "eps_source":           eps_source,
        "net_debt":             net_debt,
        "net_debt_source":      net_debt_source,
        "book_value_per_share": book_value_per_share,
        "bvps_source":          bvps_source,
    }


# ── Valuation Table (Live-Kurs + IR-Zahlen) ───────────────────────────────────

def build_valuation_table(dcf_inputs: dict) -> list[dict]:
    """
    Berechnet Bewertungs-Multiples aus Live-Kurs (Finnhub) + IR-Zahlen.

    Jede Zeile enthält ein 'calculation'-Feld mit transparenter Herleitung,
    z.B. 'P/E = 148.50 CHF / 4.52 CHF (IR adj. EPS) = 32.9x'.
    peer_average / historical_average sind als 'n/v' vorbelegt —
    der LLM ergänzt sie aus historical_multiples / peer-Daten.

    Returns:
        Liste von dicts kompatibel mit ValuationTableRow + zusätzlichem
        'calculation'-Feld.
    """
    price    = _safe_float(dcf_inputs.get("current_price"))
    mktcap   = _safe_float(dcf_inputs.get("market_cap"))
    net_debt = _safe_float(dcf_inputs.get("net_debt"))
    ebitda   = _safe_float(dcf_inputs.get("ebitda"))
    fcf      = _safe_float(dcf_inputs.get("fcf"))
    eps      = _safe_float(dcf_inputs.get("eps"))
    bvps     = _safe_float(dcf_inputs.get("book_value_per_share"))
    ccy      = dcf_inputs.get("currency", "")

    rows: list[dict] = []

    # EV = MarktKap + Nettoverschuldung
    ev: float | None = None
    if mktcap is not None and net_debt is not None:
        ev = mktcap + net_debt

    # ── P/E ──────────────────────────────────────────────────────────────────
    pe_val, pe_calc = None, "n/v"
    if price and eps:
        pe_val = price / eps
        pe_calc = (
            f"P/E = {price:.2f} {ccy} / {eps:.2f} {ccy} "
            f"({dcf_inputs.get('eps_source', 'IR adj. EPS')}) = {pe_val:.1f}x"
        )
    rows.append({
        "metric":             "P/E (KGV)",
        "current_value":      f"{pe_val:.1f}x" if pe_val is not None else "n/v",
        "calculation":        pe_calc,
        "peer_average":       "n/v",
        "historical_average": "n/v",
        "assessment":         "FAIR",
        "source":             dcf_inputs.get("eps_source", "n/v"),
    })

    # ── EV/EBITDA ─────────────────────────────────────────────────────────────
    ev_ebitda_val, ev_ebitda_calc = None, "n/v"
    if ev is not None and ebitda:
        ev_ebitda_val = ev / ebitda
        ev_ebitda_calc = (
            f"EV/EBITDA = ({mktcap/1e9:.0f} Mrd. + {net_debt/1e9:.0f} Mrd.) / "
            f"{ebitda/1e9:.1f} Mrd. ({dcf_inputs.get('ebitda_source', 'IR')}) "
            f"= {ev_ebitda_val:.1f}x"
        )
    rows.append({
        "metric":             "EV/EBITDA",
        "current_value":      f"{ev_ebitda_val:.1f}x" if ev_ebitda_val is not None else "n/v",
        "calculation":        ev_ebitda_calc,
        "peer_average":       "n/v",
        "historical_average": "n/v",
        "assessment":         "FAIR",
        "source":             dcf_inputs.get("ebitda_source", "n/v"),
    })

    # ── EV/FCF ────────────────────────────────────────────────────────────────
    ev_fcf_val, ev_fcf_calc = None, "n/v"
    if ev is not None and fcf:
        ev_fcf_val = ev / fcf
        ev_fcf_calc = (
            f"EV/FCF = {ev/1e9:.1f} Mrd. EV / "
            f"{fcf/1e9:.2f} Mrd. FCF ({dcf_inputs.get('fcf_source', 'IR')}) "
            f"= {ev_fcf_val:.1f}x"
        )
    rows.append({
        "metric":             "EV/FCF",
        "current_value":      f"{ev_fcf_val:.1f}x" if ev_fcf_val is not None else "n/v",
        "calculation":        ev_fcf_calc,
        "peer_average":       "n/v",
        "historical_average": "n/v",
        "assessment":         "FAIR",
        "source":             dcf_inputs.get("fcf_source", "n/v"),
    })

    # ── P/B ───────────────────────────────────────────────────────────────────
    pb_val, pb_calc = None, "n/v"
    if price and bvps:
        pb_val = price / bvps
        pb_calc = (
            f"P/B = {price:.2f} {ccy} / {bvps:.2f} {ccy} "
            f"({dcf_inputs.get('bvps_source', 'yfinance Buchwert')}) = {pb_val:.1f}x"
        )
    rows.append({
        "metric":             "P/B (Kurs/Buchwert)",
        "current_value":      f"{pb_val:.1f}x" if pb_val is not None else "n/v",
        "calculation":        pb_calc,
        "peer_average":       "n/v",
        "historical_average": "n/v",
        "assessment":         "FAIR",
        "source":             dcf_inputs.get("bvps_source", "yfinance"),
    })

    return rows


# ── Full Financial Overview (3A + 3E) ────────────────────────────────────────

def build_full_financials(
    ticker: str,
    stock_info: dict,
    financials: dict,
    cashflow_data: dict,
    ir_analysis: dict,
    forward_estimates: dict,
    historical_multiples: dict,
) -> list[dict]:
    """
    Erstellt eine 6-Jahres P&L-Übersicht (3 historisch + 3 Forward).

    Priorität historisch: IR-Dokument > yfinance income_stmt > yfinance info
    Priorität Forward:    IR-Consensus > Guidance + LLM-Ableitung

    Fehlende Werte werden als "n/v — Bloomberg/FactSet empfohlen" markiert.
    Returns liste von dicts kompatibel mit FullFinancialYear.
    """
    NV = "n/v — Bloomberg/FactSet empfohlen"
    current_year = datetime.now().year
    historical_years = [current_year - 3, current_year - 2, current_year - 1]

    # ── Historische Basisdaten aus yfinance info (TTM-Näherung) ──────────────
    try:
        stock = yf.Ticker(ticker)
        yf_info = stock.info or {}
    except Exception:
        yf_info = {}

    # Versuche Jahresabschlüsse aus yfinance annual income statement
    annual_revenue: dict[int, float] = {}
    annual_net_income: dict[int, float] = {}
    annual_ebit: dict[int, float] = {}
    try:
        inc = stock.income_stmt
        if inc is not None and not inc.empty:
            for col in inc.columns:
                try:
                    yr = col.year
                    rev_row = None
                    ni_row  = None
                    ebit_row = None
                    for key in ["Total Revenue", "Revenue"]:
                        if key in inc.index:
                            rev_row = inc.loc[key, col]
                            break
                    for key in ["Net Income", "Net Income Common Stockholders"]:
                        if key in inc.index:
                            ni_row = inc.loc[key, col]
                            break
                    for key in ["EBIT", "Operating Income"]:
                        if key in inc.index:
                            ebit_row = inc.loc[key, col]
                            break
                    if rev_row is not None:
                        annual_revenue[yr]    = float(rev_row)
                    if ni_row is not None:
                        annual_net_income[yr] = float(ni_row)
                    if ebit_row is not None:
                        annual_ebit[yr]       = float(ebit_row)
                except Exception:
                    pass
    except Exception:
        pass

    # Dividenden-Historie für DPS
    annual_dps: dict[int, float] = {}
    try:
        divs = stock.dividends
        if divs is not None and not divs.empty:
            if hasattr(divs, "squeeze"):
                divs = divs.squeeze()
            for idx, val in divs.items():
                try:
                    yr = idx.year
                    annual_dps[yr] = round(annual_dps.get(yr, 0.0) + float(val), 4)
                except Exception:
                    pass
    except Exception:
        pass

    # Cashflow-Daten aus yfinance annual
    annual_fcf: dict[int, float]   = {}
    annual_capex: dict[int, float] = {}
    try:
        cf = stock.cashflow
        if cf is not None and not cf.empty:
            for col in cf.columns:
                try:
                    yr = col.year
                    ocf_val = capex_val = None
                    for key in ["Operating Cash Flow", "Total Cash From Operating Activities"]:
                        if key in cf.index:
                            ocf_val = float(cf.loc[key, col])
                            break
                    for key in ["Capital Expenditure", "Capital Expenditures",
                                "Purchase Of Property Plant And Equipment"]:
                        if key in cf.index:
                            capex_val = float(cf.loc[key, col])
                            break
                    if ocf_val is not None and capex_val is not None:
                        annual_fcf[yr]   = ocf_val - abs(capex_val)
                        annual_capex[yr] = capex_val
                except Exception:
                    pass
    except Exception:
        pass

    # IR-Daten für das aktuellste historische Jahr
    ir_revenue    = _safe_float(ir_analysis.get("revenue_bn"))
    ir_ebitda_m   = _safe_float(ir_analysis.get("ebitda_margin_pct"))
    ir_ebit_m     = _safe_float(ir_analysis.get("recurring_ebit_margin_pct"))
    ir_eps        = _safe_float(ir_analysis.get("adjusted_eps"))
    ir_fcf        = _safe_float(ir_analysis.get("free_cashflow_bn"))
    ir_net_debt   = _safe_float(ir_analysis.get("net_debt_bn"))
    ir_year       = historical_years[-1]  # IR-Daten = aktuellstes Jahr

    # Payout-Ratio für DPS-Ableitung
    payout_ratio = _safe_float(yf_info.get("payoutRatio"))

    # Net Debt aus cashflow_data
    total_debt = _safe_float(yf_info.get("totalDebt")) or 0.0
    total_cash = _safe_float(yf_info.get("totalCash")) or 0.0
    net_debt_current = total_debt - total_cash

    result = []

    # ── 3 historische Jahre ────────────────────────────────────────────────────
    for yr in historical_years:
        is_ir_year = (yr == ir_year)
        source = "IR-Dokument" if (is_ir_year and ir_revenue) else "yfinance"

        # Revenue
        if is_ir_year and ir_revenue:
            rev_bn = round(ir_revenue, 2)
        elif yr in annual_revenue:
            rev_bn = round(annual_revenue[yr] / 1e9, 2)
        else:
            rev_bn = NV

        # EBITDA
        if is_ir_year and ir_ebitda_m and ir_revenue:
            ebitda_bn  = round(ir_revenue * ir_ebitda_m / 100, 2)
            ebitda_m   = round(ir_ebitda_m, 1)
        elif isinstance(rev_bn, float) and yr in annual_ebit:
            ebit_f    = annual_ebit[yr] / 1e9
            dep_amort = _safe_float(yf_info.get("ebitda")) or 0.0
            ebitda_bn  = round(ebit_f + (dep_amort / 1e9 * 0.25), 2)
            ebitda_m   = round(ebitda_bn / rev_bn * 100, 1) if rev_bn else NV
        else:
            ebitda_bn = NV
            ebitda_m  = NV

        # EBIT
        if is_ir_year and ir_ebit_m and ir_revenue:
            ebit_bn  = round(ir_revenue * ir_ebit_m / 100, 2)
            ebit_m   = round(ir_ebit_m, 1)
        elif yr in annual_ebit:
            ebit_bn  = round(annual_ebit[yr] / 1e9, 2)
            ebit_m   = round(annual_ebit[yr] / annual_revenue[yr] * 100, 1) if yr in annual_revenue else NV
        else:
            ebit_bn = NV
            ebit_m  = NV

        # Net Income
        ni_bn = round(annual_net_income[yr] / 1e9, 2) if yr in annual_net_income else NV

        # EPS
        if is_ir_year and ir_eps:
            eps_adj = round(ir_eps, 2)
        else:
            eps_trailing = _safe_float(yf_info.get("trailingEps"))
            eps_adj = round(eps_trailing, 2) if (eps_trailing and is_ir_year) else NV

        # DPS
        dps = round(annual_dps[yr], 2) if yr in annual_dps else NV

        # FCF
        if is_ir_year and ir_fcf:
            fcf_bn = round(ir_fcf, 2)
        elif yr in annual_fcf:
            fcf_bn = round(annual_fcf[yr] / 1e9, 2)
        else:
            fcf_bn = NV

        # Net Debt
        if is_ir_year and ir_net_debt:
            nd_bn = round(ir_net_debt, 2)
        elif is_ir_year:
            nd_bn = round(net_debt_current / 1e9, 2)
        else:
            nd_bn = NV

        # ND/EBITDA
        nd_ebitda = NV
        if isinstance(nd_bn, float) and isinstance(ebitda_bn, float) and ebitda_bn != 0:
            nd_ebitda = round(nd_bn / ebitda_bn, 2)

        # ROIC — yfinance returnOnEquity als Proxy
        roic = NV
        if is_ir_year:
            roe = _safe_float(yf_info.get("returnOnEquity"))
            roic = round(roe * 100, 1) if roe is not None else NV

        # CapEx
        if yr in annual_capex:
            capex_bn = round(abs(annual_capex[yr]) / 1e9, 2)
        else:
            capex_bn = NV

        result.append({
            "year":             f"{yr}A",
            "type":             "A",
            "revenue_bn":       rev_bn,
            "ebitda_bn":        ebitda_bn,
            "ebitda_margin_pct": ebitda_m,
            "ebit_bn":          ebit_bn,
            "ebit_margin_pct":  ebit_m,
            "net_income_bn":    ni_bn,
            "eps_adj":          eps_adj,
            "dps":              dps,
            "fcf_bn":           fcf_bn,
            "net_debt_bn":      nd_bn,
            "nd_ebitda":        nd_ebitda,
            "roic_pct":         roic,
            "capex_bn":         capex_bn,
            "source":           source,
        })

    # ── 3 Forward-Jahre ────────────────────────────────────────────────────────
    estimates = forward_estimates.get("estimates", {})
    fwd_source_base = forward_estimates.get("method", "LLM-Ableitung")

    # Historische Ausschüttungsquote für DPS-Ableitung
    hist_dps_vals = [v for v in annual_dps.values() if v > 0]
    hist_eps_vals = []
    for yr2 in historical_years:
        if yr2 in annual_net_income and yr2 in annual_revenue:
            shares = _safe_float(yf_info.get("sharesOutstanding"))
            if shares and shares > 0:
                hist_eps_vals.append(annual_net_income[yr2] / shares)

    avg_payout = payout_ratio if payout_ratio else (
        (sum(hist_dps_vals) / sum(hist_eps_vals)) if hist_dps_vals and hist_eps_vals else 0.4
    )

    for fwd_year in ["2026E", "2027E", "2028E"]:
        est = estimates.get(fwd_year, {})
        if not est:
            result.append({
                "year": fwd_year, "type": "E",
                "revenue_bn": NV, "ebitda_bn": NV, "ebitda_margin_pct": NV,
                "ebit_bn": NV, "ebit_margin_pct": NV, "net_income_bn": NV,
                "eps_adj": NV, "dps": NV, "fcf_bn": NV,
                "net_debt_bn": NV, "nd_ebitda": NV, "roic_pct": NV, "capex_bn": NV,
                "source": "LLM-Ableitung — kein Bloomberg/FactSet Konsens verfügbar",
            })
            continue

        rev_f      = _safe_float(est.get("revenue_bn"))
        ebitda_m_f = _safe_float(est.get("ebitda_margin_pct"))
        ebit_m_f   = _safe_float(est.get("ebit_margin_pct"))
        eps_f      = _safe_float(est.get("eps"))
        fcf_f      = _safe_float(est.get("fcf_bn"))

        ebitda_f  = round(rev_f * ebitda_m_f / 100, 2) if (rev_f and ebitda_m_f) else NV
        ebit_f    = round(rev_f * ebit_m_f / 100, 2)   if (rev_f and ebit_m_f)   else NV

        # Net Income-Näherung aus EPS × Aktien
        ni_f = NV
        shares = _safe_float(yf_info.get("sharesOutstanding"))
        if eps_f and shares:
            ni_f = round(eps_f * shares / 1e9, 2)

        # DPS aus Payout-Ratio × EPS
        dps_f = NV
        if eps_f and avg_payout:
            dps_f = round(eps_f * float(avg_payout), 2)

        # ND/EBITDA — letzte bekannte ND + FCF-Reduktion
        nd_f      = NV
        nd_eb_f   = NV
        if isinstance(ebitda_f, float) and ebitda_f != 0:
            last_nd = ir_net_debt if ir_net_debt else (net_debt_current / 1e9)
            if fcf_f and isinstance(fcf_f, float):
                offset = (list(estimates.keys()).index(fwd_year) + 1)
                nd_f    = round(last_nd - fcf_f * offset * 0.5, 2)
                nd_eb_f = round(nd_f / ebitda_f, 2)

        # CapEx-Näherung: historisches CapEx/Revenue-Verhältnis
        capex_f = NV
        last_capex_ratio = None
        if annual_capex and annual_revenue:
            ratios = [abs(annual_capex[y]) / annual_revenue[y]
                      for y in historical_years if y in annual_capex and y in annual_revenue]
            if ratios:
                last_capex_ratio = sum(ratios) / len(ratios)
        if rev_f and last_capex_ratio:
            capex_f = round(rev_f * last_capex_ratio, 2)

        est_src = est.get("source", "LLM-Ableitung")
        src_label = (
            f"{fwd_source_base} | {est_src} | "
            "LLM-basierte Approximation. Kein Ersatz für Bloomberg/FactSet Konsensdaten"
        )

        result.append({
            "year":             fwd_year,
            "type":             "E",
            "revenue_bn":       _round2(rev_f),
            "ebitda_bn":        ebitda_f,
            "ebitda_margin_pct": _round1(ebitda_m_f),
            "ebit_bn":          ebit_f,
            "ebit_margin_pct":  _round1(ebit_m_f),
            "net_income_bn":    ni_f,
            "eps_adj":          _round2(eps_f),
            "dps":              dps_f,
            "fcf_bn":           _round2(fcf_f),
            "net_debt_bn":      nd_f,
            "nd_ebitda":        nd_eb_f,
            "roic_pct":         NV,
            "capex_bn":         capex_f,
            "source":           src_label,
        })

    return result


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
