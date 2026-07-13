import yfinance as yf
from dataclasses import dataclass
import logging
from tools.period_classifier import (
    QuarterlySignal,
    validate_yfinance_annual_columns,
    check_ratio_guard,
)

logger = logging.getLogger(__name__)

@dataclass
class MultipleResult:
    value:   float | None
    formula: str
    inputs:  dict
    source:  str
    valid:   bool

class MultiplesEngine:
    def __init__(self, **kwargs):
        # Wir nutzen kwargs, um flexibel zu bleiben
        self.price     = kwargs.get("current_price")
        self.mktcap    = kwargs.get("market_cap")
        self.shares    = kwargs.get("shares_outstanding")
        self.currency  = kwargs.get("currency", "n/v")
        self.price_src = kwargs.get("price_source", "yfinance")
        
        # Finanzdaten
        self.revenue   = kwargs.get("revenue")
        self.ebitda    = kwargs.get("ebitda")
        self.ebit      = kwargs.get("ebit")
        self.gp        = kwargs.get("gross_profit")
        self.ni        = kwargs.get("net_income")
        self.fcf       = kwargs.get("fcf")
        self.debt      = kwargs.get("total_debt", 0)
        self.cash      = kwargs.get("total_cash", 0)
        self.equity    = kwargs.get("total_equity")
        self.assets    = kwargs.get("total_assets")
        self.interest  = kwargs.get("interest_expense")
        self.eps       = kwargs.get("eps")
        self.dps       = kwargs.get("dps")
        self.ic        = kwargs.get("invested_capital")
        self.nopat_val = kwargs.get("nopat")
        self.rev_prev  = kwargs.get("revenue_prev")
        self.eps_prev  = kwargs.get("eps_prev")
        self.fin_src   = kwargs.get("financial_source", "Mixed")

        # Enterprise Value Berechnung
        self._ev = None
        if self.mktcap is not None:
            self._ev = round(self.mktcap + (self.debt or 0) - (self.cash or 0), 3)

        # Period-guard state (set by from_ticker; default = no guard)
        self._fcf_suspect: bool = False
        self._guard_warnings: list[str] = []
        self._quarterly_signal: QuarterlySignal | None = None

    @classmethod
    def from_ticker(
        cls,
        ticker:           str,
        ir_analysis:      dict,
        financial_source: str        = "IR-Dokument",
        hist_data:        dict | None = None,
    ) -> "MultiplesEngine":
        stock   = yf.Ticker(ticker)
        yf_info = stock.info

        def safe_f(val, scale=1.0):
            try:
                if val in (None, "n/v", "not found", "", "-"): return None
                return float(val) * scale
            except Exception: return None

        # 1. Basis-Daten (yfinance)
        price  = yf_info.get("currentPrice") or yf_info.get("regularMarketPrice")
        mktcap = safe_f(yf_info.get("marketCap"), 1e-9)          # Mrd.
        shares = safe_f(yf_info.get("sharesOutstanding"), 1e-9)   # Mrd.

        # 2. Finanzdaten — IR zuerst, dann yfinance
        # Revenue
        rev = safe_f(ir_analysis.get("revenue_bn"))
        if rev is None: rev = safe_f(yf_info.get("totalRevenue"), 1e-9)

        # EBITDA — 4-stufige Fallback-Kette (CH/EU-Titel: yfinance "ebitda" oft None)
        ebitda = safe_f(ir_analysis.get("ebitda_bn"))
        if ebitda is None:
            ebitda_m = safe_f(ir_analysis.get("ebitda_margin_pct"))
            if rev and ebitda_m: ebitda = rev * (ebitda_m / 100)
        if ebitda is None: ebitda = safe_f(yf_info.get("ebitda"), 1e-9)
        if ebitda is None:
            # ebitdaMargins × totalRevenue als letzter Fallback
            em = safe_f(yf_info.get("ebitdaMargins"))
            tr = safe_f(yf_info.get("totalRevenue"), 1e-9)
            if em and tr: ebitda = em * tr

        # EBIT
        ebit = safe_f(ir_analysis.get("ebit_bn"))
        if ebit is None:
            ebit_m = safe_f(ir_analysis.get("recurring_ebit_margin_pct") or ir_analysis.get("ebit_margin_pct"))
            if rev and ebit_m: ebit = rev * (ebit_m / 100)
        if ebit is None: ebit = safe_f(yf_info.get("operatingCashflow"), 1e-9)

        # Gross Profit
        gp = safe_f(ir_analysis.get("gross_profit_bn"))
        if gp is None: gp = safe_f(yf_info.get("grossProfits"), 1e-9)

        # EPS / Net Income
        eps = safe_f(ir_analysis.get("adjusted_eps"))
        if eps is None: eps = safe_f(yf_info.get("trailingEps"))

        ni = safe_f(ir_analysis.get("net_income_bn"))
        if ni is None and eps and shares: ni = eps * shares
        if ni is None: ni = safe_f(yf_info.get("netIncomeToCommon"), 1e-9)

        # Cash & Debt
        net_debt = safe_f(ir_analysis.get("net_debt_bn"))
        debt     = safe_f(yf_info.get("totalDebt"), 1e-9)
        cash     = safe_f(yf_info.get("totalCash"), 1e-9)
        if net_debt is not None:
            debt = net_debt if net_debt > 0 else 0
            cash = abs(net_debt) if net_debt < 0 else 0

        # ── FCF with period guards ──────────────────────────────────────────
        _guard_warnings: list[str] = []
        _fcf_suspect = False

        fcf_ir  = safe_f(ir_analysis.get("free_cashflow_bn"))
        fcf_yf  = safe_f(yf_info.get("freeCashflow"), 1e-9)
        cfo_ttm = safe_f(yf_info.get("operatingCashflow"), 1e-9)

        # --- Prior-year FCF from annual cashflow (for ratio-to-prior guard) ---
        prior_fcf: float | None = None
        _cf_valid = True
        try:
            cf_annual = stock.cashflow
            _cf_valid, _col_warn = validate_yfinance_annual_columns(cf_annual)
            if not _cf_valid and _col_warn:
                _guard_warnings.append(_col_warn)
            if cf_annual is not None and not cf_annual.empty and len(cf_annual.columns) >= 2:
                _CFO_KEYS   = ["Operating Cash Flow", "Total Cash From Operating Activities",
                               "Cash From Operations"]
                _CAPEX_KEYS = ["Capital Expenditure", "Capital Expenditures",
                               "Purchase Of Property Plant And Equipment"]
                # Use column 1 = prior fiscal year (column 0 = most recent)
                _col1 = cf_annual.iloc[:, 1]
                _cfo_p, _capex_p = None, None
                for k in _CFO_KEYS:
                    if k in _col1.index:
                        try: _cfo_p = float(_col1[k]); break
                        except Exception: pass
                for k in _CAPEX_KEYS:
                    if k in _col1.index:
                        try: _capex_p = float(_col1[k]); break
                        except Exception: pass
                if _cfo_p is not None and _capex_p is not None:
                    prior_fcf = round((_cfo_p - abs(_capex_p)) * 1e-9, 3)
        except Exception:
            pass

        # --- Cross-source validation: IR vs yfinance TTM ---
        fcf = fcf_ir
        if fcf_ir is not None and fcf_yf is not None and fcf_yf > 0:
            ratio = fcf_ir / fcf_yf
            if not (0.40 <= ratio <= 1.75):
                _guard_warnings.append(
                    f"⚠ FCF perioden-kontaminiert: IR {fcf_ir:.2f} Mrd vs "
                    f"yfinance TTM {fcf_yf:.2f} Mrd (Ratio {ratio:.2f}) — "
                    "IR-FCF likely aus Interim-PDF; yfinance TTM bevorzugt"
                )
                _fcf_suspect = True
                fcf = fcf_yf  # prefer yfinance TTM which is annual/TTM
        elif fcf_ir is None:
            fcf = fcf_yf

        # --- Ratio-to-Prior-Year guard on the chosen FCF candidate ---
        if fcf is not None and prior_fcf is not None and prior_fcf > 0:
            passed, w = check_ratio_guard(fcf, prior_fcf, label="FCF")
            if not passed:
                _guard_warnings.append(w)
                _fcf_suspect = True

        # --- FCF/CFO conversion band [0.30, 1.15] ---
        if fcf is not None and cfo_ttm is not None and cfo_ttm > 0:
            conv = fcf / cfo_ttm
            if not (0.30 <= conv <= 1.15):
                _guard_warnings.append(
                    f"⚠ FCF/CFO-Band: {fcf:.2f}/{cfo_ttm:.2f} = {conv:.2f} "
                    "ausserhalb [0.30, 1.15] — FCF-Input periodenverdächtig"
                )
                _fcf_suspect = True

        # Emit all guard warnings to the Live-Reasoning panel
        for _w in _guard_warnings:
            print(_w)

        # --- Quarterly signal (for forward estimates only) ---
        _quarterly_signal: QuarterlySignal | None = None
        try:
            qcf = stock.quarterly_cashflow
            if qcf is not None and not qcf.empty:
                _CFO_KEYS   = ["Operating Cash Flow", "Total Cash From Operating Activities"]
                _CAPEX_KEYS = ["Capital Expenditure", "Capital Expenditures",
                               "Purchase Of Property Plant And Equipment"]
                _cols_q = sorted(qcf.columns, reverse=True)

                def _qval(col, keys):
                    for k in keys:
                        if k in qcf[col].index:
                            try: return float(qcf[col][k])
                            except Exception: pass
                    return None

                q_cfos   = [(_c, v) for _c in _cols_q if (_v := _qval(_c, _CFO_KEYS))   is not None for v in [_v]]
                q_capexs = [(_c, v) for _c in _cols_q if (_v := _qval(_c, _CAPEX_KEYS)) is not None for v in [_v]]

                raw_q_fcf, run_rate, yoy_g, qoq_g = None, None, None, None
                if q_cfos and q_capexs:
                    cfo0 = q_cfos[0][1]; cap0 = q_capexs[0][1]
                    raw_q_fcf = round((cfo0 - abs(cap0)) * 1e-9, 3)
                if len(q_cfos) >= 4 and len(q_capexs) >= 4:
                    run_rate = round(
                        (sum(v for _, v in q_cfos[:4]) - abs(sum(v for _, v in q_capexs[:4]))) * 1e-9,
                        3,
                    )
                if len(q_cfos) >= 5:
                    py_v = q_cfos[4][1]
                    if py_v != 0:
                        yoy_g = round((q_cfos[0][1] - py_v) / abs(py_v) * 100, 1)
                if len(q_cfos) >= 2 and q_cfos[1][1] != 0:
                    qoq_g = round((q_cfos[0][1] - q_cfos[1][1]) / abs(q_cfos[1][1]) * 100, 1)

                # Depressed prior-year comp: prior-year Q < 60% of 4-quarter average
                comp_depressed = False
                if len(q_cfos) >= 5:
                    avg4 = sum(v for _, v in q_cfos[:4]) / 4
                    if avg4 != 0 and q_cfos[4][1] < 0.60 * avg4:
                        comp_depressed = True

                _pe = None
                try:
                    _pe = _cols_q[0].date()
                except Exception:
                    pass

                _quarterly_signal = QuarterlySignal(
                    ticker=ticker,
                    source_metric="fcf",
                    raw_q_value=raw_q_fcf,
                    yoy_comparable_growth=yoy_g,
                    qoq_growth=qoq_g,
                    run_rate_ttm=run_rate,
                    prior_year_comp_depressed=comp_depressed,
                    period_end=_pe,
                    guard_messages=list(_guard_warnings),
                )
        except Exception as _e:
            logger.debug("QuarterlySignal extraction failed: %s", _e)

        # Equity — IR → yfinance totalStockholderEquity → bookValue × shares
        equity = safe_f(ir_analysis.get("total_equity_bn"))
        if equity is None: equity = safe_f(yf_info.get("totalStockholderEquity"), 1e-9)
        if equity is None:
            bvps = safe_f(yf_info.get("bookValue"))
            if bvps and shares:
                equity = bvps * shares   # BVPS (CHF/Aktie) × Aktien (Mrd.) = Mrd. CHF

        # Assets
        assets = safe_f(ir_analysis.get("total_assets_bn"))
        if assets is None: assets = safe_f(yf_info.get("totalAssets"), 1e-9)

        # 3. Historische Vorjahreswerte aus hist_data (für Wachstumsberechnung)
        rev_prev = None
        eps_prev = None
        dps_hist = None
        if hist_data:
            sorted_years = sorted(hist_data.keys(), reverse=True)
            if len(sorted_years) >= 2:
                prev_yr  = sorted_years[1]
                rev_prev = safe_f(hist_data[prev_yr].get("revenue_bn"))
                eps_prev = safe_f(hist_data[prev_yr].get("eps"))
            if sorted_years:
                dps_hist = safe_f(hist_data[sorted_years[0]].get("dps"))

        # DPS — IR → hist_data → yfinance dividendRate
        dps = (
            safe_f(ir_analysis.get("dividend_per_share"))
            or dps_hist
            or safe_f(yf_info.get("dividendRate"))
        )

        engine = cls(
            current_price=price,
            market_cap=mktcap,
            shares_outstanding=shares,
            currency=yf_info.get("currency", "CHF"),
            revenue=rev,
            ebitda=ebitda,
            ebit=ebit,
            gross_profit=gp,
            net_income=ni,
            fcf=fcf,
            total_debt=debt,
            total_cash=cash,
            total_equity=equity,
            total_assets=assets,
            eps=eps,
            dps=dps,
            revenue_prev=rev_prev,
            eps_prev=eps_prev,
            financial_source=financial_source,
        )
        engine._fcf_suspect      = _fcf_suspect
        engine._guard_warnings   = _guard_warnings
        engine._quarterly_signal = _quarterly_signal
        return engine

    # ── Berechnungs-Helfer ────────────────────────────────────────────────────

    def _r(self, v) -> float | None:
        return round(v, 2) if v is not None else None

    def _ratio(self, label: str, num, den, suffix: str = "x") -> dict:
        src = f"yfinance Kurs + {self.fin_src}"
        if num is None or den is None or den == 0:
            return {"valid": False, "value": None, "formula": f"{label} = -", "source": src}
        val = round(num / den, 2)
        return {
            "valid":   True,
            "value":   val,
            "formula": f"{label} = {self._r(num)} / {self._r(den)} = {val}{suffix}",
            "source":  src,
        }

    def _pct(self, label: str, num, den) -> dict:
        src = self.fin_src
        if num is None or den is None or den == 0:
            return {"valid": False, "value": None, "formula": f"{label} = -", "source": src}
        val = round(num / den * 100, 1)
        return {
            "valid":   True,
            "value":   val,
            "formula": f"{label} = {self._r(num)} / {self._r(den)} = {val}%",
            "source":  src,
        }

    # ── compute_all ───────────────────────────────────────────────────────────

    def compute_all(self) -> dict:
        """Berechnet alle 16 Kennzahlen deterministisch. Gibt dict zurück."""
        ev  = self._ev
        mc  = self.mktcap
        nd  = (self.debt or 0) - (self.cash or 0)
        cap = (self.equity or 0) + nd  # Invested Capital Näherung

        results: dict = {}

        # Enterprise-Value Multiples
        results["ev_ebitda"]  = self._ratio("EV/EBITDA",  ev, self.ebitda)
        results["ev_ebit"]    = self._ratio("EV/EBIT",    ev, self.ebit)
        results["ev_sales"]   = self._ratio("EV/Umsatz",  ev, self.revenue)
        results["ev_fcf"]     = self._ratio("EV/FCF",     ev, self.fcf)

        # Preis-Multiples
        results["pe_ratio"]   = self._ratio("P/E",   mc, self.ni)
        results["pb_ratio"]   = self._ratio("P/B",   mc, self.equity)
        results["ps_ratio"]   = self._ratio("P/S",   mc, self.revenue)
        results["p_fcf"]      = self._ratio("P/FCF", mc, self.fcf)

        # Yield
        if self.dps and self.price and self.price > 0:
            val = round(self.dps / self.price * 100, 2)
            results["dividend_yield"] = {
                "valid":   True, "value": val,
                "formula": f"DPS {self.dps} / Kurs {self.price} = {val}%",
                "source":  f"yfinance Kurs + {self.fin_src}",
            }
        else:
            results["dividend_yield"] = {"valid": False, "value": None,
                                         "formula": "DPS / Kurs = -", "source": self.fin_src}

        if self.fcf and mc and mc > 0:
            val = round(self.fcf / mc * 100, 2)
            results["fcf_yield"] = {
                "valid":   True, "value": val,
                "formula": f"FCF {self._r(self.fcf)} / MarktKap {self._r(mc)} = {val}%",
                "source":  f"yfinance Kurs + {self.fin_src}",
            }
        else:
            results["fcf_yield"] = {"valid": False, "value": None,
                                    "formula": "FCF / MarktKap = -", "source": self.fin_src}

        # Verschuldung
        if self.ebitda and self.ebitda != 0:
            val = round(nd / self.ebitda, 2)
            results["nd_ebitda"] = {
                "valid":   True, "value": val,
                "formula": f"NetDebt {self._r(nd)} / EBITDA {self._r(self.ebitda)} = {val}x",
                "source":  self.fin_src,
            }
        else:
            results["nd_ebitda"] = {"valid": False, "value": None,
                                    "formula": "NetDebt / EBITDA = -", "source": self.fin_src}

        # Margen
        results["ebitda_margin"]  = self._pct("EBITDA-Marge",  self.ebitda, self.revenue)
        results["ebit_margin"]    = self._pct("EBIT-Marge",    self.ebit,   self.revenue)
        results["net_margin"]     = self._pct("Nettomarge",    self.ni,     self.revenue)
        results["gross_margin"]   = self._pct("Bruttomarge",   self.gp,     self.revenue)
        results["fcf_conversion"] = self._pct("FCF-Conversion", self.fcf,   self.ni)

        # Renditen
        results["roe"]  = self._pct("ROE",  self.ni,     self.equity)
        results["roa"]  = self._pct("ROA",  self.ni,     self.assets)
        if self.nopat_val and self.ic and self.ic != 0:
            results["roic"] = self._pct("ROIC", self.nopat_val, self.ic)
        else:
            results["roic"] = self._pct("ROIC (EBIT/Kapital)", self.ebit, cap if cap != 0 else None)

        # Wachstum
        if self.rev_prev and self.rev_prev != 0 and self.revenue:
            val = round((self.revenue - self.rev_prev) / self.rev_prev * 100, 1)
            results["revenue_growth"] = {
                "valid":   True, "value": val,
                "formula": f"Umsatz ({self._r(self.revenue)} - {self._r(self.rev_prev)}) / {self._r(self.rev_prev)} = {val}%",
                "source":  self.fin_src,
            }
        else:
            results["revenue_growth"] = {"valid": False, "value": None,
                                         "formula": "Umsatz YoY = -", "source": self.fin_src}

        if self.eps_prev and self.eps_prev != 0 and self.eps:
            val = round((self.eps - self.eps_prev) / self.eps_prev * 100, 1)
            results["eps_growth"] = {
                "valid":   True, "value": val,
                "formula": f"EPS ({self.eps} - {self.eps_prev}) / {self.eps_prev} = {val}%",
                "source":  self.fin_src,
            }
        else:
            results["eps_growth"] = {"valid": False, "value": None,
                                     "formula": "EPS YoY = -", "source": self.fin_src}

        # ── Period Guards ──────────────────────────────────────────────────────
        _FCF_METRICS = ("ev_fcf", "p_fcf", "fcf_yield", "fcf_conversion")
        _gw = "; ".join(self._guard_warnings) if self._guard_warnings else ""

        if self._fcf_suspect:
            # FCF input is contaminated — suppress all FCF-derived metrics
            for k in _FCF_METRICS:
                if results.get(k, {}).get("valid"):
                    results[k] = {
                        "valid":   False,
                        "value":   None,
                        "formula": f"{k} = unterdrückt (FCF perioden-kontaminiert)",
                        "source":  self.fin_src,
                        "warning": _gw,
                    }
        else:
            # Absolute sanity bounds (catch remaining edge cases)
            ev_fcf_val = results.get("ev_fcf", {}).get("value")
            if ev_fcf_val is not None and ev_fcf_val > 80:
                msg = f"⚠ EV/FCF {ev_fcf_val}x > 80x Schwelle — FCF-Input periodenverdächtig"
                print(msg)
                results["ev_fcf"] = {
                    "valid": False, "value": None,
                    "formula": f"EV/FCF = {ev_fcf_val}x unterdrückt (> 80x Schwelle)",
                    "source": self.fin_src, "warning": msg,
                }

            fcf_yield_val = results.get("fcf_yield", {}).get("value")
            if (fcf_yield_val is not None
                    and self.fcf is not None and self.fcf > 0
                    and fcf_yield_val < 0.5):
                msg = f"⚠ FCF-Yield {fcf_yield_val}% < 0.5% Schwelle — periodenverdächtig"
                print(msg)
                results["fcf_yield"] = {
                    "valid": False, "value": None,
                    "formula": f"FCF-Yield = {fcf_yield_val}% unterdrückt (< 0.5%)",
                    "source": self.fin_src, "warning": msg,
                }

            fcf_conv_val = results.get("fcf_conversion", {}).get("value")
            if (fcf_conv_val is not None
                    and self.ni is not None and self.ni > 0
                    and not (30.0 <= fcf_conv_val <= 115.0)):
                msg = (
                    f"⚠ FCF-Conversion {fcf_conv_val}% ausserhalb [30%, 115%] "
                    "— periodenverdächtig"
                )
                print(msg)
                results["fcf_conversion"] = {
                    "valid": False, "value": None,
                    "formula": f"FCF-Conversion = {fcf_conv_val}% unterdrückt ([30%,115%])",
                    "source": self.fin_src, "warning": msg,
                }

        # ── Meta-Felder ────────────────────────────────────────────────────────
        ev_str = (
            f"EV = MarktKap {self._r(mc)} + Schulden {self._r(self.debt or 0)} "
            f"- Cash {self._r(self.cash or 0)} = {self._r(ev)} Mrd."
            if ev is not None else "EV = -"
        )
        results["_enterprise_value"] = {"formula": ev_str}
        results["_price_data"] = {
            "current_price": self.price,
            "market_cap_bn": mc,
            "currency":      self.currency,
        }
        results["_guard_warnings"]   = list(self._guard_warnings)
        results["_quarterly_signal"] = (
            self._quarterly_signal.to_dict() if self._quarterly_signal else None
        )

        valid_n = sum(1 for k, v in results.items()
                      if not k.startswith("_") and isinstance(v, dict) and v.get("valid"))
        total_n = sum(1 for k in results if not k.startswith("_"))
        results["_summary"] = {"valid": valid_n, "total_calculated": total_n}

        return results


