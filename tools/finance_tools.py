import concurrent.futures
import finnhub
import yfinance as yf
import os
import json
import requests
import statistics
from datetime import datetime, timedelta
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.tools.tavily_search import TavilySearchResults

# ── Helpers ──────────────────────────────────────────────────────────────────
def _parse_date(value) -> str:
    """Konvertiert Timestamp (int/float), pandas Timestamp oder ISO-String zu YYYY-MM-DD."""
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        try:
            return str(datetime.fromtimestamp(value).date())
        except Exception:
            return "N/A"
    if isinstance(value, str):
        return value[:10]
    # pandas Timestamp oder datetime-Objekte
    try:
        return str(value.date())
    except AttributeError:
        return str(value)[:10]


# ── P/E Validation ───────────────────────────────────────────────────────────
def validate_pe_ratio(pe_ratio, forward_pe, ticker: str) -> dict:
    """Flags distorted trailing P/E and recommends primary multiple."""
    result = {
        "status": "plausibel",
        "primary_multiple": "pe_ratio",
        "warning": None,
        "implied_earnings_growth": None,
    }
    try:
        pe = float(pe_ratio) if pe_ratio not in (None, "N/A") else None
        fpe = float(forward_pe) if forward_pe not in (None, "N/A") else None
    except (TypeError, ValueError):
        return result

    if pe is None:
        return result

    if pe > 50 or pe < 0:
        result["status"] = "verzerrt"
        result["primary_multiple"] = "forward_pe"
        result["warning"] = (
            "KGV durch Einmaleffekt verzerrt (z.B. Spin-off, Abschreibung) "
            "— Forward P/E und EV/EBITDA als primäre Multiples"
        )
        if fpe and fpe > 0:
            result["implied_earnings_growth"] = round((pe / fpe - 1) * 100, 1)

    return result


# ── Finnhub Client ───────────────────────────────────────────────────────────
def get_finnhub_client():
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise ValueError("FINNHUB_API_KEY nicht in .env gefunden")
    return finnhub.Client(api_key=api_key)


def search_ticker(query: str) -> list[dict]:
    """Sucht Aktien nach Firmenname. Kombiniert Finnhub und yfinance, max. 6 Ergebnisse."""

    def _fetch_finnhub() -> list[dict]:
        try:
            client = get_finnhub_client()
            raw = client.symbol_search(query)
            items = raw.get("result", []) if isinstance(raw, dict) else (raw or [])
            return [
                {"ticker": r["displaySymbol"], "name": r.get("description", r["displaySymbol"])}
                for r in items
                if r.get("type") in ("Common Stock", "EQS")
            ][:5]
        except Exception:
            return []

    def _fetch_yfinance() -> list[dict]:
        try:
            res = yf.Search(query, max_results=5)
            quotes = res.quotes or []
            return [
                {"ticker": q["symbol"], "name": q.get("shortname") or q.get("longname") or q["symbol"]}
                for q in quotes
                if q.get("quoteType") == "EQUITY"
            ][:5]
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_future = executor.submit(_fetch_finnhub)
        y_future = executor.submit(_fetch_yfinance)
        try:
            finnhub_results = f_future.result(timeout=5)
        except Exception:
            finnhub_results = []
        try:
            yfinance_results = y_future.result(timeout=5)
        except Exception:
            yfinance_results = []

    # Deduplizieren: Überschneidungen beider Quellen werden priorisiert (stable sort)
    both_tickers = {r["ticker"] for r in finnhub_results} & {r["ticker"] for r in yfinance_results}
    seen: set[str] = set()
    merged: list[dict] = []
    for r in (*finnhub_results, *yfinance_results):
        if r["ticker"] not in seen:
            merged.append(r)
            seen.add(r["ticker"])
    merged.sort(key=lambda r: r["ticker"] not in both_tickers)

    output: list[dict] = []
    for item in merged[:6]:
        sym = item["ticker"]
        try:
            fi = yf.Ticker(sym).fast_info
            exchange = getattr(fi, "exchange", None) or "N/A"
            currency = getattr(fi, "currency", None) or "N/A"
            last_price = getattr(fi, "last_price", None)
            price_str = f"{last_price:.2f}" if last_price is not None else "N/A"
            output.append({
                "ticker": sym,
                "name": item["name"],
                "exchange": exchange,
                "currency": currency,
                "last_price": last_price,
                "display": f"{item['name']} ({sym}) — {exchange} — {currency} {price_str}",
            })
        except Exception:
            output.append({
                "ticker": sym,
                "name": item["name"],
                "exchange": "N/A",
                "currency": "N/A",
                "last_price": None,
                "display": f"{item['name']} ({sym})",
            })

    return output


@tool
def get_stock_info(ticker: str) -> dict:
    """Holt allgemeine Unternehmensinformationen und aktuelle Kennzahlen.
    Kurs/Marktkapitalisierung/Aktien: primär Finnhub.
    Alle anderen Felder (Sektor, Multiples, etc.): yfinance."""
    NA_FINAL = "-"

    # ── Schritt 1: Finnhub für die drei Live-Werte ────────────────────────────
    fh_price:      float | None = None
    fh_prev_close: float | None = None
    fh_market_cap: float | None = None
    fh_shares:     float | None = None
    try:
        client  = get_finnhub_client()
        quote   = client.quote(ticker) or {}
        profile = client.company_profile2(symbol=ticker) or {}

        fh_price      = quote.get("c")  or None
        fh_prev_close = quote.get("pc") or None
        mc = profile.get("marketCapitalization")
        if mc:
            fh_market_cap = float(mc) * 1_000_000   # Mio. USD → absolute
        sh = profile.get("shareOutstanding")
        if sh:
            fh_shares = float(sh) * 1_000_000       # Mio. → absolute
    except Exception:
        pass

    # ── Schritt 2: yfinance für alle anderen Felder (+ Fallback Live-Werte) ───
    yf_info: dict = {}
    try:
        yf_info = yf.Ticker(ticker).info or {}
    except Exception:
        pass

    # ── Schritt 3: Live-Werte mergen (Finnhub > yfinance > NA_FINAL) ──────────
    yf_price = yf_info.get("currentPrice") or yf_info.get("regularMarketPrice")

    current_price      = fh_price      if fh_price      is not None else (yf_price or NA_FINAL)
    prev_close         = fh_prev_close if fh_prev_close is not None else (yf_info.get("regularMarketPreviousClose") or NA_FINAL)
    market_cap         = fh_market_cap if fh_market_cap is not None else (yf_info.get("marketCap")          or NA_FINAL)
    shares_outstanding = fh_shares     if fh_shares     is not None else (yf_info.get("sharesOutstanding")  or NA_FINAL)

    data_source = (
        "finnhub"  if fh_price is not None else
        "yfinance" if yf_price is not None else
        "mixed"
    )

    pe_ratio   = yf_info.get("trailingPE",  "N/A")
    forward_pe = yf_info.get("forwardPE",   "N/A")
    pe_val     = validate_pe_ratio(pe_ratio, forward_pe, ticker)

    result = {
        "ticker":               ticker,
        "name":                 yf_info.get("longName",                          ticker),
        "sector":               yf_info.get("sector",                            "N/A"),
        "industry":             yf_info.get("industry",                          "N/A"),
        "country":              yf_info.get("country",                           "N/A"),
        "currency":             yf_info.get("currency",                          "N/A"),
        "current_price":        current_price,
        "prev_close":           prev_close,
        "market_cap":           market_cap,
        "shares_outstanding":   shares_outstanding,
        "enterprise_value":     yf_info.get("enterpriseValue",                   "N/A"),
        "pe_ratio":             pe_ratio,
        "forward_pe":           forward_pe,
        "price_to_book":        yf_info.get("priceToBook",                       "N/A"),
        "price_to_sales":       yf_info.get("priceToSalesTrailing12Months",      "N/A"),
        "ev_to_ebitda":         yf_info.get("enterpriseToEbitda",                "N/A"),
        "ev_to_revenue":        yf_info.get("enterpriseToRevenue",               "N/A"),
        "dividend_yield":       yf_info.get("dividendYield",                     "N/A"),
        "beta":                 yf_info.get("beta",                              "N/A"),
        "52_week_high":         yf_info.get("fiftyTwoWeekHigh",                  "N/A"),
        "52_week_low":          yf_info.get("fiftyTwoWeekLow",                   "N/A"),
        "analyst_target_price": yf_info.get("targetMeanPrice",                   "N/A"),
        "recommendation":       yf_info.get("recommendationKey",                 "N/A"),
        "description":          yf_info.get("longBusinessSummary",               "N/A"),
        "pe_validation":        pe_val,
        "data_source":          data_source,
    }

    if pe_val["status"] == "verzerrt":
        result["pe_warning"] = "⚠ KGV nicht aussagekräftig — Forward P/E bevorzugen"
    return result


