"""
tools/xbrl_fetcher.py — SEC EDGAR XBRL Company Facts fetcher

Uses the free, public SEC EDGAR API:
  https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json

Provides structured annual and quarterly financial data going back 10-15 years
for US-listed companies (10-K / 10-Q filings) — no LLM required.

Returns rows compatible with tools/financial_db.upsert_financials().
"""

from __future__ import annotations

import time
import requests
from datetime import datetime

_SEC_XBRL_BASE = "https://data.sec.gov/api/xbrl"
_HEADERS = {
    "User-Agent": "KI-Co-Analyst research@bfh.ch",
    "Accept":     "application/json",
}

# US-GAAP concept → DB field name
# Multiple candidates per field (tried in order, first non-empty wins)
_ANNUAL_CONCEPT_MAP: dict[str, list[str]] = {
    "revenue_bn": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "NetSales",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ],
    "gross_profit_bn": ["GrossProfit"],
    "ebit_bn": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "net_income_bn": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "interest_bn": [
        "InterestExpense",
        "InterestAndDebtExpense",
    ],
    "operating_cf_bn": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "capex_bn": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ],
    "da_bn": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ],
    "total_debt_bn": [
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    ],
    "total_cash_bn": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsAndShortTermInvestments",
    ],
    "total_equity_bn": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "total_assets_bn": ["Assets"],
    "shares_bn": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "eps_adj": [
        "EarningsPerShareBasic",
        "EarningsPerShareDiluted",
    ],
    "dps": [
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
}


def _fetch_facts(cik: str) -> dict | None:
    """Fetch the full company-facts JSON from SEC EDGAR XBRL API."""
    cik_padded = str(int(cik)).zfill(10)
    url = f"{_SEC_XBRL_BASE}/companyfacts/CIK{cik_padded}.json"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        r.raise_for_status()
        time.sleep(0.1)
        return r.json()
    except Exception as exc:
        print(f"      XBRL: Abruf fehlgeschlagen (CIK {cik}): {exc}")
        return None