def compute_historical_averages(ticker: str, annual_rows: list[dict], n_years: int = 5) -> dict:
    """
    Historische Durchschnitte der Bewertungsmultiples (EV/EBITDA, P/E, EV/Sales,
    P/B, FCF-Yield, Dividend-Yield), deterministisch aus financial_db-
    Fundamentaldaten + yfinance-Jahresend-Kursen berechnet — unabhängig von
    Finnhub. Setzt voraus, dass annual_rows echte period_end-Daten tragen
    (siehe Phase 7: Perioden-Enden sind jetzt bei allen Quellen echte Daten,
    kein f"{jahr}-12-31"-Hardcode mehr).

    annual_rows: Zeilen aus financial_db.get_annual_history(ticker), neuestes
    Jahr zuerst oder zuletzt (Reihenfolge egal, wird hier selbst sortiert).

    Returns: {"ev_ebitda": float, "pe_ratio": float, "ev_sales": float,
              "pb_ratio": float, "fcf_yield": float, "dividend_yield": float,
              "years_used": [int, ...]} — Schlüssel fehlen, wenn für keine
    Periode genug Daten (Kurs + Fundamentalwert) vorlagen. Nie erfundene Werte.
    """
    from datetime import datetime as _dt
    import pandas as pd

    rows = [r for r in (annual_rows or []) if r.get("period_end")]
    rows = sorted(rows, key=lambda r: r["period_end"], reverse=True)[:n_years]
    if not rows:
        return {}

    oldest_end = min(r["period_end"] for r in rows)
    try:
        stock = yf.Ticker(ticker)
        price_hist = stock.history(
            start=oldest_end, end=_dt.now().strftime("%Y-%m-%d"), interval="1d",
        )
    except Exception as e:
        logger.warning(f"compute_historical_averages: Kursabruf fehlgeschlagen ({ticker}): {e}")
        return {}
    if price_hist is None or price_hist.empty:
        return {}

    def _price_near(date_str: str) -> float | None:
        try:
            target = pd.Timestamp(date_str)
        except Exception:
            return None
        idx = price_hist.index
        if idx.tz is not None:
            target = target.tz_localize(idx.tz) if target.tzinfo is None else target.tz_convert(idx.tz)
        pos = idx.get_indexer([target], method="nearest")
        if len(pos) == 0 or pos[0] == -1:
            return None
        return float(price_hist["Close"].iloc[pos[0]])

    metrics: dict[str, list[float]] = {
        "ev_ebitda": [], "pe_ratio": [], "ev_sales": [],
        "pb_ratio": [], "fcf_yield": [], "dividend_yield": [],
    }
    years_used: list[int] = []

    for r in rows:
        price = _price_near(r["period_end"])
        shares = r.get("shares_bn")
        if price is None or not shares:
            continue
        market_cap = price * shares  # Mrd. (shares_bn ist in Mrd. Aktien)
        net_debt = r.get("net_debt_bn") or 0
        ev = market_cap + net_debt
        used_this_year = False

        ebitda = r.get("ebitda_bn")
        if ebitda and ebitda > 0:
            metrics["ev_ebitda"].append(ev / ebitda)
            used_this_year = True

        eps = r.get("eps_adj")
        if eps and eps > 0:
            metrics["pe_ratio"].append(price / eps)
            used_this_year = True

        revenue = r.get("revenue_bn")
        if revenue and revenue > 0:
            metrics["ev_sales"].append(ev / revenue)
            used_this_year = True

        equity = r.get("total_equity_bn")
        if equity and equity > 0:
            metrics["pb_ratio"].append(market_cap / equity)
            used_this_year = True

        fcf = r.get("fcf_bn")
        if fcf is not None and market_cap > 0:
            metrics["fcf_yield"].append(fcf / market_cap * 100)
            used_this_year = True

        dps = r.get("dps")
        if dps and price > 0:
            metrics["dividend_yield"].append(dps / price * 100)
            used_this_year = True

        if used_this_year:
            years_used.append(r["fiscal_year"])

    averages = {k: round(sum(v) / len(v), 2) for k, v in metrics.items() if v}
    if averages:
        averages["years_used"] = sorted(set(years_used), reverse=True)
    return averages