@tool
def get_financial_statements(ticker: str) -> dict:
    """Holt Bilanz, GuV und Cashflow der letzten Jahre via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Kennzahlen aus info
        metrics = {
            "revenue_ttm": info.get("totalRevenue", "N/A"),
            "gross_profit_ttm": info.get("grossProfits", "N/A"),
            "ebitda_ttm": info.get("ebitda", "N/A"),
            "net_income_ttm": info.get("netIncomeToCommon", "N/A"),
            "free_cashflow_ttm": info.get("freeCashflow", "N/A"),
            "operating_cashflow_ttm": info.get("operatingCashflow", "N/A"),
            "total_debt": info.get("totalDebt", "N/A"),
            "total_cash": info.get("totalCash", "N/A"),
            "gross_margin": info.get("grossMargins", "N/A"),
            "operating_margin": info.get("operatingMargins", "N/A"),
            "profit_margin": info.get("profitMargins", "N/A"),
            "roe": info.get("returnOnEquity", "N/A"),
            "roa": info.get("returnOnAssets", "N/A"),
            "revenue_growth": info.get("revenueGrowth", "N/A"),
            "earnings_growth": info.get("earningsGrowth", "N/A"),
            "debt_to_equity": info.get("debtToEquity", "N/A"),
            "current_ratio": info.get("currentRatio", "N/A"),
            "book_value_per_share": info.get("bookValue", "N/A"),
            "eps_trailing": info.get("trailingEps", "N/A"),
            "eps_forward": info.get("forwardEps", "N/A"),
        }

        # Historische Einkommensdaten (letzte 4 Quartale)
        try:
            income_stmt = stock.quarterly_income_stmt
            if not income_stmt.empty:
                latest = income_stmt.iloc[:, 0]
                metrics["latest_quarter_revenue"] = float(latest.get("Total Revenue", "N/A")) if "Total Revenue" in latest.index else "N/A"
                metrics["latest_quarter_net_income"] = float(latest.get("Net Income", "N/A")) if "Net Income" in latest.index else "N/A"
        except Exception:
            pass

        return metrics
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@tool
def get_price_history(ticker: str) -> dict:
    """Holt Kursentwicklung der letzten 3 Monate via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        end = datetime.now()
        start = end - timedelta(days=90)
        hist = stock.history(start=start, end=end, auto_adjust=False)

        if hist.empty:
            return {"error": "Keine Kursdaten verfügbar", "ticker": ticker}

        prices = hist["Close"].dropna()
        first_price = float(prices.iloc[0])
        last_price = float(prices.iloc[-1])
        performance_pct = ((last_price - first_price) / first_price) * 100

        return {
            "ticker": ticker,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "start_price": round(first_price, 2),
            "current_price": round(last_price, 2),
            "performance_3m_pct": round(performance_pct, 2),
            "high_3m": round(float(hist["High"].max()), 2),
            "low_3m": round(float(hist["Low"].min()), 2),
            "avg_volume_3m": int(hist["Volume"].mean()),
            "num_trading_days": len(prices),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@tool
def get_recent_news(ticker: str) -> list:
    """Holt aktuelle News-Artikel via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        result = []
        for item in news[:10]:
            result.append({
                "title": item.get("title", "N/A"),
                "summary": item.get("summary", ""),
                "published": datetime.fromtimestamp(item.get("providerPublishTime", 0)).strftime("%Y-%m-%d %H:%M") if item.get("providerPublishTime") else "N/A",
                "source": item.get("publisher", "N/A"),
                "url": item.get("link", "nicht verfügbar"),
            })
        return result
    except Exception as e:
        return [{"error": str(e), "ticker": ticker}]



@tool
def get_historical_multiples(ticker: str) -> dict:
    """Historische Bewertungskennzahlen der letzten 5 Jahre.
    Primär: Finnhub annual series.
    Fallback: deterministisch aus yfinance DataFrames + Jahresend-Kursen."""
    import pandas as pd

    # ── Schritt 1: Finnhub (primär) ───────────────────────────────────────────
    finnhub_result: dict = {}
    try:
        client  = get_finnhub_client()
        metrics = client.company_basic_financials(ticker, "all")
        series  = metrics.get("series", {}).get("annual", {})

        def extract_series(key):
            data = series.get(key, [])
            sorted_data = sorted(data, key=lambda d: d.get("period", ""), reverse=True)
            return [{"period": d.get("period"), "value": d.get("v")} for d in sorted_data[:5]]

        finnhub_result = {
            "ticker":         ticker,
            "source":         "finnhub",
            "pe_ratio":       extract_series("pe"),
            "pb_ratio":       extract_series("pb"),
            "ps_ratio":       extract_series("ps"),
            "ev_to_ebitda":   extract_series("currentEv/freeCashflowTTM"),
            "roe":            extract_series("roeTTM"),
            "roa":            extract_series("roaTTM"),
            "net_margin":     extract_series("netProfitMarginTTM"),
            "revenue_growth": extract_series("revenueGrowthTTMYoy"),
        }

        # Nur zurückgeben wenn mindestens eine Series Daten hat
        has_data = any(
            len(finnhub_result.get(k, [])) > 0
            for k in ("pe_ratio", "pb_ratio", "ev_to_ebitda")
        )
        if has_data:
            return finnhub_result
    except Exception:
        pass

    # ── Schritt 2: yfinance Fallback ──────────────────────────────────────────
    print(f"        Finnhub leer — berechne historische Multiples via yfinance für {ticker}...")

    empty_result = {
        "ticker": ticker, "source": "yfinance",
        "pe_ratio": [], "pb_ratio": [], "ps_ratio": [],
        "ev_to_ebitda": [], "ev_to_sales": [], "ev_to_fcf": [],
        "roe": [], "roa": [], "net_margin": [], "revenue_growth": [],
        "nd_ebitda": [],
    }

    try:
        stock = yf.Ticker(ticker)
        info  = stock.info or {}

        def safe_df(attr: str) -> pd.DataFrame:
            try:
                df = getattr(stock, attr)
                return df if (df is not None and not df.empty) else pd.DataFrame()
            except Exception:
                return pd.DataFrame()

        inc = safe_df("income_stmt")
        bs  = safe_df("balance_sheet")
        cf  = safe_df("cashflow")

        if inc.empty:
            return empty_result

        # Jahresend-Kurse (gesamte verfügbare History)
        price_hist = pd.DataFrame()
        try:
            price_hist = stock.history(period="max", auto_adjust=True)
        except Exception:
            pass

        def col_for_year(df: pd.DataFrame, year: str):
            for c in df.columns:
                try:
                    yr = c.year if hasattr(c, "year") else int(str(c)[:4])
                    if str(yr) == year:
                        return c
                except Exception:
                    pass
            return None

        def get_v(df: pd.DataFrame, col, *fields):
            if df.empty or col is None:
                return None
            for f in fields:
                if f in df.index:
                    try:
                        val = df.loc[f, col]
                        if val is not None and not (isinstance(val, float) and str(val) == "nan"):
                            return float(val)
                    except Exception:
                        pass
            return None

        def to_bn(v):
            if v is None:
                return None
            try:
                v = float(v)
                if abs(v) > 1_000_000:
                    return v / 1e9
                if abs(v) > 100:
                    return v / 1e3
                return v
            except Exception:
                return None

        # Alle Jahre aus income_stmt ermitteln
        years = []
        for c in inc.columns:
            try:
                yr = c.year if hasattr(c, "year") else int(str(c)[:4])
                if 2015 <= yr <= 2030:
                    years.append(str(yr))
            except Exception:
                pass
        years = sorted(set(years), reverse=True)[:5]

        pe_series, pb_series, ps_series    = [], [], []
        ev_ebitda_series, ev_sales_series  = [], []
        ev_fcf_series                      = []
        roe_series, roa_series             = [], []
        net_margin_series, rev_growth_s    = [], []
        nd_ebitda_series                   = []
        prev_revenue = None

        for year in sorted(years):
            inc_col = col_for_year(inc, year)
            bs_col  = col_for_year(bs,  year)
            cf_col  = col_for_year(cf,  year)

            # ── Jahresend-Kurs ────────────────────────────────────────────────
            year_end_price = None
            if not price_hist.empty:
                try:
                    yr_prices = price_hist[price_hist.index.year == int(year)]
                    if not yr_prices.empty:
                        year_end_price = float(yr_prices["Close"].iloc[-1])
                except Exception:
                    pass

            # Fallback: aktueller Kurs nur für letztes Jahr
            if year_end_price is None and year == years[-1]:
                year_end_price = (
                    info.get("currentPrice") or info.get("regularMarketPrice")
                )

            # ── Finanzdaten ───────────────────────────────────────────────────
            revenue    = to_bn(get_v(inc, inc_col, "Total Revenue", "Revenue"))
            net_income = to_bn(get_v(inc, inc_col, "Net Income",
                                     "Net Income Common Stockholders"))
            ebit       = to_bn(get_v(inc, inc_col, "EBIT", "Operating Income",
                                     "Operating Income Loss"))
            da         = to_bn(get_v(cf, cf_col,
                                     "Depreciation And Amortization",
                                     "Depreciation Amortization Depletion"))
            if da is None:
                da = to_bn(get_v(inc, inc_col, "Reconciled Depreciation"))
            op_cf  = to_bn(get_v(cf, cf_col, "Operating Cash Flow",
                                  "Cash Flow From Continuing Operating Activities"))
            capex_raw = to_bn(get_v(cf, cf_col, "Capital Expenditure",
                                    "Purchase Of PPE", "Capital Expenditures"))
            capex  = -abs(capex_raw) if capex_raw else None
            fcf    = to_bn(get_v(cf, cf_col, "Free Cash Flow"))
            if fcf is None and op_cf and capex:
                fcf = op_cf + capex

            equity = to_bn(get_v(bs, bs_col, "Common Stock Equity",
                                  "Stockholders Equity",
                                  "Total Equity Gross Minority Interest"))
            assets = to_bn(get_v(bs, bs_col, "Total Assets"))
            debt   = to_bn(get_v(bs, bs_col, "Total Debt",
                                  "Long Term Debt And Capital Lease Obligation"))
            cash   = to_bn(get_v(bs, bs_col, "Cash And Cash Equivalents",
                                  "Cash Cash Equivalents And Short Term Investments"))
            shares = to_bn(get_v(inc, inc_col, "Diluted Average Shares",
                                  "Basic Average Shares"))

            ebitda  = (ebit + abs(da) if (ebit and da) else None)
            net_debt = (debt - cash if (debt is not None and cash is not None) else None)

            # ── Multiples berechnen ───────────────────────────────────────────
            if year_end_price and shares and shares > 0:
                mktcap = year_end_price * shares  # in Mrd. (shares already in Mrd.)
                ev     = mktcap + (net_debt or 0)

                if net_income and net_income > 0:
                    pe_series.append({"period": year, "value": round(mktcap / net_income, 2)})
                if equity and equity > 0:
                    pb_series.append({"period": year, "value": round(mktcap / equity, 2)})
                if revenue and revenue > 0:
                    ps_series.append({"period": year, "value": round(mktcap / revenue, 2)})
                if ebitda and ebitda > 0:
                    ev_ebitda_series.append({"period": year, "value": round(ev / ebitda, 2)})
                if revenue and revenue > 0:
                    ev_sales_series.append({"period": year, "value": round(ev / revenue, 2)})
                if fcf and fcf > 0:
                    ev_fcf_series.append({"period": year, "value": round(ev / fcf, 2)})

            if net_income and equity and equity > 0:
                roe_series.append({"period": year, "value": round(net_income / equity * 100, 1)})
            if net_income and assets and assets > 0:
                roa_series.append({"period": year, "value": round(net_income / assets * 100, 1)})
            if net_income and revenue and revenue > 0:
                net_margin_series.append({"period": year, "value": round(net_income / revenue * 100, 1)})
            if net_debt is not None and ebitda and ebitda > 0:
                nd_ebitda_series.append({"period": year, "value": round(net_debt / ebitda, 2)})
            if prev_revenue and prev_revenue > 0 and revenue:
                rev_growth_s.append({
                    "period": year,
                    "value": round((revenue - prev_revenue) / prev_revenue * 100, 1),
                })
            prev_revenue = revenue

        return {
            "ticker":         ticker,
            "source":         "yfinance",
            "pe_ratio":       list(reversed(pe_series)),
            "pb_ratio":       list(reversed(pb_series)),
            "ps_ratio":       list(reversed(ps_series)),
            "ev_to_ebitda":   list(reversed(ev_ebitda_series)),
            "ev_to_sales":    list(reversed(ev_sales_series)),
            "ev_to_fcf":      list(reversed(ev_fcf_series)),
            "roe":            list(reversed(roe_series)),
            "roa":            list(reversed(roa_series)),
            "net_margin":     list(reversed(net_margin_series)),
            "revenue_growth": list(reversed(rev_growth_s)),
            "nd_ebitda":      list(reversed(nd_ebitda_series)),
        }

    except Exception as e:
        return {**empty_result, "error": str(e)}


@tool
def get_historical_financials(ticker: str) -> dict:
    """
    Holt historische Jahresdaten via yfinance DataFrames
    und berechnet alle Kennzahlen deterministisch per Loop.

    Datenquellen:
      stock.income_stmt   → Revenue, EBIT, Net Income
      stock.balance_sheet → Debt, Cash, Equity, Assets
      stock.cashflow      → Operating CF, Capex, D&A

    Returns dict pro Jahr:
      { "2022": { revenue_bn, ebitda_bn, eps, net_debt_bn, ... }, ... }
    """
    import pandas as pd

    print(f"      Hole historische Finanzdaten für {ticker}...")

    try:
        stock = yf.Ticker(ticker)

        def safe_df(attr: str) -> pd.DataFrame:
            try:
                df = getattr(stock, attr)
                return df if (df is not None and not df.empty) else pd.DataFrame()
            except Exception as e:
                print(f"        ⚠ {attr}: {e}")
                return pd.DataFrame()

        inc = safe_df("income_stmt")
        bs  = safe_df("balance_sheet")
        cf  = safe_df("cashflow")

        all_years: set = set()
        for df in [inc, bs, cf]:
            if not df.empty:
                for col in df.columns:
                    try:
                        yr = col.year if hasattr(col, "year") else int(str(col)[:4])
                        if 2015 <= yr <= 2030:
                            all_years.add(str(yr))
                    except Exception:
                        pass

        if not all_years:
            print(f"        ⚠ Keine historischen Daten für {ticker}")
            return {}

        print(f"        Verfügbare Jahre: {sorted(all_years)}")

        def get_val(df: pd.DataFrame, year: str, *fields):
            if df.empty:
                return None
            col_match = None
            for c in df.columns:
                try:
                    yr = c.year if hasattr(c, "year") else int(str(c)[:4])
                    if str(yr) == year:
                        col_match = c
                        break
                except Exception:
                    pass
            if col_match is None:
                return None
            for field in fields:
                if field in df.index:
                    try:
                        val = df.loc[field, col_match]
                        if val is not None and not (
                            isinstance(val, float) and str(val) == "nan"
                        ):
                            return float(val)
                    except Exception:
                        continue
            return None

        def to_bn(val) -> float | None:
            if val is None:
                return None
            try:
                v = float(val)
                if abs(v) > 1_000_000:
                    return round(v / 1e9, 4)
                if abs(v) > 100:
                    return round(v / 1e3, 4)
                return round(v, 4)
            except Exception:
                return None

        def safe_div(num, den, pct=False):
            try:
                if num is None or den is None or den == 0:
                    return None
                r = float(num) / float(den)
                return round(r * 100 if pct else r, 4)
            except Exception:
                return None

        result = {}

        for year in sorted(all_years):
            print(f"        Verarbeite {year}...")

            revenue_raw    = get_val(inc, year, "Total Revenue", "Revenue", "Total Revenues")
            gross_profit_raw = get_val(inc, year, "Gross Profit", "Gross Income")
            ebit_raw       = get_val(inc, year, "EBIT", "Operating Income", "Operating Income Loss")
            net_income_raw = get_val(inc, year, "Net Income",
                                     "Net Income Common Stockholders",
                                     "Net Income Continuous Operations")
            ebt_raw        = get_val(inc, year, "Pretax Income", "Income Before Tax")
            tax_prov_raw   = get_val(inc, year, "Tax Provision", "Income Tax Expense")
            interest_raw   = get_val(inc, year, "Interest Expense",
                                     "Interest Expense Non Operating")
            shares_raw     = get_val(inc, year, "Diluted Average Shares", "Basic Average Shares")

            da_raw = get_val(cf, year,
                             "Depreciation And Amortization",
                             "Depreciation Amortization Depletion",
                             "Reconciled Depreciation")
            if da_raw is None:
                da_raw = get_val(inc, year,
                                 "Reconciled Depreciation",
                                 "Depreciation And Amortization In Income Statement")

            op_cf_raw  = get_val(cf, year, "Operating Cash Flow",
                                 "Cash Flow From Continuing Operating Activities")
            capex_raw  = get_val(cf, year, "Capital Expenditure", "Purchase Of PPE",
                                 "Capital Expenditures")
            fcf_raw    = get_val(cf, year, "Free Cash Flow")
            divs_raw   = get_val(cf, year, "Common Stock Dividend Paid",
                                 "Dividends Paid", "Payment Of Dividends")

            debt_raw   = get_val(bs, year, "Total Debt",
                                 "Long Term Debt And Capital Lease Obligation",
                                 "Long Term Debt")
            cash_raw   = get_val(bs, year, "Cash And Cash Equivalents",
                                 "Cash Cash Equivalents And Short Term Investments")
            equity_raw = get_val(bs, year, "Common Stock Equity",
                                 "Stockholders Equity",
                                 "Total Equity Gross Minority Interest")
            assets_raw = get_val(bs, year, "Total Assets")
            ic_raw     = get_val(bs, year, "Invested Capital", "Net PPE")

            revenue      = to_bn(revenue_raw)
            gross_profit = to_bn(gross_profit_raw)
            ebit         = to_bn(ebit_raw)
            net_income   = to_bn(net_income_raw)
            ebt          = to_bn(ebt_raw)
            tax_prov     = to_bn(tax_prov_raw)
            interest     = to_bn(interest_raw)
            shares_bn    = to_bn(shares_raw)
            da           = to_bn(da_raw)
            op_cf        = to_bn(op_cf_raw)
            capex_raw_bn = to_bn(capex_raw)
            capex        = -abs(capex_raw_bn) if capex_raw_bn else None
            fcf_direct   = to_bn(fcf_raw)
            divs         = to_bn(divs_raw)
            total_debt   = to_bn(debt_raw)
            total_cash   = to_bn(cash_raw)
            equity       = to_bn(equity_raw)
            assets       = to_bn(assets_raw)
            ic           = to_bn(ic_raw)

            ebitda = None
            if ebit is not None and da is not None:
                ebitda = round(ebit + abs(da), 4)

            fcf = fcf_direct
            if fcf is None and op_cf is not None and capex is not None:
                fcf = round(op_cf + capex, 4)

            net_debt = None
            if total_debt is not None and total_cash is not None:
                net_debt = round(total_debt - total_cash, 4)

            eps = None
            if net_income is not None and shares_bn and shares_bn > 0:
                eps = round(net_income / shares_bn, 2)

            dps = None
            if divs is not None and shares_bn and shares_bn > 0:
                dps = round(abs(divs) / shares_bn, 2)

            tax_rate = None
            if tax_prov and ebt and ebt != 0:
                tr = abs(tax_prov) / abs(ebt) * 100
                if 0 < tr < 60:
                    tax_rate = round(tr, 1)

            nopat = None
            if ebit is not None and tax_rate:
                nopat = round(ebit * (1 - tax_rate / 100), 4)

            ebitda_margin = safe_div(ebitda, revenue, pct=True)
            ebit_margin   = safe_div(ebit,   revenue, pct=True)
            gross_margin  = safe_div(gross_profit, revenue, pct=True)
            net_margin    = safe_div(net_income, revenue, pct=True)
            fcf_margin    = safe_div(fcf, revenue, pct=True)

            nd_ebitda = None
            if net_debt is not None and ebitda and ebitda > 0:
                nd_ebitda = round(net_debt / ebitda, 2)

            roe = None
            if net_income is not None and equity and equity > 0:
                roe = round(net_income / equity * 100, 1)

            roa = None
            if net_income is not None and assets and assets > 0:
                roa = round(net_income / assets * 100, 1)

            roic = None
            if nopat and nopat > 0 and ic and ic > 0:
                roic = round(nopat / ic * 100, 1)

            fcf_conv = None
            if fcf and net_income and net_income != 0:
                fcf_conv = round(fcf / net_income * 100, 1)

            capex_pct = None
            if capex and revenue and revenue > 0:
                capex_pct = round(abs(capex) / revenue * 100, 1)

            da_pct = safe_div(da, revenue, pct=True)

            if not revenue:
                print(f"          ⚠ {year}: Kein Revenue — übersprungen")
                continue

            result[year] = {
                "year":               year,
                "source":             "yfinance",
                "revenue_bn":         revenue,
                "gross_profit_bn":    gross_profit,
                "ebitda_bn":          ebitda,
                "ebit_bn":            ebit,
                "net_income_bn":      net_income,
                "interest_bn":        interest,
                "ebitda_margin_pct":  ebitda_margin,
                "ebit_margin_pct":    ebit_margin,
                "gross_margin_pct":   gross_margin,
                "net_margin_pct":     net_margin,
                "fcf_margin_pct":     fcf_margin,
                "eps":                eps,
                "dps":                dps,
                "shares_bn":          shares_bn,
                "operating_cf_bn":    op_cf,
                "capex_bn":           capex,
                "capex_pct":          capex_pct,
                "fcf_bn":             fcf,
                "fcf_conversion_pct": fcf_conv,
                "da_bn":              da,
                "da_pct":             da_pct,
                "total_debt_bn":      total_debt,
                "total_cash_bn":      total_cash,
                "net_debt_bn":        net_debt,
                "total_equity_bn":    equity,
                "total_assets_bn":    assets,
                "invested_capital_bn": ic,
                "nd_ebitda":          nd_ebitda,
                "roe_pct":            roe,
                "roa_pct":            roa,
                "roic_pct":           roic,
                "tax_rate_pct":       tax_rate,
                "nopat_bn":           nopat,
            }

            if all(v is not None for v in [revenue, ebitda, ebitda_margin, eps, net_debt]):
                print(
                    f"          ✅ {year}: "
                    f"Rev {revenue:.2f} | "
                    f"EBITDA {ebitda:.2f} ({ebitda_margin:.1f}%) | "
                    f"EPS {eps} | "
                    f"ND {net_debt:.2f}"
                )
            else:
                print(f"          ✅ {year}: Rev {revenue:.2f} Mrd.")

        print(f"      ✅ {len(result)} historische Jahre geladen")
        return result

    except Exception as e:
        print(f"      ❌ get_historical_financials Fehler: {e}")
        import traceback
        traceback.print_exc()
        return {}


@tool
def get_consensus_estimates(ticker: str) -> dict:
    """Holt Analysten-Konsensschätzungen für EPS und Umsatz. Nutzt yfinance als primäre Quelle,
    Finnhub-Recommendation-Trends als Ergänzung (kostenloser Plan)."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # EPS-Schätzungen via yfinance
        eps_estimates = []
        try:
            ee = stock.earnings_estimate
            if ee is not None and not ee.empty:
                for period, row in ee.iterrows():
                    eps_estimates.append({
                        "period": str(period),
                        "consensus": row.get("avg") if hasattr(row, "get") else None,
                        "high": row.get("high") if hasattr(row, "get") else None,
                        "low": row.get("low") if hasattr(row, "get") else None,
                        "num_analysts": row.get("numberOfAnalysts") if hasattr(row, "get") else None,
                    })
        except Exception:
            pass

        # Revenue-Schätzungen via yfinance
        rev_estimates = []
        try:
            re = stock.revenue_estimate
            if re is not None and not re.empty:
                for period, row in re.iterrows():
                    rev_estimates.append({
                        "period": str(period),
                        "consensus": row.get("avg") if hasattr(row, "get") else None,
                        "high": row.get("high") if hasattr(row, "get") else None,
                        "low": row.get("low") if hasattr(row, "get") else None,
                        "num_analysts": row.get("numberOfAnalysts") if hasattr(row, "get") else None,
                    })
        except Exception:
            pass

        # Analyst-Empfehlungen via Finnhub (kostenloser Endpunkt)
        analyst_recs = {}
        price_target = {}
        try:
            client = get_finnhub_client()
            rec = client.recommendation_trends(ticker)
            latest_rec = rec[0] if rec else {}
            analyst_recs = {
                "period": latest_rec.get("period"),
                "strong_buy": latest_rec.get("strongBuy"),
                "buy": latest_rec.get("buy"),
                "hold": latest_rec.get("hold"),
                "sell": latest_rec.get("sell"),
                "strong_sell": latest_rec.get("strongSell"),
            }
            price_target = client.price_target(ticker)
        except Exception:
            # Fallback: yfinance Analyst-Daten
            analyst_recs = {
                "recommendation_key": info.get("recommendationKey", "N/A"),
                "num_analyst_opinions": info.get("numberOfAnalystOpinions", "N/A"),
            }
            price_target = {
                "targetMean": info.get("targetMeanPrice", "N/A"),
                "targetHigh": info.get("targetHighPrice", "N/A"),
                "targetLow": info.get("targetLowPrice", "N/A"),
            }

        return {
            "ticker": ticker,
            "eps_estimates": eps_estimates,
            "revenue_estimates": rev_estimates,
            "analyst_recommendations": analyst_recs,
            "price_target": price_target,
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@tool
def get_finnhub_news(ticker: str) -> list:
    """Holt aktuelle Unternehmensnews der letzten 7 Tage. Primär Finnhub, Fallback auf yfinance."""
    end = datetime.now()
    start = end - timedelta(days=7)

    # Finnhub: company_news filtert nach Ticker — prüfen ob Ergebnis firmenspezifisch ist
    try:
        client = get_finnhub_client()
        news = client.company_news(
            ticker,
            _from=start.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d"),
        )
        # Finnhub Free-Plan liefert manchmal allgemeine Marktnews statt Firmennews.
        # Validierung: mind. ein Artikel muss den Ticker im Headline/Summary erwähnen.
        company_name = ticker.upper()
        relevant = [
            item for item in news
            if ticker.upper() in (item.get("headline", "") + item.get("summary", "")).upper()
        ]
        if relevant:
            return [
                {
                    "headline": item.get("headline", "N/A"),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", "N/A"),
                    "url": item.get("url", "N/A"),
                    "published": datetime.fromtimestamp(item["datetime"]).strftime("%Y-%m-%d %H:%M") if item.get("datetime") else "N/A",
                }
                for item in relevant[:10]
            ]
    except Exception:
        pass

    # Fallback: yfinance News
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        return [
            {
                "headline": item.get("title", "N/A"),
                "summary": item.get("summary", ""),
                "source": item.get("publisher", "N/A"),
                "url": item.get("link", "N/A"),
                "published": datetime.fromtimestamp(item["providerPublishTime"]).strftime("%Y-%m-%d %H:%M") if item.get("providerPublishTime") else "N/A",
            }
            for item in news[:10]
        ] or [{"info": f"Keine News für {ticker} in den letzten 7 Tagen"}]
    except Exception as e:
        return [{"error": str(e), "ticker": ticker}]


@tool
def get_dividend_history(ticker: str) -> dict:
    """Holt Dividendenhistorie und Kennzahlen der letzten 5 Jahre via yfinance."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        dividends = stock.dividends

        if dividends.empty:
            return {"ticker": ticker, "pays_dividend": False, "history": []}

        # DataFrame → Series normalisieren (yfinance >= 0.2 gibt DataFrame zurück)
        if hasattr(dividends, "squeeze"):
            dividends = dividends.squeeze()

        # Letzte 5 Jahre filtern
        cutoff = datetime.now() - timedelta(days=5 * 365)
        recent = dividends[dividends.index >= cutoff.strftime("%Y-%m-%d")]

        history = [
            {"date": _parse_date(idx), "amount": round(float(val), 4)}
            for idx, val in recent.items()
        ]

        # Jährliche Summen berechnen
        annual = {}
        for entry in history:
            year = entry["date"][:4]
            annual[year] = round(annual.get(year, 0) + entry["amount"], 4)

        return {
            "ticker": ticker,
            "pays_dividend": True,
            "current_yield_pct": info.get("dividendYield", "N/A"),
            "trailing_annual_dividend": info.get("trailingAnnualDividendRate", "N/A"),
            "payout_ratio": info.get("payoutRatio", "N/A"),
            "ex_dividend_date": _parse_date(info.get("exDividendDate")),
            "annual_dividends": annual,
            "recent_payments": history[-8:],
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@tool
def get_cashflow_data(ticker: str) -> dict:
    """Holt detaillierte Cashflow-Kennzahlen und abgeleitete Kapitaleffizienzkennzahlen via yfinance."""
    NA = "nicht verfügbar — IR-Dokument empfohlen"
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        cf    = stock.cashflow  # Annual cashflow statement

        operating_cf: float | str = NA
        capex:        float | str = NA

        if cf is not None and not cf.empty:
            col = cf.iloc[:, 0]  # most recent annual period

            for key in ["Operating Cash Flow", "Total Cash From Operating Activities", "Cash From Operations"]:
                if key in col.index:
                    v = col[key]
                    if hasattr(v, "squeeze"):
                        v = v.squeeze()
                    try:
                        operating_cf = float(v)
                        break
                    except (TypeError, ValueError):
                        pass

            for key in ["Capital Expenditure", "Capital Expenditures",
                        "Purchase Of Property Plant And Equipment"]:
                if key in col.index:
                    v = col[key]
                    if hasattr(v, "squeeze"):
                        v = v.squeeze()
                    try:
                        capex = float(v)
                        break
                    except (TypeError, ValueError):
                        pass

        # Free Cash Flow
        free_cf: float | str = NA
        if operating_cf != NA and capex != NA:
            free_cf = operating_cf - abs(capex)

        # FCF Yield
        market_cap = info.get("marketCap")
        fcf_yield: float | str = NA
        if free_cf != NA and market_cap and market_cap > 0:
            fcf_yield = round(free_cf / market_cap * 100, 2)

        # FCF Conversion (FCF / Net Income)
        net_income = info.get("netIncomeToCommon")
        fcf_conversion: float | str = NA
        if free_cf != NA and net_income and net_income != 0:
            fcf_conversion = round(free_cf / net_income * 100, 2)

        # CapEx to Revenue
        total_revenue = info.get("totalRevenue")
        capex_to_revenue: float | str = NA
        if capex != NA and total_revenue and total_revenue > 0:
            capex_to_revenue = round(abs(capex) / total_revenue * 100, 2)

        # Net Debt / EBITDA
        total_debt = info.get("totalDebt")
        total_cash = info.get("totalCash")
        ebitda = info.get("ebitda")
        net_debt_to_ebitda: float | str = NA
        if total_debt is not None and total_cash is not None and ebitda and ebitda != 0:
            net_debt_to_ebitda = round((total_debt - total_cash) / ebitda, 2)

        # EV / FCF
        enterprise_value = info.get("enterpriseValue")
        ev_to_fcf: float | str = NA
        if enterprise_value and free_cf != NA and free_cf != 0:
            ev_to_fcf = round(enterprise_value / free_cf, 2)

        return {
            "ticker":              ticker,
            "operating_cashflow":  operating_cf,
            "capital_expenditure": capex,
            "free_cashflow":       free_cf,
            "fcf_yield_pct":       fcf_yield,
            "fcf_conversion_pct":  fcf_conversion,
            "capex_to_revenue_pct": capex_to_revenue,
            "net_debt_to_ebitda":  net_debt_to_ebitda,
            "ev_to_fcf":           ev_to_fcf,
            "source":              "yfinance",
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


@tool
def get_peers(ticker: str) -> list:
    """Holt börsennotierte Konkurrenten und deren Kennzahlen für Peer-Vergleich."""
    try:
        client = get_finnhub_client()
        peers = client.company_peers(ticker)

        # Eigene Aktie aus Peers entfernen
        peers = [p for p in peers if p != ticker][:5]

        result = []
        for peer in peers:
            try:
                stock = yf.Ticker(peer)
                info = stock.info
                result.append({
                    "ticker": peer,
                    "name": info.get("longName", peer),
                    "pe_ratio": info.get("trailingPE", "N/A"),
                    "forward_pe": info.get("forwardPE", "N/A"),
                    "price_to_book": info.get("priceToBook", "N/A"),
                    "market_cap": info.get("marketCap", "N/A"),
                    "ev_to_ebitda": info.get("enterpriseToEbitda", "N/A"),
                    "profit_margin": info.get("profitMargins", "N/A"),
                    "revenue_growth": info.get("revenueGrowth", "N/A"),
                    "roe": info.get("returnOnEquity", "N/A"),
                    "dividend_yield": info.get("dividendYield", "N/A"),
                })
            except Exception:
                result.append({"ticker": peer, "error": "Daten nicht verfügbar"})
        return result
    except Exception as e:
        return [{"error": str(e)}]


# ── Macro / Industry helpers ──────────────────────────────────────────────────

_CURRENCY_FX = {
    "CHF": {"EURCHF": "EURCHF=X", "USDCHF": "USDCHF=X"},
    "EUR": {"EURUSD": "EURUSD=X", "EURCHF": "EURCHF=X", "EURGBP": "EURGBP=X"},
    "USD": {"EURUSD": "EURUSD=X", "USDCHF": "USDCHF=X", "USDJPY": "USDJPY=X"},
    "GBP": {"GBPUSD": "GBPUSD=X", "EURGBP": "EURGBP=X"},
}

_CURRENCY_RATES = {
    "USD": {"US_10Y_Treasury": "^TNX", "US_2Y_Treasury": "^FVX", "US_3M_TBill": "^IRX"},
    "EUR": {"US_10Y_Treasury": "^TNX", "US_2Y_Treasury": "^FVX"},
    "CHF": {"US_10Y_Treasury": "^TNX", "US_2Y_Treasury": "^FVX"},
    "GBP": {"US_10Y_Treasury": "^TNX", "US_2Y_Treasury": "^FVX"},
}

_CURRENCY_KEYWORDS = {
    "CHF": ["SNB", "Swiss", "interest rate", "inflation", "Fed", "ECB", "tariff", "GDP", "PMI", "recession"],
    "EUR": ["ECB", "Eurozone", "interest rate", "inflation", "tariff", "GDP", "PMI", "recession", "Fed"],
    "USD": ["Federal Reserve", "Fed", "interest rate", "inflation", "tariff", "GDP", "PMI", "FOMC", "recession"],
    "GBP": ["Bank of England", "BoE", "UK", "interest rate", "inflation", "tariff", "GDP", "PMI"],
}


@tool
def get_macro_indicators(currency: str) -> dict:
    """Fetches macro-economic indicators (FX, rates, news) relevant to the company's home currency."""
    result: dict = {"currency": currency, "fx_rates": {}, "rate_proxies": {}, "economic_calendar": [], "macro_news": []}

    # FX rates via yfinance
    for pair, sym in _CURRENCY_FX.get(currency, {}).items():
        try:
            hist = yf.Ticker(sym).history(period="5d", auto_adjust=False)
            if not hist.empty:
                cur = round(float(hist["Close"].iloc[-1]), 4)
                prev = round(float(hist["Close"].iloc[0]), 4)
                chg = round(((cur - prev) / prev) * 100, 2) if prev else 0
                result["fx_rates"][pair] = {
                    "value": cur,
                    "change_5d_pct": chg,
                    "trend": "improving" if chg > 0.3 else ("deteriorating" if chg < -0.3 else "stable"),
                    "source": "yfinance",
                    "date": str(hist.index[-1].date()),
                }
        except Exception:
            pass

    # Interest rate proxies via yfinance
    for name, sym in _CURRENCY_RATES.get(currency, {}).items():
        try:
            hist = yf.Ticker(sym).history(period="10d", auto_adjust=False)
            if not hist.empty:
                cur = round(float(hist["Close"].iloc[-1]), 3)
                prev = round(float(hist["Close"].iloc[0]), 3)
                chg = round(cur - prev, 3)
                result["rate_proxies"][name] = {
                    "value_pct": cur,
                    "change_10d_bp": round(chg * 100, 1),
                    "trend": "improving" if chg < -0.05 else ("deteriorating" if chg > 0.05 else "stable"),
                    "source": "yfinance",
                    "date": str(hist.index[-1].date()),
                }
        except Exception:
            pass

    # Economic calendar via Finnhub (free plan may return 403 — handled gracefully)
    try:
        client = get_finnhub_client()
        cal = client.economic_calendar()
        events = cal.get("economicCalendar", [])
        country_map = {"CHF": "CH", "EUR": "EU", "USD": "US", "GBP": "GB"}
        country_code = country_map.get(currency, "")
        relevant = [e for e in events if e.get("country", "") == country_code][:5]
        result["economic_calendar"] = [
            {
                "event": e.get("event"),
                "actual": e.get("actual"),
                "estimate": e.get("estimate"),
                "previous": e.get("prev"),
                "date": str(e.get("time", ""))[:10],
            }
            for e in relevant
        ]
    except Exception:
        pass

    # Macro news via Finnhub general_news, filtered by currency-specific keywords
    keywords = _CURRENCY_KEYWORDS.get(currency, ["central bank", "inflation", "GDP", "PMI"])
    try:
        client = get_finnhub_client()
        all_news = client.general_news("general", min_id=0)
        filtered = [
            item for item in all_news
            if any(kw.lower() in (item.get("headline", "") + item.get("summary", "")).lower() for kw in keywords)
        ][:6]
        result["macro_news"] = [
            {
                "headline": item.get("headline", "N/A"),
                "summary": item.get("summary", "")[:200],
                "source": item.get("source", "N/A"),
                "published": datetime.fromtimestamp(item["datetime"]).strftime("%Y-%m-%d") if item.get("datetime") else "N/A",
            }
            for item in filtered
        ]
    except Exception:
        pass

    return result


@tool
def get_industry_indicators(sector: str, industry: str) -> dict:
    """Determines sector/industry-specific indicator topics via LLM, then fetches relevant news per topic."""
    _llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)

    # Step 1: LLM determines 4-6 relevant indicator topics
    topics: list = []
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a senior equity analyst. Reply only with a JSON array, no other text."),
            ("human", (
                "List 4-6 industry-specific indicator topics most relevant for equity analysis "
                "of sector '{sector}', industry '{industry}'. "
                "Return ONLY a JSON array of short English search terms (1-3 words each), "
                "e.g. [\"oil price\", \"construction PMI\", \"CO2 certificates\"]. No explanation."
            )),
        ])
        raw = (prompt | _llm | StrOutputParser()).invoke({"sector": sector, "industry": industry})
        s, e = raw.find("["), raw.rfind("]") + 1
        if s != -1 and e > 0:
            parsed = json.loads(raw[s:e])
            if isinstance(parsed, list):
                topics = [str(t) for t in parsed[:6]]
    except Exception:
        pass

    if not topics:
        return {"sector": sector, "industry": industry, "topics": [], "news_per_topic": {}}

    # Step 2: Fetch Finnhub general_news once, then filter per topic
    news_per_topic: dict = {}
    try:
        client = get_finnhub_client()
        all_news = client.general_news("general", min_id=0)

        for topic in topics:
            keywords = topic.lower().split()
            relevant = [
                item for item in all_news
                if any(kw in (item.get("headline", "") + item.get("summary", "")).lower() for kw in keywords)
            ][:3]
            news_per_topic[topic] = [
                {
                    "headline": item.get("headline", "N/A"),
                    "summary": item.get("summary", "")[:200],
                    "source": item.get("source", "N/A"),
                    "url": item.get("url", "N/A"),
                    "published": datetime.fromtimestamp(item["datetime"]).strftime("%Y-%m-%d") if item.get("datetime") else "N/A",
                }
                for item in relevant
            ]
    except Exception:
        pass

    return {"sector": sector, "industry": industry, "topics": topics, "news_per_topic": news_per_topic}


