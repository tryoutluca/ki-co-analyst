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
    def from_ticker(cls, ticker: str, ir_analysis: dict, financial_source: str = "IR-Dokument") -> "MultiplesEngine":
        stock = yf.Ticker(ticker)
        yf_info = stock.info
        
        def safe_f(val, scale=1.0):
            try:
                if val in (None, "n/v", "not found", ""): return None
                return float(val) * scale
            except: return None

        # 1. Basis-Daten (yfinance)
        price = yf_info.get("currentPrice") or yf_info.get("regularMarketPrice")
        mktcap = safe_f(yf_info.get("marketCap"), 1e-9) # In Mrd.
        shares = safe_f(yf_info.get("sharesOutstanding"), 1e-9) # In Mrd.

        # 2. Finanzdaten-Extraktion mit Fallback-Logik (IR -> yfinance)
        # Revenue
        rev = safe_f(ir_analysis.get("revenue_bn"))
        if rev is None: rev = safe_f(yf_info.get("totalRevenue"), 1e-9)

        # EBITDA (Absoluter Wert hat Vorrang vor Marge)
        ebitda = safe_f(ir_analysis.get("ebitda_bn"))
        if ebitda is None:
            ebitda_m = safe_f(ir_analysis.get("ebitda_margin_pct"))
            if rev and ebitda_m: ebitda = rev * (ebitda_m / 100)
        if ebitda is None: ebitda = safe_f(yf_info.get("ebitda"), 1e-9)

        # EBIT
        ebit = safe_f(ir_analysis.get("ebit_bn"))
        if ebit is None:
            ebit_m = safe_f(ir_analysis.get("recurring_ebit_margin_pct") or ir_analysis.get("ebit_margin_pct"))
            if rev and ebit_m: ebit = rev * (ebit_m / 100)
        if ebit is None: ebit = safe_f(yf_info.get("operatingCashflow"), 1e-9) # Sehr grober Fallback

        # Net Income / EPS
        eps = safe_f(ir_analysis.get("adjusted_eps"))
        if eps is None: eps = safe_f(yf_info.get("trailingEps"))
        
        ni = safe_f(ir_analysis.get("net_income_bn"))
        if ni is None and eps and shares: ni = eps * shares
        if ni is None: ni = safe_f(yf_info.get("netIncomeToCommon"), 1e-9)

        # Cash & Debt
        # Wichtig: Wenn IR nur 'Net Debt' liefert, setzen wir Debt=NetDebt und Cash=0 für den EV
        net_debt = safe_f(ir_analysis.get("net_debt_bn"))
        debt = safe_f(yf_info.get("totalDebt"), 1e-9)
        cash = safe_f(yf_info.get("totalCash"), 1e-9)
        
        if net_debt is not None:
            debt = net_debt if net_debt > 0 else 0
            cash = abs(net_debt) if net_debt < 0 else 0

        # FCF
        fcf = safe_f(ir_analysis.get("free_cashflow_bn"))
        if fcf is None: fcf = safe_f(yf_info.get("freeCashflow"), 1e-9)

        # Buchwert / Equity
        equity = safe_f(ir_analysis.get("total_equity_bn"))
        if equity is None: equity = safe_f(yf_info.get("totalStockholderEquity"), 1e-9)
        
        assets = safe_f(ir_analysis.get("total_assets_bn"))
        if assets is None: assets = safe_f(yf_info.get("totalAssets"), 1e-9)

        return cls(
            current_price=price,
            market_cap=mktcap,
            shares_outstanding=shares,
            currency=yf_info.get("currency", "CHF"),
            revenue=rev,
            ebitda=ebitda,
            ebit=ebit,
            net_income=ni,
            fcf=fcf,
            total_debt=debt,
            total_cash=cash,
            total_equity=equity,
            total_assets=assets,
            eps=eps,
            dps=safe_f(ir_analysis.get("dividend_per_share") or yf_info.get("dividendRate")),
            financial_source=financial_source
        )