def _extract_concept(facts: dict, concept: str,
                     form_filter: str | None = "10-K") -> dict[int, float]:
    """
    Extract annual values for a single GAAP concept.
    Returns {fiscal_year: value_in_units} dict.
    Only keeps the most recent filing per fiscal year.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    data = gaap.get(concept)
    if not data:
        return {}

    units = data.get("units", {})
    # Prefer USD, fall back to shares for EPS/shares concepts
    values_raw = units.get("USD") or units.get("shares") or units.get("pure") or []

    by_year: dict[int, tuple[float, str]] = {}  # year → (value, filed_date)
    for entry in values_raw:
        form = entry.get("form", "")
        if form_filter and not form.startswith(form_filter.replace("-", "")):
            # Accept both "10-K" and "10K" style
            if form_filter not in (form, form.replace("-", "")):
                continue
        end = entry.get("end", "")
        filed = entry.get("filed", "")
        try:
            year = int(end[:4]) if end else 0
        except ValueError:
            continue
        if year < 2005:
            continue
        val = entry.get("val")
        if val is None:
            continue
        # Keep the most recently filed entry for each fiscal year
        existing = by_year.get(year)
        if existing is None or filed > existing[1]:
            by_year[year] = (float(val), filed)

    return {yr: v for yr, (v, _) in by_year.items()}


def _scale_bn(val: float, concept: str) -> float:
    """Convert raw SEC value to billions. EPS/DPS/shares handled separately."""
    eps_concepts = {"EarningsPerShareBasic", "EarningsPerShareDiluted",
                    "CommonStockDividendsPerShareDeclared",
                    "CommonStockDividendsPerShareCashPaid"}
    share_concepts = {"CommonStockSharesOutstanding",
                      "EntityCommonStockSharesOutstanding"}
    if concept in eps_concepts:
        return round(val, 4)
    if concept in share_concepts:
        return round(val / 1e9, 4)  # shares → billions of shares
    return round(val / 1e9, 4)      # USD → billions


def fetch_xbrl_annual(ticker: str, cik: str, max_years: int = 10) -> list[dict]:
    """
    Fetch up to max_years of annual financial data from SEC EDGAR XBRL.
    Returns list of dicts compatible with financial_db.upsert_financials().
    source = 'sec_xbrl', quality_score = 3
    """
    facts = _fetch_facts(cik)
    if not facts:
        return []

    currency = "USD"
    # Collect all concepts into year-keyed dicts
    year_data: dict[int, dict] = {}

    for db_field, candidates in _ANNUAL_CONCEPT_MAP.items():
        for concept in candidates:
            values = _extract_concept(facts, concept, form_filter="10-K")
            if values:
                for yr, raw_val in values.items():
                    if yr not in year_data:
                        year_data[yr] = {}
                    if db_field not in year_data[yr]:
                        year_data[yr][db_field] = _scale_bn(raw_val, concept)
                break  # first candidate with data wins

    # Sort years descending, cap at max_years
    current_year = datetime.now().year
    sorted_years = sorted(
        [y for y in year_data if y <= current_year],
        reverse=True,
    )[:max_years]

    rows: list[dict] = []
    for yr in sorted_years:
        d = year_data[yr]
        # Derive net_debt from debt - cash
        debt = d.get("total_debt_bn")
        cash = d.get("total_cash_bn")
        if debt is not None and cash is not None:
            d["net_debt_bn"] = round(debt - cash, 4)
        # Derive FCF from operating_cf - capex
        ocf   = d.get("operating_cf_bn")
        capex = d.get("capex_bn")
        if ocf is not None and capex is not None and "fcf_bn" not in d:
            d["fcf_bn"] = round(ocf - abs(capex), 4)

        rows.append({
            "ticker":       ticker,
            "fiscal_year":  yr,
            "period_type":  "annual",
            "quarter":      None,
            "period_end":   f"{yr}-12-31",
            "currency":     currency,
            "source":       "sec_xbrl",
            "quality_score": 3,
            **d,
        })

    print(f"      XBRL: {len(rows)} Jahreswerte für {ticker} aus SEC EDGAR geladen.")
    return rows


def fetch_xbrl_quarterly(ticker: str, cik: str,
                         max_quarters: int = 12) -> list[dict]:
    """
    Fetch up to max_quarters of quarterly data from SEC EDGAR XBRL (10-Q filings).
    Returns list of dicts compatible with financial_db.upsert_financials().
    """
    facts = _fetch_facts(cik)
    if not facts:
        return []

    # Quarter-specific concepts (subset of annual)
    _Q_CONCEPTS: dict[str, list[str]] = {
        "revenue_bn":    _ANNUAL_CONCEPT_MAP["revenue_bn"],
        "net_income_bn": _ANNUAL_CONCEPT_MAP["net_income_bn"],
        "operating_cf_bn": _ANNUAL_CONCEPT_MAP["operating_cf_bn"],
        "capex_bn":      _ANNUAL_CONCEPT_MAP["capex_bn"],
        "eps_adj":       _ANNUAL_CONCEPT_MAP["eps_adj"],
    }

    # key: (fiscal_year, quarter_label) e.g. (2024, "Q2")
    qdata: dict[tuple[int, str], dict] = {}

    for db_field, candidates in _Q_CONCEPTS.items():
        for concept in candidates:
            gaap = facts.get("facts", {}).get("us-gaap", {})
            entries = gaap.get(concept, {}).get("units", {}).get("USD", [])
            for entry in entries:
                if not entry.get("form", "").startswith("10-Q"):
                    continue
                end   = entry.get("end", "")
                filed = entry.get("filed", "")
                val   = entry.get("val")
                if not end or val is None:
                    continue
                try:
                    yr  = int(end[:4])
                    mo  = int(end[5:7])
                except ValueError:
                    continue
                if yr < 2010:
                    continue
                # Map month to quarter
                q = {1: "Q1", 2: "Q1", 3: "Q1",
                     4: "Q2", 5: "Q2", 6: "Q2",
                     7: "Q3", 8: "Q3", 9: "Q3",
                     10: "Q4", 11: "Q4", 12: "Q4"}.get(mo, "Q?")
                key = (yr, q)
                if key not in qdata:
                    qdata[key] = {"_filed": filed}
                if db_field not in qdata[key] or filed > qdata[key].get("_filed", ""):
                    qdata[key][db_field] = _scale_bn(float(val), concept)
                    qdata[key]["_filed"] = filed
                    qdata[key]["_period_end"] = end
            if any(db_field in v for v in qdata.values()):
                break

    sorted_keys = sorted(qdata.keys(), key=lambda k: (k[0], k[1]), reverse=True)[:max_quarters]

    rows: list[dict] = []
    for (yr, q) in sorted_keys:
        d = {k: v for k, v in qdata[(yr, q)].items()
             if not k.startswith("_")}
        ocf   = d.get("operating_cf_bn")
        capex = d.get("capex_bn")
        if ocf is not None and capex is not None:
            d["fcf_bn"] = round(ocf - abs(capex), 4)
        rows.append({
            "ticker":       ticker,
            "fiscal_year":  yr,
            "period_type":  "quarterly",
            "quarter":      q,
            "period_end":   qdata[(yr, q)].get("_period_end", f"{yr}-{q[-1]}"),
            "currency":     "USD",
            "source":       "sec_xbrl",
            "quality_score": 3,
            **d,
        })

    print(f"      XBRL: {len(rows)} Quartalswerte für {ticker} aus SEC EDGAR geladen.")
    return rows