def _peers_cache_path(ticker: str) -> str:
    cache_dir = os.path.join("ir_cache", ticker.upper())
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "peers.json")


def discover_peers_via_tavily(
    ticker: str,
    company_name: str,
    sector: str,
    industry: str,
) -> list[str]:
    """Findet börsennotierte Konkurrenten via Tavily + LLM-Extraktion + yfinance-Validierung."""
    cache_path = _peers_cache_path(ticker)
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        age_h = (datetime.now().timestamp() - cached.get("ts", 0)) / 3600
        if age_h < 24 and cached.get("peers"):
            print(f"      Peers aus Cache ({round(age_h, 1)}h alt): {cached['peers']}")
            return cached["peers"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # Schritt 1: Tavily Suche — Unternehmensbeschreibung für Kontextgenauigkeit
    try:
        # Kurzbeschreibung aus yfinance holen (sagt "quantum hardware" statt
        # nur "Semiconductors") und auf ~200 Zeichen kürzen
        try:
            _yf_desc = yf.Ticker(ticker).info.get("longBusinessSummary", "") or ""
            _desc_snippet = _yf_desc[:200].rsplit(" ", 1)[0] if len(_yf_desc) > 200 else _yf_desc
        except Exception:
            _desc_snippet = ""

        search = TavilySearchResults(max_results=5)
        queries = [
            # Query 1: Konkurrenten mit Geschäftsmodell-Kontext (nicht nur GICS-Sektor)
            f"publicly listed stock competitors of {company_name} ({ticker}) "
            f"same business segment market ticker symbols",
            # Query 2: Peer-Group mit Beschreibung wenn vorhanden
            (
                f"{company_name} peer group comparable companies equity analysis "
                f"ticker symbols — {_desc_snippet}"
                if _desc_snippet
                else f"{company_name} {ticker} comparable companies equity research peers"
            ),
            # Query 3: Spezifische Branche aus der Unternehmensbeschreibung
            f"{ticker} {company_name} stock peers similar companies same technology",
        ]
        all_results = []
        for query in queries:
            all_results.extend(search.invoke(query))
        search_context = "\n\n".join([
            f"URL: {r.get('url', '')}\n{r.get('content', '')[:500]}"
            for r in all_results[:9]
        ])
    except Exception as e:
        print(f"      Tavily Fehler: {e}")
        return []

    # Schritt 2: LLM extrahiert Ticker-Symbole
    try:
        llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "Du bist ein Finanzanalyst. Extrahiere aus den "
             "Suchergebnissen börsennotierte Konkurrenten. "
             "Antworte NUR mit einem JSON-Array von Ticker-Symbolen. "
             "Beispiel: [\"MC.PA\", \"KER.PA\", \"BRBY.L\"] "
             "Keine Erklärungen, nur das JSON-Array."),
            ("human",
             "Unternehmen: {company} ({ticker})\n"
             "Sektor: {sector}, Industrie: {industry}\n\n"
             "Suchergebnisse:\n{context}\n\n"
             "Extrahiere 4-6 direkte Konkurrenten als Ticker-Array. "
             "Nur börsennotierte Unternehmen. "
             "Schliesse {ticker} selbst aus. "
             "Falls unsicher ob ein Ticker korrekt: weglassen."),
        ])
        raw = (prompt | llm | StrOutputParser()).invoke({
            "company": company_name,
            "ticker": ticker,
            "sector": sector,
            "industry": _desc_snippet or industry,
            "context": search_context,
        })
        s, e = raw.find("["), raw.rfind("]") + 1
        if s == -1 or e == 0:
            return []
        candidate_tickers = json.loads(raw[s:e])
    except Exception as e:
        print(f"      LLM Ticker-Extraktion Fehler: {e}")
        return []

    # Schritt 3: Ticker via yfinance validieren
    validated = []
    for peer_ticker in candidate_tickers[:8]:
        try:
            info = yf.Ticker(peer_ticker).info
            if info.get("longName") and info.get("marketCap") and peer_ticker != ticker:
                validated.append(peer_ticker)
                print(f"      Peer validiert: {peer_ticker} ({info.get('longName', '')})")
            else:
                print(f"      Peer ungültig: {peer_ticker}")
        except Exception:
            print(f"      Peer nicht gefunden: {peer_ticker}")

    result = validated[:5]

    # Cache schreiben
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"ts": datetime.now().timestamp(), "peers": result}, f)
    except Exception:
        pass

    return result


