"""
multiples_engine.py — Deterministische Bewertungskennzahlen
KI-Co-Analyst | Bachelor Thesis BFH 2025/26 | Luca Lüdi

Alle Multiples werden mathematisch berechnet — kein LLM,
keine Halluzination. Jede Berechnung dokumentiert Formel
und Datenquelle.

Datenquellen:
  Aktueller Kurs + MarktKap: yfinance (primär)
  Fundamentaldaten:          IR-RAG Pipeline (CH/EU)
                             SEC EDGAR XBRL (US)
"""

import yfinance as yf
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class MultipleResult:
    value:   float | None
    formula: str        # vollständige Herleitung
    inputs:  dict       # alle Input-Werte
    source:  str        # Datenquelle
    valid:   bool       # False wenn Input fehlt/negativ


def get_price_and_marketcap(ticker: str) -> dict:
    """
    Holt aktuellen Kurs und MarktKap via yfinance.

    Returns:
        {
            "current_price": float | None,
            "market_cap":    float | None,  # in Mrd.
            "currency":      str,
            "shares":        float | None,  # in Mrd.
            "source":        str,
            "error":         str | None,
        }
    """
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info

        price = (
            info.get("currentPrice") or
            info.get("regularMarketPrice") or
            info.get("previousClose")
        )

        mktcap_raw = info.get("marketCap")
        mktcap_bn  = round(mktcap_raw / 1e9, 3) if mktcap_raw else None

        shares_raw = info.get("sharesOutstanding")
        shares_bn  = round(shares_raw / 1e9, 4) if shares_raw else None

        # Falls MarktKap fehlt: aus Kurs × Aktienanzahl
        if not mktcap_bn and price and shares_bn:
            mktcap_bn = round(price * shares_bn, 3)

        currency = info.get("currency", "n/v")

        if not price:
            return {
                "current_price": None,
                "market_cap":    None,
                "currency":      currency,
                "shares":        shares_bn,
                "source":        "yfinance",
                "error":         f"Kurs für {ticker} nicht verfügbar",
            }

        return {
            "current_price": round(float(price), 2),
            "market_cap":    mktcap_bn,
            "currency":      currency,
            "shares":        shares_bn,
            "source":        "yfinance",
            "error":         None,
        }

    except Exception as e:
        logger.warning(f"yfinance Fehler für {ticker}: {e}")
        return {
            "current_price": None,
            "market_cap":    None,
            "currency":      "n/v",
            "shares":        None,
            "source":        "yfinance",
            "error":         str(e),
        }


