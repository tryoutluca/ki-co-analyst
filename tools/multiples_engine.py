import yfinance as yf
from dataclasses import dataclass
import logging

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

        # FCF
        fcf = safe_f(ir_analysis.get("free_cashflow_bn"))
        if fcf is None: fcf = safe_f(yf_info.get("freeCashflow"), 1e-9)

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

        return cls(
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

        # Meta-Felder
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
        valid_n = sum(1 for k, v in results.items()
                      if not k.startswith("_") and isinstance(v, dict) and v.get("valid"))
        total_n = sum(1 for k in results if not k.startswith("_"))
        results["_summary"] = {"valid": valid_n, "total_calculated": total_n}

        return results