def get_dynamic_peers(
    ticker: str,
    company_name: str,
    sector: str,
    industry: str,
) -> list[str]:
    """
    Dreistufige Peer-Ermittlung:
    1. Tavily Websearch (dynamisch, für alle Branchen)
    2. Finnhub (nur für US-Titel ohne Suffix)
    3. Sektor-Fallback (letzter Ausweg)
    """
    # Industrie-spezifische Fallbacks (Priorität vor Sektor-Fallback)
    # Verhindert z.B. Chemiekonzerne als Peers für Zementhersteller
    INDUSTRY_FALLBACK = {
        # Basic Materials – Sub-Sektoren
        "Building Materials":         ["CRH", "HEI.DE", "MLM", "VMC", "SIKA.SW"],
        "Specialty Chemicals":        ["LIN", "SHW", "PPG", "ECL", "APD"],
        "Steel":                      ["MT", "NUE", "STLD", "CLF", "X"],
        "Copper":                     ["FCX", "SCCO", "HBM", "TGB"],
        "Gold":                       ["NEM", "AEM", "WPM", "GOLD"],
        "Agricultural Inputs":        ["NTR", "MOS", "CF", "ICL"],
        # Technology – Sub-Sektoren
        "Semiconductors":             ["NVDA", "AMD", "AVGO", "QCOM", "TXN"],
        "Software - Application":     ["MSFT", "SAP", "CRM", "ORCL", "NOW"],
        "Software - Infrastructure":  ["MSFT", "ORCL", "VMW", "NET", "DDOG"],
        "Computer Hardware":          ["AAPL", "HPQ", "DELL", "HPE", "NTAP"],
        "Electronic Components":      ["TEL", "APH", "GLW", "FLEX", "JABIL"],
        # Healthcare – Sub-Sektoren
        "Drug Manufacturers - General": ["LLY", "PFE", "MRK", "NVO", "AZN"],
        "Biotechnology":              ["AMGN", "GILD", "REGN", "VRTX", "BIIB"],
        "Medical Devices":            ["MDT", "ABT", "SYK", "BSX", "EW"],
        "Medical Instruments":        ["DHR", "A", "TMO", "IDXX", "METTLER"],
        # Industrials – Sub-Sektoren
        "Specialty Industrial Machinery": ["EMR", "ROK", "PH", "ITW", "IR"],
        "Aerospace & Defense":        ["RTX", "LMT", "BA", "NOC", "GD"],
        "Waste Management":           ["WM", "RSG", "CWST", "SRCL"],
        # Energy – Sub-Sektoren
        "Oil & Gas Integrated":       ["XOM", "CVX", "SHEL", "TTE", "BP"],
        "Oil & Gas E&P":              ["COP", "PXD", "EOG", "DVN", "MRO"],
        # Financial Services – Sub-Sektoren
        "Banks - Global":             ["JPM", "BAC", "HSBC", "BCS", "DB"],
        "Insurance - Life":           ["MET", "PRU", "LNC", "UNM"],
        "Asset Management":           ["BLK", "SCHW", "IVZ", "AMG"],
    }

    SECTOR_FALLBACK = {
        "Technology":             ["MSFT", "GOOGL", "META", "AMZN"],
        "Healthcare":             ["LLY", "AZN", "NVO", "ABBV"],
        "Financial Services":     ["JPM", "BAC", "GS", "MS"],
        "Consumer Defensive":     ["UL", "MDLZ", "PG", "KO"],
        "Consumer Cyclical":      ["AMZN", "HD", "MCD", "NKE"],
        "Industrials":            ["HON", "ETN", "EMR", "CAT"],
        "Basic Materials":        ["CRH", "LIN", "SHW", "MLM"],
        "Energy":                 ["XOM", "CVX", "SHEL", "TTE"],
        "Communication Services": ["GOOGL", "META", "DIS", "NFLX"],
        "Utilities":              ["NEE", "DUK", "SO", "AEP"],
        "Real Estate":            ["PLD", "AMT", "CCI", "EQIX"],
    }

    # Stufe 1: Tavily
    print(f"      Suche Peers für {company_name} via Tavily...")
    tavily_peers = discover_peers_via_tavily(ticker, company_name, sector, industry)
    if len(tavily_peers) >= 3:
        return tavily_peers

    # Stufe 2: Finnhub (nur für US-Ticker ohne Börsensuffix) — mit LLM-Gate
    # Finnhub gruppiert nach SIC-Code, nicht Geschäftsmodell → falsche Peers
    # möglich (z.B. WDC für Rigetti). LLM prüft Relevanz bevor wir sie akzeptieren.
    if "." not in ticker:
        try:
            client = get_finnhub_client()
            finnhub_peers = client.company_peers(ticker) or []
            candidates = [p for p in finnhub_peers if p != ticker][:8]
            if len(candidates) >= 3:
                try:
                    # Kurzbeschreibungen der Kandidaten für LLM-Check
                    cand_names = []
                    for c in candidates[:6]:
                        try:
                            n = yf.Ticker(c).info.get("longName", c)
                        except Exception:
                            n = c
                        cand_names.append(f"{c} ({n})")

                    _llm_gate = ChatOpenAI(model="gpt-5.4-mini", temperature=0)
                    gate_prompt = (
                        f"Unternehmen: {company_name} ({ticker}), Sektor: {sector}, "
                        f"Industrie: {industry}.\n"
                        f"Kandidaten-Peers (aus SIC-Gruppe): {', '.join(cand_names)}\n\n"
                        f"Sind mindestens 3 dieser Kandidaten WIRKLICH direkte Geschäftsmodell-Peers "
                        f"(gleicher Endmarkt, gleiches Geschäftsmodell) von {company_name}? "
                        f"Antworte NUR mit 'JA' oder 'NEIN'."
                    )
                    gate_answer = _llm_gate.invoke([{"role": "user", "content": gate_prompt}])
                    gate_ok = "JA" in (gate_answer.content or "").upper()
                except Exception:
                    gate_ok = True  # Im Zweifel Finnhub-Ergebnis nutzen

                if gate_ok:
                    peers = candidates[:5]
                    print(f"      Peers via Finnhub (LLM-validiert): {peers}")
                    return peers
                else:
                    print(f"      Finnhub-Peers abgelehnt (LLM-Gate): {candidates} — zu unähnlich")
        except Exception:
            pass

    # Stufe 3: Industrie-spezifischer Fallback (präziser als Sektor)
    if industry in INDUSTRY_FALLBACK:
        fallback = INDUSTRY_FALLBACK[industry][:5]
        print(f"      Industrie-Fallback für '{industry}': {fallback}")
    else:
        fallback = SECTOR_FALLBACK.get(sector, ["SPY"])[:5]
        print(f"      Sektor-Fallback für '{sector}': {fallback}")
    return fallback