class MultiplesEngine:
    """
    Berechnet alle Bewertungskennzahlen deterministisch.

    Verwendung:
        engine = MultiplesEngine.from_ticker(
            ticker      = "HOLN.SW",
            ir_analysis = ir_data,
        )
        multiples = engine.compute_all()
    """

    def __init__(
        self,
        # ── Live-Daten (yfinance) ─────────────────────────
        current_price:      float | None = None,
        market_cap:         float | None = None,  # Mrd.
        shares_outstanding: float | None = None,  # Mrd.
        currency:           str          = "n/v",
        price_source:       str          = "yfinance",

        # ── Finanzdaten (IR-RAG / SEC EDGAR) ─────────────
        revenue:            float | None = None,  # Mrd.
        ebitda:             float | None = None,  # Mrd.
        ebit:               float | None = None,  # Mrd.
        gross_profit:       float | None = None,  # Mrd.
        net_income:         float | None = None,  # Mrd.
        fcf:                float | None = None,  # Mrd.
        total_debt:         float | None = None,  # Mrd.
        total_cash:         float | None = None,  # Mrd.
        total_equity:       float | None = None,  # Mrd.
        total_assets:       float | None = None,  # Mrd.
        interest_expense:   float | None = None,  # Mrd.
        eps:                float | None = None,
        dps:                float | None = None,
        invested_capital:   float | None = None,  # Mrd.
        nopat:              float | None = None,  # Mrd.

        # ── Vorjahreswerte für Wachstum ───────────────────
        revenue_prev:       float | None = None,
        eps_prev:           float | None = None,

        # ── Quellenangaben ────────────────────────────────
        financial_source:   str = "IR-Dokument",
    ):
        self.price     = current_price
        self.mktcap    = market_cap
        self.shares    = shares_outstanding
        self.currency  = currency
        self.price_src = price_source
        self.revenue   = revenue
        self.ebitda    = ebitda
        self.ebit      = ebit
        self.gp        = gross_profit
        self.ni        = net_income
        self.fcf       = fcf
        self.debt      = total_debt
        self.cash      = total_cash
        self.equity    = total_equity
        self.assets    = total_assets
        self.interest  = interest_expense
        self.eps       = eps
        self.dps       = dps
        self.ic        = invested_capital
        self.nopat_val = nopat
        self.rev_prev  = revenue_prev
        self.eps_prev  = eps_prev
        self.fin_src   = financial_source

        # Enterprise Value einmal ableiten
        self._ev         = None
        self._ev_formula = "EV: Inputs fehlen"

        if self.mktcap is not None:
            debt_val = self.debt or 0
            cash_val = self.cash or 0
            self._ev = round(self.mktcap + debt_val - cash_val, 3)
            self._ev_formula = (
                f"EV = MarktKap {self.mktcap:.2f} Mrd. "
                f"+ Schulden {debt_val:.2f} Mrd. "
                f"- Cash {cash_val:.2f} Mrd. "
                f"= {self._ev:.2f} Mrd. {self.currency}"
            )

    @classmethod
    def from_ticker(
        cls,
        ticker:           str,
        ir_analysis:      dict,
        financial_source: str = "IR-Dokument",
    ) -> "MultiplesEngine":
        """
        Factory-Methode: Holt Kurs/MarktKap von yfinance,
        Fundamentaldaten aus ir_analysis.

        ir_analysis erwartet Felder aus ir_rag_tool.py:
          revenue_bn, ebitda_margin_pct,
          recurring_ebit_margin_pct, adjusted_eps,
          free_cashflow_bn, net_debt_bn, dps etc.
        """
        # ── Schritt 1: Live-Daten von yfinance ────────────
        price_data = get_price_and_marketcap(ticker)

        if price_data["error"]:
            logger.warning(
                f"Kurs-Daten für {ticker} unvollständig: "
                f"{price_data['error']}"
            )

        # ── Schritt 2: Finanzdaten aus IR ─────────────────

        def safe_float(val):
            try:
                return float(val) if val not in (None, "n/v", "not found", "") else None
            except (ValueError, TypeError):
                return None

        revenue = safe_float(ir_analysis.get("revenue_bn"))

        # EBITDA: aus Marge × Umsatz berechnen
        ebitda = None
        ebitda_m = safe_float(ir_analysis.get("ebitda_margin_pct"))
        if revenue and ebitda_m:
            ebitda = round(revenue * ebitda_m / 100, 3)

        # EBIT: aus Marge × Umsatz
        ebit = None
        ebit_m = safe_float(
            ir_analysis.get("recurring_ebit_margin_pct") or
            ir_analysis.get("ebit_margin_pct")
        )
        if revenue and ebit_m:
            ebit = round(revenue * ebit_m / 100, 3)

        # Net Debt: positiv = Verschuldung
        net_debt = safe_float(ir_analysis.get("net_debt_bn"))

        # Schulden und Cash aus Net Debt ableiten
        total_debt = safe_float(ir_analysis.get("total_debt_bn"))
        total_cash = safe_float(ir_analysis.get("cash_bn"))
        if net_debt is not None and not total_debt and not total_cash:
            total_debt = net_debt if net_debt > 0 else 0
            total_cash = abs(net_debt) if net_debt < 0 else 0

        # FCF
        fcf = safe_float(ir_analysis.get("free_cashflow_bn"))

        # Net Income aus EPS × Aktienanzahl
        eps    = safe_float(ir_analysis.get("adjusted_eps"))
        dps    = safe_float(ir_analysis.get("dps"))
        shares = price_data.get("shares")
        ni     = None
        if eps and shares:
            ni = round(eps * shares, 3)

        # Eigenkapital und Gesamtvermögen
        equity = safe_float(ir_analysis.get("total_equity_bn"))
        assets = safe_float(ir_analysis.get("total_assets_bn"))

        # ROIC-Inputs
        tax_rate = safe_float(ir_analysis.get("tax_rate_pct"))
        nopat    = None
        ic       = safe_float(ir_analysis.get("invested_capital_bn"))
        if ebit and tax_rate:
            nopat = round(ebit * (1 - tax_rate / 100), 3)

        # Vorjahreswerte
        revenue_prev = safe_float(ir_analysis.get("revenue_bn_prev"))
        eps_prev     = safe_float(ir_analysis.get("adjusted_eps_prev"))

        return cls(
            current_price      = price_data["current_price"],
            market_cap         = price_data["market_cap"],
            shares_outstanding = shares,
            currency           = price_data["currency"],
            price_source       = f"yfinance ({ticker})",
            revenue            = revenue,
            ebitda             = ebitda,
            ebit               = ebit,
            gross_profit       = safe_float(ir_analysis.get("gross_profit_bn")),
            net_income         = ni,
            fcf                = fcf,
            total_debt         = total_debt,
            total_cash         = total_cash,
            total_equity       = equity,
            total_assets       = assets,
            interest_expense   = safe_float(ir_analysis.get("interest_expense_bn")),
            eps                = eps,
            dps                = dps,
            invested_capital   = ic,
            nopat              = nopat,
            revenue_prev       = revenue_prev,
            eps_prev           = eps_prev,
            financial_source   = financial_source,
        )

    # ── Kern-Berechnung ───────────────────────────────────

    def _calc(
        self,
        name:            str,
        numerator:       float | None,
        denominator:     float | None,
        num_label:       str,
        den_label:       str,
        suffix:          str  = "x",
        pct:             bool = False,
        source:          str  = "",
        allow_neg_denom: bool = False,
    ) -> MultipleResult:

        inputs = {num_label: numerator, den_label: denominator}
        src    = source or f"{self.price_src} + {self.fin_src}"

        if numerator is None:
            return MultipleResult(
                value=None,
                formula=f"{name}: {num_label} nicht verfügbar",
                inputs=inputs, source=src, valid=False,
            )
        if denominator is None:
            return MultipleResult(
                value=None,
                formula=f"{name}: {den_label} nicht verfügbar",
                inputs=inputs, source=src, valid=False,
            )
        if denominator == 0:
            return MultipleResult(
                value=None,
                formula=f"{name}: {den_label} = 0 → Division nicht möglich",
                inputs=inputs, source=src, valid=False,
            )
        if not allow_neg_denom and denominator < 0:
            return MultipleResult(
                value=None,
                formula=(
                    f"{name}: {den_label} = {denominator:.2f} (negativ) "
                    f"→ Multiple nicht aussagekräftig"
                ),
                inputs=inputs, source=src, valid=False,
            )

        result  = numerator / denominator
        if pct:
            result = result * 100

        val_fmt = f"{result:.1f}{suffix}"
        formula = (
            f"{name} = {num_label} {numerator:.3f} "
            f"/ {den_label} {denominator:.3f} "
            f"= {val_fmt}"
        )

        return MultipleResult(
            value=round(result, 2),
            formula=formula,
            inputs=inputs,
            source=src,
            valid=True,
        )

    # ── EV-basierte Multiples ─────────────────────────────

    def ev_ebitda(self) -> MultipleResult:
        return self._calc(
            "EV/EBITDA", self._ev, self.ebitda,
            f"EV ({self.currency} Mrd.)", "EBITDA (Mrd.)",
        )

    def ev_ebit(self) -> MultipleResult:
        return self._calc(
            "EV/EBIT", self._ev, self.ebit,
            f"EV ({self.currency} Mrd.)", "EBIT (Mrd.)",
        )

    def ev_sales(self) -> MultipleResult:
        return self._calc(
            "EV/Sales", self._ev, self.revenue,
            f"EV ({self.currency} Mrd.)", "Umsatz (Mrd.)",
        )

    def ev_fcf(self) -> MultipleResult:
        return self._calc(
            "EV/FCF", self._ev, self.fcf,
            f"EV ({self.currency} Mrd.)", "FCF (Mrd.)",
        )

    def ev_gross_profit(self) -> MultipleResult:
        return self._calc(
            "EV/Bruttogewinn", self._ev, self.gp,
            f"EV ({self.currency} Mrd.)", "Bruttogewinn (Mrd.)",
        )

    # ── Kurs-basierte Multiples ───────────────────────────

    def pe_ratio(self) -> MultipleResult:
        return self._calc(
            "P/E", self.price, self.eps,
            f"Kurs ({self.currency})", "EPS",
            source=f"{self.price_src} + {self.fin_src}",
        )

    def pb_ratio(self) -> MultipleResult:
        bvps = None
        if self.equity and self.shares and self.shares > 0:
            bvps = round(self.equity / self.shares, 3)
        return self._calc(
            "P/B", self.price, bvps,
            f"Kurs ({self.currency})",
            f"Buchwert/Aktie ({self.fin_src})",
        )

    def ps_ratio(self) -> MultipleResult:
        sps = None
        if self.revenue and self.shares and self.shares > 0:
            sps = round(self.revenue / self.shares, 3)
        return self._calc(
            "P/S", self.price, sps,
            f"Kurs ({self.currency})", "Umsatz/Aktie",
        )

    def p_fcf(self) -> MultipleResult:
        fcf_ps = None
        if self.fcf and self.shares and self.shares > 0:
            fcf_ps = round(self.fcf / self.shares, 3)
        return self._calc(
            "P/FCF", self.price, fcf_ps,
            f"Kurs ({self.currency})", "FCF/Aktie",
        )

    def dividend_yield(self) -> MultipleResult:
        return self._calc(
            "Dividendenrendite", self.dps, self.price,
            "DPS", f"Kurs ({self.currency})",
            suffix="%", pct=True,
        )

    def fcf_yield(self) -> MultipleResult:
        fcf_ps = None
        if self.fcf and self.shares and self.shares > 0:
            fcf_ps = round(self.fcf / self.shares, 3)
        return self._calc(
            "FCF-Yield", fcf_ps, self.price,
            "FCF/Aktie", f"Kurs ({self.currency})",
            suffix="%", pct=True,
        )

    # ── Verschuldungs-Kennzahlen ──────────────────────────

    def nd_ebitda(self) -> MultipleResult:
        nd = None
        if self.debt is not None and self.cash is not None:
            nd = round(self.debt - self.cash, 3)
        elif self.debt is not None:
            nd = self.debt
        return self._calc(
            "ND/EBITDA", nd, self.ebitda,
            "Nettoverschuldung (Mrd.)", "EBITDA (Mrd.)",
            source=self.fin_src,
            allow_neg_denom=False,
        )

    def interest_coverage(self) -> MultipleResult:
        return self._calc(
            "Zinsdeckung (EBIT/Zinsen)", self.ebit, self.interest,
            "EBIT (Mrd.)", "Zinsaufwand (Mrd.)",
            source=self.fin_src,
        )

    def debt_equity(self) -> MultipleResult:
        return self._calc(
            "Debt/Equity", self.debt, self.equity,
            "Gesamtschulden (Mrd.)", "Eigenkapital (Mrd.)",
            source=self.fin_src,
        )

    # ── Margen ────────────────────────────────────────────

    def ebitda_margin(self) -> MultipleResult:
        return self._calc(
            "EBITDA-Marge", self.ebitda, self.revenue,
            "EBITDA (Mrd.)", "Umsatz (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def ebit_margin(self) -> MultipleResult:
        return self._calc(
            "EBIT-Marge", self.ebit, self.revenue,
            "EBIT (Mrd.)", "Umsatz (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def gross_margin(self) -> MultipleResult:
        return self._calc(
            "Bruttomarge", self.gp, self.revenue,
            "Bruttogewinn (Mrd.)", "Umsatz (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def net_margin(self) -> MultipleResult:
        return self._calc(
            "Nettomarge", self.ni, self.revenue,
            "Nettogewinn (Mrd.)", "Umsatz (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def fcf_margin(self) -> MultipleResult:
        return self._calc(
            "FCF-Marge", self.fcf, self.revenue,
            "FCF (Mrd.)", "Umsatz (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def fcf_conversion(self) -> MultipleResult:
        return self._calc(
            "FCF-Conversion", self.fcf, self.ni,
            "FCF (Mrd.)", "Nettogewinn (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    # ── Renditen ──────────────────────────────────────────

    def roe(self) -> MultipleResult:
        return self._calc(
            "ROE", self.ni, self.equity,
            "Nettogewinn (Mrd.)", "Eigenkapital (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def roa(self) -> MultipleResult:
        return self._calc(
            "ROA", self.ni, self.assets,
            "Nettogewinn (Mrd.)", "Gesamtvermögen (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    def roic(self) -> MultipleResult:
        return self._calc(
            "ROIC", self.nopat_val, self.ic,
            "NOPAT (Mrd.)", "Invested Capital (Mrd.)",
            suffix="%", pct=True, source=self.fin_src,
        )

    # ── Wachstum ──────────────────────────────────────────

    def revenue_growth(self) -> MultipleResult:
        if self.revenue is None or self.rev_prev is None:
            return MultipleResult(
                value=None,
                formula="Umsatz-Wachstum: Vorjahreswert fehlt",
                inputs={"Umsatz": self.revenue, "Umsatz Vorjahr": self.rev_prev},
                source=self.fin_src, valid=False,
            )
        if self.rev_prev == 0:
            return MultipleResult(
                value=None,
                formula="Umsatz-Wachstum: Vorjahr-Umsatz = 0",
                inputs={}, source=self.fin_src, valid=False,
            )
        growth = (self.revenue - self.rev_prev) / self.rev_prev * 100
        return MultipleResult(
            value=round(growth, 1),
            formula=(
                f"Umsatz-Wachstum = "
                f"({self.revenue:.3f} - {self.rev_prev:.3f}) "
                f"/ {self.rev_prev:.3f} × 100 "
                f"= {growth:.1f}%"
            ),
            inputs={"Umsatz": self.revenue, "Umsatz Vorjahr": self.rev_prev},
            source=self.fin_src, valid=True,
        )

    def eps_growth(self) -> MultipleResult:
        if self.eps is None or self.eps_prev is None:
            return MultipleResult(
                value=None,
                formula="EPS-Wachstum: Vorjahreswert fehlt",
                inputs={"EPS": self.eps, "EPS Vorjahr": self.eps_prev},
                source=self.fin_src, valid=False,
            )
        if self.eps_prev == 0:
            return MultipleResult(
                value=None,
                formula="EPS-Wachstum: Vorjahr-EPS = 0",
                inputs={}, source=self.fin_src, valid=False,
            )
        growth = (self.eps - self.eps_prev) / self.eps_prev * 100
        return MultipleResult(
            value=round(growth, 1),
            formula=(
                f"EPS-Wachstum = "
                f"({self.eps:.2f} - {self.eps_prev:.2f}) "
                f"/ {self.eps_prev:.2f} × 100 "
                f"= {growth:.1f}%"
            ),
            inputs={"EPS": self.eps, "EPS Vorjahr": self.eps_prev},
            source=self.fin_src, valid=True,
        )

    # ── Alles berechnen ───────────────────────────────────

    def compute_all(self) -> dict:
        """
        Berechnet alle Kennzahlen deterministisch.

        Returns dict mit:
          {
            "ev_ebitda": {
              "value":   9.7,
              "formula": "EV/EBITDA = EV 64.30 / EBITDA 6.63 = 9.7x",
              "source":  "yfinance (HOLN.SW) + IR-Dokument",
              "valid":   True,
            },
            ...
          }
        """
        methods = [
            ("ev_ebitda",         self.ev_ebitda),
            ("ev_ebit",           self.ev_ebit),
            ("ev_sales",          self.ev_sales),
            ("ev_fcf",            self.ev_fcf),
            ("ev_gross_profit",   self.ev_gross_profit),
            ("pe_ratio",          self.pe_ratio),
            ("pb_ratio",          self.pb_ratio),
            ("ps_ratio",          self.ps_ratio),
            ("p_fcf",             self.p_fcf),
            ("dividend_yield",    self.dividend_yield),
            ("fcf_yield",         self.fcf_yield),
            ("nd_ebitda",         self.nd_ebitda),
            ("interest_coverage", self.interest_coverage),
            ("debt_equity",       self.debt_equity),
            ("ebitda_margin",     self.ebitda_margin),
            ("ebit_margin",       self.ebit_margin),
            ("gross_margin",      self.gross_margin),
            ("net_margin",        self.net_margin),
            ("fcf_margin",        self.fcf_margin),
            ("fcf_conversion",    self.fcf_conversion),
            ("roe",               self.roe),
            ("roa",               self.roa),
            ("roic",              self.roic),
            ("revenue_growth",    self.revenue_growth),
            ("eps_growth",        self.eps_growth),
        ]

        results = {}
        for key, method in methods:
            try:
                r = method()
                results[key] = {
                    "value":   r.value,
                    "formula": r.formula,
                    "source":  r.source,
                    "valid":   r.valid,
                }
            except Exception as e:
                results[key] = {
                    "value":   None,
                    "formula": f"{key}: Fehler — {str(e)}",
                    "source":  "n/v",
                    "valid":   False,
                }

        results["_enterprise_value"] = {
            "value":   self._ev,
            "formula": self._ev_formula,
            "source":  f"{self.price_src} + {self.fin_src}",
            "valid":   self._ev is not None,
        }

        results["_price_data"] = {
            "current_price": self.price,
            "market_cap_bn": self.mktcap,
            "currency":      self.currency,
            "shares_bn":     self.shares,
            "source":        self.price_src,
        }

        valid_count = sum(
            1 for v in results.values()
            if isinstance(v, dict) and v.get("valid", False)
        )
        results["_summary"] = {
            "total_calculated": len(methods),
            "valid":            valid_count,
            "missing":          len(methods) - valid_count,
        }

        return results
