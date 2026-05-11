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
    NA_FINAL = "n/v — IR-Dokument empfohlen"

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
    """Holt historische Bewertungskennzahlen (P/E, P/B, EV/EBITDA) der letzten 5 Jahre via Finnhub."""
    try:
        client = get_finnhub_client()
        metrics = client.company_basic_financials(ticker, "all")
        series = metrics.get("series", {}).get("annual", {})

        def extract_series(key):
            data = series.get(key, [])
            # Neueste 5 Jahre: nach period absteigend sortieren
            sorted_data = sorted(data, key=lambda d: d.get("period", ""), reverse=True)
            return [{"period": d.get("period"), "value": d.get("v")} for d in sorted_data[:5]]

        return {
            "ticker": ticker,
            "pe_ratio": extract_series("pe"),
            "pb_ratio": extract_series("pb"),
            "ps_ratio": extract_series("ps"),
            "ev_to_ebitda": extract_series("currentEv/freeCashflowTTM"),
            "roe": extract_series("roeTTM"),
            "roa": extract_series("roaTTM"),
            "net_margin": extract_series("netProfitMarginTTM"),
            "revenue_growth": extract_series("revenueGrowthTTMYoy"),
        }
    except Exception as e:
        return {"error": str(e), "ticker": ticker}


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
    _llm = ChatOpenAI(model="gpt-5.4", temperature=0)

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

    # Schritt 1: Tavily Suche
    try:
        search = TavilySearchResults(max_results=5)
        queries = [
            f"main publicly listed competitors of {company_name} "
            f"in {industry} with stock ticker symbols",
            f"{company_name} {ticker} peer group comparable companies "
            f"equity analysis ticker symbols",
        ]
        all_results = []
        for query in queries:
            all_results.extend(search.invoke(query))
        search_context = "\n\n".join([
            f"URL: {r.get('url', '')}\n{r.get('content', '')[:500]}"
            for r in all_results[:6]
        ])
    except Exception as e:
        print(f"      Tavily Fehler: {e}")
        return []

    # Schritt 2: LLM extrahiert Ticker-Symbole
    try:
        llm = ChatOpenAI(model="gpt-5.4", temperature=0)
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
            "industry": industry,
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
    SECTOR_FALLBACK = {
        "Technology":             ["MSFT", "GOOGL", "META", "AMZN"],
        "Healthcare":             ["LLY", "AZN", "NVO", "ABBV"],
        "Financial Services":     ["JPM", "BAC", "GS", "MS"],
        "Consumer Defensive":     ["UL", "MDLZ", "PG", "KO"],
        "Consumer Cyclical":      ["AMZN", "HD", "MCD", "NKE"],
        "Industrials":            ["HON", "ETN", "EMR", "CAT"],
        "Basic Materials":        ["LIN", "APD", "SHW", "PPG"],
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

    # Stufe 2: Finnhub (nur für US-Ticker ohne Börsensuffix)
    if "." not in ticker:
        try:
            client = get_finnhub_client()
            finnhub_peers = client.company_peers(ticker) or []
            peers = [p for p in finnhub_peers if p != ticker][:5]
            if len(peers) >= 3:
                print(f"      Peers via Finnhub: {peers}")
                return peers
        except Exception:
            pass

    # Stufe 3: Sektor-Fallback
    fallback = SECTOR_FALLBACK.get(sector, ["SPY"])[:5]
    print(f"      Sektor-Fallback für '{sector}': {fallback}")
    return fallback


def get_peer_financials(ticker: str) -> dict:
    """
    Erstellt einen Peer-Vergleich mit sektorspezifischen Kennzahlen.

    Schritt 1: Peer-Liste via get_dynamic_peers (Tavily → Finnhub → Fallback)
    Schritt 2: Sektor-relevante Multiples via LLM bestimmen
    Schritt 3: Kennzahlen pro Peer via yfinance holen
    Schritt 4: Sektor-Median berechnen (Ausreisser bereinigen)
    Schritt 5: Subject vs. Median Abweichung berechnen

    Returns dict kompatibel mit PeerComparisonTable.model_dump()
    """
    _llm = ChatOpenAI(model="gpt-5.4", temperature=0)

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
            nd_ebitda  = "n/v"
            if ebitda and ebitda != 0:
                nd_ebitda = round((total_debt - total_cash) / ebitda, 2)

            op_margin = info.get("operatingMargins")
            ebit_margin = round(op_margin * 100, 1) if op_margin is not None else "n/v"

            div_yield = info.get("dividendYield")
            div_pct = round((div_yield or 0) * 100, 2)

            rev_growth = info.get("revenueGrowth")
            rev_growth_pct = round((rev_growth or 0) * 100, 1)

            roe = info.get("returnOnEquity")
            roic = round(roe * 100, 1) if roe is not None else "n/v"

            ev_ebitda = info.get("enterpriseToEbitda", "n/v")
            if ev_ebitda is not None and ev_ebitda != "n/v":
                try:
                    ev_ebitda = round(float(ev_ebitda), 1)
                except (TypeError, ValueError):
                    ev_ebitda = "n/v"

            fwd_pe = info.get("forwardPE", "n/v")
            if fwd_pe is not None and fwd_pe != "n/v":
                try:
                    fwd_pe = round(float(fwd_pe), 1)
                except (TypeError, ValueError):
                    fwd_pe = "n/v"

            return {
                "company":            info.get("longName", t),
                "ticker":             t,
                "country":            info.get("country", "N/A"),
                "ev_ebitda":          ev_ebitda,
                "forward_pe":         fwd_pe,
                "ebit_margin_pct":    ebit_margin,
                "nd_ebitda":          nd_ebitda,
                "dividend_yield_pct": div_pct,
                "revenue_growth_pct": rev_growth_pct,
                "roic_pct":           roic,
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
            "ev_ebitda": "n/v", "forward_pe": "n/v", "ebit_margin_pct": "n/v",
            "nd_ebitda": "n/v", "dividend_yield_pct": "n/v",
            "revenue_growth_pct": "n/v", "roic_pct": "n/v",
        }

    # ── Schritt 4: Sektor-Durchschnitte (Ausreisser entfernen) ───────────────
    numeric_fields = [
        "ev_ebitda", "forward_pe", "ebit_margin_pct",
        "nd_ebitda", "dividend_yield_pct", "revenue_growth_pct", "roic_pct",
    ]

    def _avg_clean(values: list) -> float | str:
        nums = [float(v) for v in values if v not in ("n/v", None, "") and str(v) != "n/v"]
        if not nums:
            return "n/v"
        try:
            med = statistics.median(nums)
            clean = [v for v in nums if abs(v) <= abs(med) * 3 + 1]
            return round(sum(clean) / len(clean), 2) if clean else "n/v"
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
                subject_vs_avg[field] = "n/v"
        except (TypeError, ValueError):
            subject_vs_avg[field] = "n/v"

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