def get_peer_financials(ticker: str, peers_override: list | None = None) -> dict:
    """
    Erstellt einen Peer-Vergleich mit sektorspezifischen Kennzahlen.

    Schritt 1: Peer-Liste via get_dynamic_peers (Tavily → Finnhub → Fallback)
               ODER via peers_override (Phase 2: Geschäftsmodell-Peers vom
               Classifier-Agenten — übersteuert die automatische Discovery,
               weil GICS-Sektor-Peers bei Spezialfällen wie Quantum-Hardware
               irreführend sind, z.B. Seagate/WDC für Rigetti)
    Schritt 2: Sektor-relevante Multiples via LLM bestimmen
    Schritt 3: Kennzahlen pro Peer via yfinance holen
    Schritt 4: Sektor-Median berechnen (Ausreisser bereinigen)
    Schritt 5: Subject vs. Median Abweichung berechnen

    Returns dict kompatibel mit PeerComparisonTable.model_dump()
    """
    _llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)

    SECTOR_MULTIPLES = {
        "Financial Services":   ["P/B", "ROE", "CET1-Ratio", "Net Interest Margin", "Cost-Income-Ratio"],
        "Real Estate":          ["P/FFO", "NAV-Discount", "LTV", "Dividend-Yield", "EV/EBITDA"],
        "Healthcare":           ["EV/EBITDA", "EV/Sales", "R&D/Sales", "Forward P/E", "FCF-Yield"],
        "Energy":               ["EV/EBITDA", "FCF-Yield", "Dividend-Yield", "ND/EBITDA", "EV/Sales"],
        "Technology":           ["EV/Sales", "EV/EBITDA", "FCF-Marge", "Umsatzwachstum", "Forward P/E"],
        "Basic Materials":      ["EV/EBITDA", "Forward P/E", "EBIT-Marge", "ND/EBITDA", "Dividend-Yield"],
    }

    DEFAULT_MULTIPLES = ["EV/EBITDA", "Forward P/E", "EBIT-Marge", "ND/EBITDA", "Dividend-Yield"]

    # ── Schritt 1: Sektor und Peer-Liste bestimmen ────────────────────────────
    sector = "N/A"
    try:
        subject_info = yf.Ticker(ticker).info
        sector = subject_info.get("sector", "N/A")
        industry = subject_info.get("industry", "N/A")
        company_name = subject_info.get("longName", ticker)
    except Exception:
        subject_info = {}
        industry = "N/A"
        company_name = ticker

    if peers_override:
        peer_tickers = [p for p in peers_override if isinstance(p, str) and p.strip()][:6]
        print(f"      Peers via Classifier-Override (Phase 2): {peer_tickers}")
    else:
        peer_tickers = get_dynamic_peers(ticker, company_name, sector, industry)

    # ── Schritt 2: Sektor-relevante Multiples ─────────────────────────────────
    relevant_multiples = SECTOR_MULTIPLES.get(sector, DEFAULT_MULTIPLES)
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Du bist Senior-Aktienanalyst. Antworte NUR mit einem JSON-Array."),
            ("human", (
                "Welche 5 Kennzahlen sind für Peer-Vergleich im Sektor '{sector}' am relevantesten? "
                "Antworte NUR mit JSON-Array, z.B. [\"EV/EBITDA\", \"Forward P/E\"]. Kein Text."
            )),
        ])
        raw = (prompt | _llm | StrOutputParser()).invoke({"sector": sector})
        s, e = raw.find("["), raw.rfind("]") + 1
        if s != -1 and e > 0:
            parsed = json.loads(raw[s:e])
            if isinstance(parsed, list) and len(parsed) >= 3:
                relevant_multiples = [str(m) for m in parsed[:5]]
    except Exception:
        pass

    # ── Schritt 3: Kennzahlen pro Peer holen ─────────────────────────────────
    def _fetch_peer_data(t: str) -> dict | None:
        try:
            info = yf.Ticker(t).info
            total_debt = info.get("totalDebt") or 0
            total_cash = info.get("totalCash") or 0
            ebitda     = info.get("ebitda") or 0
            nd_ebitda  = "-"
            if ebitda and ebitda != 0:
                nd_ebitda = round((total_debt - total_cash) / ebitda, 2)

            op_margin = info.get("operatingMargins")
            ebit_margin = round(op_margin * 100, 1) if op_margin is not None else "-"

            # Dividend Yield: dividendRate / price ist zuverlässiger als dividendYield
            div_rate  = info.get("dividendRate") or 0
            price_raw = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            if price_raw and float(price_raw) > 0 and float(div_rate) > 0:
                div_pct = round(float(div_rate) / float(price_raw) * 100, 2)
            else:
                div_raw = float(info.get("dividendYield") or 0)
                div_pct = round(div_raw * 100, 2) if div_raw < 0.5 else round(div_raw, 2)

            rev_growth = info.get("revenueGrowth")
            rev_growth_pct = round((rev_growth or 0) * 100, 1)

            roe = info.get("returnOnEquity")
            roic = round(roe * 100, 1) if roe is not None else "-"

            def _safe_r(val, decimals=1):
                try:
                    v = float(val)
                    return round(v, decimals) if v not in (float("inf"), float("-inf")) else "-"
                except (TypeError, ValueError):
                    return "-"

            mktcap_raw = info.get("marketCap")

            # EV/EBITDA: manuell berechnen (robuster als yfinance-Vorberechnung,
            # die bei CH/EU-Titeln und negativem EBITDA oft None liefert)
            ev_ebitda = "-"
            if mktcap_raw and ebitda and ebitda != 0:
                ev = float(mktcap_raw) + float(total_debt) - float(total_cash)
                ev_ebitda = _safe_r(ev / float(ebitda))
            if ev_ebitda == "-":
                ev_ebitda = _safe_r(info.get("enterpriseToEbitda"))

            ev_sales = _safe_r(info.get("enterpriseToRevenue"))

            # Forward P/E: yfinance-Feld, Fallback auf Kurs / forwardEps
            fwd_pe = _safe_r(info.get("forwardPE"))
            if fwd_pe == "-":
                fwd_eps = info.get("forwardEps")
                if fwd_eps and price_raw and float(price_raw) > 0 and float(fwd_eps) > 0:
                    fwd_pe = _safe_r(float(price_raw) / float(fwd_eps))

            p_b = _safe_r(info.get("priceToBook"))

            fcf_raw = info.get("freeCashflow")
            fcf_yield  = "-"
            if mktcap_raw and fcf_raw and float(mktcap_raw) > 0:
                fcf_yield = round(float(fcf_raw) / float(mktcap_raw) * 100, 1)

            return {
                "company":            info.get("longName", t),
                "ticker":             t,
                "country":            info.get("country", "N/A"),
                "ev_ebitda":          ev_ebitda,
                "ev_sales":           ev_sales,
                "forward_pe":         fwd_pe,
                "p_b":                p_b,
                "ebit_margin_pct":    ebit_margin,
                "nd_ebitda":          nd_ebitda,
                "dividend_yield_pct": div_pct,
                "revenue_growth_pct": rev_growth_pct,
                "roic_pct":           roic,
                "fcf_yield_pct":      fcf_yield,
            }
        except Exception:
            return None

    peers_data = []
    for pt in peer_tickers:
        d = _fetch_peer_data(pt)
        if d:
            peers_data.append(d)

    # Subject company data
    subject_data = _fetch_peer_data(ticker)
    if subject_data is None:
        subject_data = {
            "company": subject_info.get("longName", ticker),
            "ticker": ticker,
            "country": subject_info.get("country", "N/A"),
            "ev_ebitda": "-", "forward_pe": "-", "ebit_margin_pct": "-",
            "nd_ebitda": "-", "dividend_yield_pct": "-",
            "revenue_growth_pct": "-", "roic_pct": "-",
        }

    # ── Schritt 4: Sektor-Durchschnitte (Ausreisser entfernen) ───────────────
    numeric_fields = [
        "ev_ebitda", "ev_sales", "forward_pe", "p_b",
        "ebit_margin_pct", "nd_ebitda", "dividend_yield_pct",
        "revenue_growth_pct", "roic_pct", "fcf_yield_pct",
    ]

    def _avg_clean(values: list) -> float | str:
        nums = [float(v) for v in values if v not in ("n/v", "-", None, "") and str(v) not in ("n/v", "-")]
        if not nums:
            return "n/v"
        try:
            if len(nums) >= 4:
                q1 = statistics.quantiles(nums, n=4)[0]
                q3 = statistics.quantiles(nums, n=4)[2]
                iqr = q3 - q1
                lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                clean = [v for v in nums if lo <= v <= hi]
            else:
                clean = nums
            return round(statistics.mean(clean), 2) if clean else "n/v"
        except Exception:
            return "n/v"

    avg: dict = {}
    for field in numeric_fields:
        vals = [p[field] for p in peers_data]
        avg[field] = _avg_clean(vals)

    sector_averages = {
        "company":            "Sektor-Durchschnitt",
        "ticker":             "AVG",
        "country":            "",
        **avg,
    }

    # ── Schritt 5: Subject vs. Durchschnitt ──────────────────────────────────
    subject_vs_avg: dict = {}
    for field in numeric_fields:
        s_val = subject_data.get(field)
        a_val = avg.get(field)
        try:
            sv = float(s_val)
            av = float(a_val)
            if av != 0:
                pct = round((sv - av) / abs(av) * 100, 1)
                subject_vs_avg[field] = f"+{pct}%" if pct >= 0 else f"{pct}%"
            else:
                subject_vs_avg[field] = "-"
        except (TypeError, ValueError):
            subject_vs_avg[field] = "-"

    return {
        "sector":                    sector,
        "sector_relevant_multiples": relevant_multiples,
        "peers":                     peers_data,
        "sector_averages":           sector_averages,
        "subject_company":           subject_data,
        "subject_vs_avg":            subject_vs_avg,
        "methodology":               (
            "Peer-Ermittlung: Tavily Websearch → Finnhub → Sektor-Fallback | "
            "Peer-Daten via yfinance | Ausreisser (>3x Median) entfernt | "
            "Sektor-Ø = arithmetisches Mittel bereinigter Werte | "
            "Peers 24h gecacht in ir_cache/{ticker}/peers.json"
        ),
    }


