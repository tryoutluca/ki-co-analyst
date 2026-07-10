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
# Mehrere Tag-Kandidaten pro Kennzahl (Firmen wechseln das Tag über die Jahre —
# Auflösung erfolgt PRO FISKALPERIODE in _extract_field_by_year(), nicht global:
# ein Ticker kann 2019 Tag A und 2024 Tag B nutzen, beide werden gemerged).
# gross_profit_bn und total_assets_bn bleiben bewusst einzeltaggig — dafür gibt
# es kein gebräuchliches alternatives US-GAAP-Tag.
_ANNUAL_CONCEPT_MAP: dict[str, list[str]] = {
    "revenue_bn": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "NetSales",
        "RevenuesNetOfInterestExpense",
    ],
    "gross_profit_bn": ["GrossProfit"],
    "ebit_bn": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    ],
    "net_income_bn": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
    ],
    "interest_bn": [
        "InterestExpense",
        "InterestAndDebtExpense",
    ],
    "operating_cf_bn": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex_bn": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements",
    ],
    "da_bn": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
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
        # SEC's eigenes fy-Feld (fiskalisches Jahr laut Filer) ist massgeblich —
        # der Kalenderjahr-Fallback (end[:4]) kann bei abweichendem Geschäftsjahr
        # (z.B. NVDA, Ende Januar) vom fy abweichen und muss mit der fy-basierten
        # Perioden-Zuordnung in fetch_xbrl_quarterly() konsistent bleiben.
        fy_field = entry.get("fy")
        if isinstance(fy_field, int):
            year = fy_field
        else:
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


def _extract_field_by_year(
    facts: dict, db_field: str, candidates: list[str], form_filter: str | None = "10-K",
) -> dict[int, float]:
    """
    Löst eine Kennzahl über mehrere US-GAAP-Tag-Kandidaten auf.

    Auflösung erfolgt PRO FISKALJAHR, nicht global: für jedes Jahr wird das
    erste Tag der Liste verwendet, das für DIESES Jahr einen Wert liefert.
    Ein früherer Kandidat, der nur einen Teil der Jahre abdeckt, blockiert damit
    nicht mehr den Fallback auf einen späteren Kandidaten für die übrigen Jahre
    (Bug: NVDA revenue_bn war für 2024-2026 NULL, weil das erste Tag brach
    ab, sobald es IRGENDEIN Jahr geliefert hatte).
    """
    merged: dict[int, float] = {}
    tag_used: dict[int, str] = {}
    for concept in candidates:
        values = _extract_concept(facts, concept, form_filter=form_filter)
        for yr, raw_val in values.items():
            if yr not in merged:
                merged[yr] = _scale_bn(raw_val, concept)
                tag_used[yr] = concept

    primary = candidates[0]
    for yr in sorted(tag_used):
        if tag_used[yr] != primary:
            print(f"        [xbrl-debug] {db_field} {yr}: Fallback-Tag "
                  f"'{tag_used[yr]}' (statt '{primary}')")
    return merged


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
        values_by_year = _extract_field_by_year(facts, db_field, candidates, form_filter="10-K")
        for yr, scaled_val in values_by_year.items():
            if yr not in year_data:
                year_data[yr] = {}
            year_data[yr][db_field] = scaled_val

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


# Flussgrössen: additiv über das Geschäftsjahr, dürfen für die Q4-Ableitung
# (Jahr − 9M-YTD) subtrahiert werden. Bestandsgrössen (Bilanzposten, Stichtag)
# sind NICHT additiv und werden nie so abgeleitet — aktuell enthält _Q_CONCEPTS
# ohnehin keine Bestandsgrösse, das Set ist trotzdem explizit als Leitplanke
# für künftige Erweiterungen. eps_adj ist bewusst ausgeschlossen: Q4-EPS lässt
# sich wegen unterschiedlicher gewichteter Aktienzahl je Quartal nicht sauber
# durch Jahr − 9M ableiten.
_FLOW_FIELDS = {"revenue_bn", "net_income_bn", "operating_cf_bn", "capex_bn"}

