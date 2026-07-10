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


def _annual_end_dates_by_year(facts: dict) -> dict[int, str]:
    """
    Fallback-Landkarte fiscal_year -> echtes end-Datum, direkt aus den 10-K-
    Facts gescannt (unabhängig von fy/fp). Greift, wenn die fy/fp-basierte
    Fiskalkalender-Landkarte (_build_fiscal_calendar) für ein Jahr keinen
    Treffer hat (z.B. ältere Filings ohne fy/fp) — das echte end-Datum ist auf
    dem Fact trotzdem vorhanden und soll genutzt werden statt None.
    """
    result: dict[int, tuple[str, str]] = {}  # yr -> (end, filed); jüngste filed gewinnt
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept_data in gaap.values():
        for unit_entries in concept_data.get("units", {}).values():
            for entry in unit_entries:
                form = entry.get("form", "")
                if not (form.startswith("10-K") or form.startswith("10K")):
                    continue
                end = entry.get("end")
                if not end:
                    continue
                filed = entry.get("filed", "")
                fy_field = entry.get("fy")
                if isinstance(fy_field, int):
                    yr = fy_field
                else:
                    try:
                        yr = int(end[:4])
                    except ValueError:
                        continue
                existing = result.get(yr)
                if existing is None or filed > existing[1]:
                    result[yr] = (end, filed)
    return {yr: end for yr, (end, _) in result.items()}


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

    # Echte Periodenenden pro Fiskaljahr (fp == "FY") aus demselben Fiskal-
    # kalender wie assign_fiscal_label() — kein f"{yr}-12-31"-Hardcode mehr,
    # der für Nicht-Kalenderjahr-GJ (z.B. NVDA, Ende Januar) falsch wäre.
    # Fallback auf _annual_end_dates_by_year() wenn fy/fp auf den Facts fehlen
    # (ältere Filings) — auch dann ist das echte end-Datum vorhanden, nur ohne
    # fy/fp-Metadaten, und soll trotzdem verwendet werden statt NULL.
    calendar = _get_fiscal_calendar(cik, facts)
    period_end_by_year = {fy: pe for pe, (fy, q) in calendar.items() if q is None}
    fallback_end_dates = _annual_end_dates_by_year(facts)

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

        # EBITDA ist kein eigenes US-GAAP-Konzept und taucht in den XBRL-Facts
        # nie direkt auf — deterministisch aus EBIT + D&A ableiten (kein LLM,
        # keine Kennzeichnung nötig, bleibt source='sec_xbrl'). Die Margen-
        # Nachberechnung im Upsert (financial_db._compute_margins) zieht
        # danach automatisch nach.
        if d.get("ebitda_bn") is None:
            ebit = d.get("ebit_bn")
            da   = d.get("da_bn")
            if ebit is not None and da is not None:
                d["ebitda_bn"] = round(ebit + abs(da), 4)

        # Echtes Periodenende, sonst None (nie konstruiert) — siehe 7.4.
        period_end = period_end_by_year.get(yr) or fallback_end_dates.get(yr)
        # Konsistenz-Pass über die zentrale Fiskal-Label-Funktion (7.3), damit
        # auch der IR-PDF-Pfad für dieselbe Periode dasselbe Label vergibt.
        if period_end:
            assigned_year, _ = assign_fiscal_label(ticker, period_end, "annual", cik=cik, facts=facts)
            if assigned_year is not None:
                yr = assigned_year

        rows.append({
            "ticker":       ticker,
            "fiscal_year":  yr,
            "period_type":  "annual",
            "quarter":      None,
            "period_end":   period_end,
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


# ── Zentrale Fiskal-Label-Zuordnung (XBRL + IR-PDF nutzen dieselbe Funktion) ──
#
# period_end -> (fiscal_year, quarter) pro CIK, gecached für die Laufzeit des
# Prozesses (SEC-Fiskalkalender ändert sich nicht innerhalb einer Analyse).
_FISCAL_CALENDAR_CACHE: dict[str, dict[str, tuple[int, str | None]]] = {}


def _build_fiscal_calendar(cik: str, facts: dict | None = None) -> dict[str, tuple[int, str | None]]:
    """
    Baut eine period_end -> (fiscal_year, quarter) Landkarte aus SEC's eigenen
    fy/fp-Feldern, indem ALLE us-gaap-Fakten (nicht nur ein Konzept) gescannt
    werden. quarter ist None für Jahres-Perioden (fp == "FY").
    """
    if facts is None:
        facts = _fetch_facts(cik)
    calendar: dict[str, tuple[int, str | None]] = {}
    if not facts:
        return calendar

    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept_data in gaap.values():
        for unit_entries in concept_data.get("units", {}).values():
            for entry in unit_entries:
                end = entry.get("end")
                fy  = entry.get("fy")
                fp  = entry.get("fp")
                if not end or not isinstance(fy, int) or not fp:
                    continue
                if fp == "FY":
                    calendar.setdefault(end, (fy, None))
                elif fp in _VALID_FP_QUARTERS:
                    calendar.setdefault(end, (fy, fp))
    return calendar


def _get_fiscal_calendar(cik: str | None, facts: dict | None) -> dict[str, tuple[int, str | None]]:
    """Cache-Lookup-oder-Build für die period_end -> (fiscal_year, quarter) Landkarte."""
    if not cik and not facts:
        return {}
    cache_key = cik or f"_facts_{id(facts)}"
    calendar = _FISCAL_CALENDAR_CACHE.get(cache_key)
    if calendar is None:
        calendar = _build_fiscal_calendar(cik, facts=facts)
        _FISCAL_CALENDAR_CACHE[cache_key] = calendar
    return calendar


def assign_fiscal_label(
    ticker: str,
    period_end: str,
    period_type: str = "annual",
    cik: str | None = None,
    facts: dict | None = None,
) -> tuple[int | None, str | None]:
    """
    Zentrale Fiskal-Label-Zuordnung: leitet (fiscal_year, quarter) aus dem
    tatsächlichen Periodenende und dem Fiskalkalender des Unternehmens ab.

    MUSS von beiden Extraktionspfaden (SEC-XBRL und IR-PDF) verwendet werden,
    sonst leiten sie das Label für dieselbe Berichtsperiode unterschiedlich ab
    und die Quellen-Priorität im Upsert greift nie (zwei Primary Keys für
    dieselbe Periode). Bevorzugt SEC's eigene fy/fp-Werte aus companyfacts
    (siehe _build_fiscal_calendar) — für US-Ticker i.d.R. exakt, unabhängig
    vom Geschäftsjahres-Ende.

    Fallback (kein CIK/keine SEC-Daten, z.B. Nicht-US-Ticker, oder period_end
    kommt in der SEC-Landkarte nicht exakt vor): Kalenderjahr/-monat von
    period_end selbst — schwächer, aber die einzige verfügbare Information
    ausserhalb der SEC-Welt. Ohne period_end (None) ist keine Ableitung
    möglich — gibt (None, None) zurück.
    """
    if not period_end:
        return (None, None)

    if cik is None and facts is None:
        from tools.ir_rag_tool import _sec_is_us_ticker, get_sec_cik
        if _sec_is_us_ticker(ticker):
            cik = get_sec_cik(ticker)

    calendar = _get_fiscal_calendar(cik, facts)
    hit = calendar.get(period_end)
    if hit is not None:
        return hit

    # Fallback: aus dem Kalenderdatum selbst ableiten.
    try:
        yr = int(period_end[:4])
        mo = int(period_end[5:7])
    except (ValueError, TypeError, IndexError):
        return (None, None)
    if period_type == "annual":
        return (yr, None)
    return (yr, _MONTH_TO_QUARTER.get(mo))


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
                    assigned_year, assigned_q = assign_fiscal_label(
                        ticker, end, "quarterly", cik=cik, facts=facts,
                    )
                    key = (assigned_year if assigned_year is not None else yr,
                           assigned_q or _MONTH_TO_QUARTER.get(mo, "Q?"))
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
    # Q4 endet exakt am Fiskaljahresende — dasselbe echte Datum wie im Annual-
    # Pfad (7.4), nie ein konstruiertes.
    calendar = _get_fiscal_calendar(cik, facts)
    annual_period_end_by_year = {fy: pe for pe, (fy, q) in calendar.items() if q is None}
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
            qdata[q4_key].setdefault("_period_end", annual_period_end_by_year.get(fy))
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
            # Echtes Periodenende, sonst None (nie konstruiert) — siehe 7.4.
            "period_end":   qdata[(yr, q)].get("_period_end"),
            "currency":     "USD",
            "source":       "sec_xbrl",
            "quality_score": 3,
            **d,
        })

    print(f"      XBRL: {len(rows)} Quartalswerte für {ticker} aus SEC EDGAR geladen.")
    return rows