@tool
def get_strategic_milestones(ticker: str, company_name: str) -> list:
    """Fetches major strategic developments (leadership changes, M&A, regulatory events)
    for a company over the past 12 months via Tavily web search. Works for any ticker."""
    try:
        search = TavilySearchResults(max_results=5)
        query = (
            f"major strategic developments, leadership changes, M&A, "
            f"and regulatory milestones for {company_name} ({ticker}) in 2025/2026"
        )
        results = search.invoke(query)
        if not results:
            return [{"info": f"Keine strategischen Meilensteine für {ticker} gefunden"}]
        return [
            {
                "title": item.get("title", item.get("content", "")[:80]),
                "url": item.get("url", "nicht verfügbar"),
                "content": item.get("content", "")[:400],
            }
            for item in results
        ]
    except Exception as e:
        return [{"info": f"Tavily nicht erreichbar: {str(e)}"}]


# ── Estimate-Anker ────────────────────────────────────────────────────────────

def build_estimate_anchors(
    ticker:          str,
    hist_data:       dict,
    ir_analysis:     dict,
    peer_comparison: dict | None = None,
) -> dict:
    """
    Berechnet Wachstumsanker für Forward-Estimates.

    Hierarchie:
      1. Historischer CAGR (deterministisch aus hist_data)
      2. Peer-Wachstum Median (aus peer_comparison)
      3. Management-Targets (aus IR-Dokument)

    Returns dict mit Ankerwerten und finaler Empfehlung.
    """
    result: dict = {}

    # ── 1. Historischer CAGR aus hist_data ───────────────────────────────────
    years = sorted(hist_data.keys()) if hist_data else []

    if len(years) >= 2:
        n_years = len(years) - 1

        # Revenue CAGR
        rev_start = hist_data[years[0]].get("revenue_bn")
        rev_end   = hist_data[years[-1]].get("revenue_bn")
        if rev_start and rev_end and rev_start > 0:
            cagr = ((rev_end / rev_start) ** (1 / n_years) - 1) * 100
            result["revenue_cagr_3y"] = round(cagr, 1)

        # EBITDA-Marge: Durchschnitt und Trend
        margins = [
            hist_data[y].get("ebitda_margin_pct")
            for y in years
            if hist_data[y].get("ebitda_margin_pct") is not None
        ]
        if margins:
            result["ebitda_margin_avg"] = round(sum(margins) / len(margins), 1)
            if len(margins) >= 2:
                result["ebitda_margin_trend"] = round(
                    (margins[-1] - margins[0]) / n_years, 1
                )

        # EPS CAGR (nur wenn beide Werte positiv)
        eps_start = hist_data[years[0]].get("eps")
        eps_end   = hist_data[years[-1]].get("eps")
        if eps_start and eps_end and eps_start > 0 and eps_end > 0:
            eps_cagr = ((eps_end / eps_start) ** (1 / n_years) - 1) * 100
            result["eps_cagr_3y"] = round(eps_cagr, 1)

    # ── 2. Peer-Wachstum Median ───────────────────────────────────────────────
    if peer_comparison:
        peer_growths = [
            p.get("revenue_growth_pct")
            for p in peer_comparison.get("peers", [])
            if isinstance(p.get("revenue_growth_pct"), (int, float))
        ]
        if peer_growths:
            peer_growths_sorted = sorted(peer_growths)
            n = len(peer_growths_sorted)
            mid = n // 2
            median = (
                peer_growths_sorted[mid]
                if n % 2 else
                (peer_growths_sorted[mid - 1] + peer_growths_sorted[mid]) / 2
            )
            result["peer_revenue_growth"] = round(median, 1)

    # ── 3. Management Guidance aus IR ────────────────────────────────────────
    guidance = {
        "revenue":  ir_analysis.get("revenue_guidance", ""),
        "ebitda_m": ir_analysis.get("ebitda_guidance", ""),
        "tone":     ir_analysis.get("management_tone", ""),
    }
    result["management_guidance"] = guidance

    # ── 4. Finale Empfehlung (konservativ: Mittelwert CAGR + Peer) ───────────
    anchors = []
    if result.get("revenue_cagr_3y") is not None:
        anchors.append(result["revenue_cagr_3y"])
    if result.get("peer_revenue_growth") is not None:
        anchors.append(result["peer_revenue_growth"])

    if anchors:
        recommended = sum(anchors) / len(anchors)
        tone = guidance.get("tone", "").lower()
        if any(w in tone for w in ("cautious", "conservative", "vorsichtig")):
            recommended *= 0.8
        elif any(w in tone for w in ("positive", "confident", "optimistic", "zuversichtlich")):
            recommended *= 1.1
        result["recommended_growth"] = round(recommended, 1)
        result["confidence"] = (
            "hoch"        if len(anchors) >= 2 else
            "mittel-hoch" if result.get("revenue_cagr_3y") is not None else
            "niedrig"
        )
    else:
        result["recommended_growth"] = 3.0
        result["confidence"] = "niedrig"

    result["methodology"] = (
        f"CAGR {result.get('revenue_cagr_3y', '-')}% "
        f"+ Peer {result.get('peer_revenue_growth', '-')}% "
        f"→ Empfehlung {result.get('recommended_growth')}% "
        f"(Konfidenz: {result.get('confidence')})"
    )

    return result