_VALID_FP_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}

_MONTH_TO_QUARTER = {
    1: "Q1", 2: "Q1", 3: "Q1",
    4: "Q2", 5: "Q2", 6: "Q2",
    7: "Q3", 8: "Q3", 9: "Q3",
    10: "Q4", 11: "Q4", 12: "Q4",
}


def _period_days(start: str, end: str) -> int | None:
    """Dauer eines XBRL-Facts in Tagen (start/end als 'YYYY-MM-DD')."""
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        return (e - s).days
    except (ValueError, TypeError):
        return None


def _classify_duration(days: int | None) -> str | None:
    """
    Klassifiziert einen Fact anhand seiner Dauer:
    'quarter' (diskretes Quartal, ~1 Quartal), 'ytd6'/'ytd9' (kumulierte
    Halbjahres-/9-Monats-Werte — NIE als Quartal speichern), 'annual'
    (Jahreswert — gehört in den Annual-Pfad, hier ignorieren). None für alles
    andere (z.B. unplausible/fehlende Dauer).
    """
    if days is None:
        return None
    if 80 <= days <= 100:
        return "quarter"
    if 170 <= days <= 190:
        return "ytd6"
    if 260 <= days <= 280:
        return "ytd9"
    if 350 <= days <= 380:
        return "annual"
    return None


def _fiscal_period_key(entry: dict, end: str, mo: int) -> tuple[int, str]:
    """
    Fiskaljahr/Quartal-Schlüssel für einen diskreten Quartals-Fact.

    Bevorzugt SEC's eigene fy/fp-Felder (fiskalisches Jahr/Quartal laut Filer):
    der Kalendermonat des Periodenendes sagt bei abweichendem Geschäftsjahr
    (z.B. NVDA, Ende Januar) nichts über die fiskalische Quartalsnummer aus —
    NVDAs fiskalisches Q1 endet im April und würde per Kalendermonat-Heuristik
    fälschlich als "Q2" einsortiert, was zu doppelten/kollidierenden Perioden
    führt (identisches period_end unter zwei Labels). Fallback auf die
    Kalendermonat-Heuristik nur wenn fy/fp fehlen (ältere Filings).
    """
    fy = entry.get("fy")
    fp = entry.get("fp")
    if isinstance(fy, int) and fp in _VALID_FP_QUARTERS:
        return (fy, fp)
    yr = int(end[:4])
    return (yr, _MONTH_TO_QUARTER.get(mo, "Q?"))