def detect_structural_anomalies(hist_data: dict) -> list:
    """
    Erkennt strukturelle Anomalien (Spin-off, M&A, Divestiture) deterministisch.
    Gibt Liste von Anomalie-Flags zurück — kein LLM, nur Zahlenvergleich.
    """
    if not hist_data or len(hist_data) < 2:
        return []

    flags = []
    sorted_years = sorted(hist_data.keys(), reverse=True)

    thresholds = [
        ("revenue_bn",      -25, "Umsatz",     "Abspaltung/Divestiture möglich"),
        ("ebitda_bn",       -30, "EBITDA",      "Strukturelle Änderung möglich"),
        ("total_assets_bn", -20, "Bilanzsumme", "Spin-off/Divestiture möglich"),
    ]

    for i in range(len(sorted_years) - 1):
        yr_curr = sorted_years[i]
        yr_prev = sorted_years[i + 1]
        curr = hist_data[yr_curr]
        prev = hist_data[yr_prev]

        for field, threshold_pct, label, hint in thresholds:
            v_curr = curr.get(field)
            v_prev = prev.get(field)
            if v_curr is None or v_prev is None or v_prev == 0:
                continue
            change_pct = (v_curr - v_prev) / abs(v_prev) * 100
            if change_pct < threshold_pct:
                flags.append({
                    "year":           yr_curr,
                    "metric":         field,
                    "yoy_change_pct": round(change_pct, 1),
                    "flag":           "STRUKTURELLE_VERÄNDERUNG",
                    "note":           (
                        f"{label} {yr_curr} vs {yr_prev}: "
                        f"{change_pct:+.1f}% — {hint}"
                    ),
                })

    return flags

    return result