def fetch_xbrl_quarterly(ticker: str, cik: str,
                         max_quarters: int = 12) -> list[dict]:
    """
    Fetch up to max_quarters of quarterly data from SEC EDGAR XBRL (10-Q filings).
    Returns list of dicts compatible with financial_db.upsert_financials().

    Nur diskrete ~3-Monats-Fakten werden als Quartal übernommen (siehe
    _classify_duration) — 6M/9M-YTD-Kumulationen unter demselben Tag werden
    verworfen. Q4 wird für Flussgrössen i.d.R. NICHT direkt von der SEC
    gemeldet (steckt im 10-K) und daher als Jahreswert − 9M-YTD abgeleitet.
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
    # (fiscal_year, db_field) -> {"val":.., "filed":..} — 9M-YTD-Werte, nur
    # gesammelt für Flussgrössen, dienen ausschliesslich der Q4-Ableitung.
    ytd9: dict[tuple[int, str], dict] = {}

    gaap = facts.get("facts", {}).get("us-gaap", {})

    for db_field, candidates in _Q_CONCEPTS.items():
        # Pro Kennzahl PRO PERIODE auflösen (nicht global): ein Tag, das nur
        # einen Teil der Perioden abdeckt, darf den Fallback für die übrigen
        # Perioden nicht mehr blockieren. locked_quarter/locked_ytd9 merken
        # sich, welche Perioden bereits durch ein höher priorisiertes Tag
        # gefüllt wurden.
        locked_quarter: set[tuple[int, str]] = set()
        locked_ytd9: set[int] = set()
        for concept in candidates:
            entries = gaap.get(concept, {}).get("units", {}).get("USD", [])
            touched_quarter: set[tuple[int, str]] = set()
            touched_ytd9: set[int] = set()
            for entry in entries:
                if not entry.get("form", "").startswith("10-Q"):
                    continue
                start = entry.get("start", "")
                end   = entry.get("end", "")
                filed = entry.get("filed", "")
                val   = entry.get("val")
                if not start or not end or val is None:
                    continue
                kind = _classify_duration(_period_days(start, end))
                if kind not in ("quarter", "ytd9"):
                    continue  # ytd6/annual/unplausibel: gehören nicht hierher
                try:
                    yr = int(end[:4])
                    mo = int(end[5:7])
                except ValueError:
                    continue
                if yr < 2010:
                    continue

                if kind == "quarter":
                    key = _fiscal_period_key(entry, end, mo)
                    if key in locked_quarter:
                        continue
                    qdata.setdefault(key, {})
                    filed_marker = f"_{db_field}_filed"
                    prev_filed = qdata[key].get(filed_marker)
                    if prev_filed is None or filed > prev_filed:
                        qdata[key][db_field] = _scale_bn(float(val), concept)
                        qdata[key][filed_marker] = filed
                        qdata[key]["_period_end"] = end
                        touched_quarter.add(key)
                        if concept != candidates[0]:
                            print(f"        [xbrl-debug] {db_field} {key[0]} {key[1]}: "
                                  f"Fallback-Tag '{concept}' (statt '{candidates[0]}')")
                else:  # kind == "ytd9"
                    if db_field not in _FLOW_FIELDS:
                        continue
                    fy_field = entry.get("fy")
                    fy = fy_field if isinstance(fy_field, int) else yr
                    if fy in locked_ytd9:
                        continue
                    prev = ytd9.get((fy, db_field))
                    if prev is None or filed > prev["filed"]:
                        ytd9[(fy, db_field)] = {
                            "val": _scale_bn(float(val), concept), "filed": filed,
                        }
                        touched_ytd9.add(fy)
                        if concept != candidates[0]:
                            print(f"        [xbrl-debug] {db_field} {fy} 9M-YTD: "
                                  f"Fallback-Tag '{concept}' (statt '{candidates[0]}')")
            locked_quarter |= touched_quarter
            locked_ytd9    |= touched_ytd9

    # ── Q4-Ableitung für Flussgrössen: Jahreswert − 9M-YTD ────────────────────
    # SEC meldet Q4 für Flussgrössen praktisch nie diskret (steckt im 10-K statt
    # in einem 10-Q) — daher hier ableiten, ausser ein diskreter Q4-Fact wurde
    # oben doch schon gefunden (dann Vorrang für die echte Meldung).
    for db_field in _FLOW_FIELDS:
        if db_field not in _Q_CONCEPTS:
            continue
        annual_by_year = _extract_field_by_year(facts, db_field, _Q_CONCEPTS[db_field], form_filter="10-K")
        for fy, annual_val in annual_by_year.items():
            ytd_entry = ytd9.get((fy, db_field))
            if ytd_entry is None:
                continue
            q4_key = (fy, "Q4")
            if db_field in qdata.get(q4_key, {}):
                continue  # bereits ein diskreter Q4-Fact vorhanden — nicht überschreiben
            derived = round(annual_val - ytd_entry["val"], 4)
            qdata.setdefault(q4_key, {})
            qdata[q4_key][db_field] = derived
            print(f"        [xbrl-debug] {db_field} {fy} Q4: abgeleitet "
                  f"(Jahr {annual_val} minus 9M-YTD {ytd_entry['val']}) = {derived}")

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
