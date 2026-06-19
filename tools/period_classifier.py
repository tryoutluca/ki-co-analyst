"""
tools/period_classifier.py — Period classification for financial data ingestion.

Guards the MultiplesEngine level inputs against period contamination:
a quarterly value must never be treated as an annual FY value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

PeriodType = Literal["annual", "quarterly", "h1", "9m", "ttm"]

# ── Regex patterns for PDF title classification ───────────────────────────────

_ANNUAL_RX = re.compile(
    r"""
    annual\s+report
    | full[\s_\-]year(?:\s+results?)?
    | geschäftsbericht | jahresbericht | jahresabschluss | jahresergebnis
    | rapport\s+annuel | bilan\s+annuel
    | fy\s*20\d{2}\b
    | financial\s+report\s+20\d{2}
    | integrated\s+report
    | annual\s+results?
    | full\s+year\s+results?
    | gesamtjahr | ganzjahresergebnis
    """,
    re.I | re.VERBOSE,
)

_INTERIM_RX = re.compile(
    r"""
    \bq[1-4]\b
    | quartal(?:s|sbericht|sergebnis)?
    | quarter(?:ly)?(?:\s+results?)?
    | half[\s_\-]year(?:\s+results?)?
    | halbjahres(?:bericht|ergebnis|abschluss)?
    | interim(?:\s+report|\s+results?)?
    | semest(?:er|riel)?
    | six[\s_\-]months?
    | 9[\s_\-]months?  | nine[\s_\-]months?
    | first\s+half | second\s+half
    | h1[\s_\.\-] | h2[\s_\.\-]
    | q[1-4]\s+20\d{2}
    | zwischenbericht | zwischenmitteilung
    | 6[\s_\-]k\b
    """,
    re.I | re.VERBOSE,
)


def classify_pdf_period(title: str) -> Optional[PeriodType]:
    """
    Classify the reporting period from a PDF document title or filing type.

    Returns None when ambiguous — callers MUST NOT treat the document
    as an annual FY source in that case.

    Accepts SEC form-type strings too:
        "20-F" → "annual"
        "10-K" → "annual"
        "10-Q" → "quarterly"
        "6-K"  → "quarterly"
    """
    # Direct SEC form-type mapping
    stripped = title.strip().upper()
    if stripped in ("10-K", "20-F", "10-K/A", "20-F/A"):
        return "annual"
    if stripped in ("10-Q", "6-K", "10-Q/A"):
        return "quarterly"

    is_annual  = bool(_ANNUAL_RX.search(title))
    is_interim = bool(_INTERIM_RX.search(title))

    if is_annual and not is_interim:
        return "annual"
    if is_interim and not is_annual:
        t = title.lower()
        if re.search(r"h1|half[\s_\-]year|six[\s_\-]month|halbjahr|first\s+half", t):
            return "h1"
        if re.search(r"9[\s_\-]month|nine[\s_\-]month", t):
            return "9m"
        return "quarterly"
    return None  # ambiguous — do not use as annual source


def validate_yfinance_annual_columns(cashflow_df) -> tuple[bool, str]:
    """
    Verify that the yfinance cashflow DataFrame's most-recent column
    represents a full fiscal year (column gap ≥ 200 days from prior column).

    Returns (is_valid_annual, warning_message).
    Empty warning_message means no problem.
    """
    if cashflow_df is None or cashflow_df.empty:
        return False, "Cashflow DataFrame leer"
    cols = sorted(cashflow_df.columns, reverse=True)
    if len(cols) < 2:
        return True, ""  # single column — cannot verify, accept
    try:
        gap = (cols[0] - cols[1]).days
    except Exception:
        return True, ""  # can't compute gap, accept
    if gap < 200:
        return False, (
            f"⚠ Cashflow-Spaltenabstand {gap} Tage < 200 — "
            "wahrscheinlich quarterly statt annual (partial-period)"
        )
    return True, ""


def check_ratio_guard(
    candidate: float,
    prior_year: float,
    label: str = "Flow",
    low: float = 0.40,
    high: float = 1.75,
) -> tuple[bool, str]:
    """
    Ratio-to-Prior-Year guard: candidate must lie in [low×prior, high×prior].
    Returns (passed, warning_message).
    """
    if prior_year == 0:
        return True, ""
    ratio = candidate / prior_year
    if not (low <= ratio <= high):
        return False, (
            f"⚠ {label} Ratio-zu-Vorjahr: {candidate:.2f} / {prior_year:.2f} = {ratio:.2f} "
            f"ausserhalb [{low:.2f}, {high:.2f}] — periodenverdächtig"
        )
    return True, ""


# ── Data containers ───────────────────────────────────────────────────────────

@dataclass
class FinancialValue:
    """Tagged financial metric with full period provenance."""
    value:       float
    period_type: PeriodType
    period_end:  date
    fiscal_year: int
    currency:    str
    source:      str   # "yfinance" | "ir_pdf" | "sec_edgar" | "finnhub"


@dataclass
class QuarterlySignal:
    """
    Quarterly data re-routed exclusively to forward estimates.
    NEVER overwrites annual (A) actuals in MultiplesEngine or _full_financials.
    """
    ticker:                    str
    source_metric:             str              # "fcf" | "revenue"
    raw_q_value:               Optional[float]  # latest single-quarter value (Bn)
    yoy_comparable_growth:     Optional[float]  # latest Q vs prior-year Q (%)
    qoq_growth:                Optional[float]  # Q vs prior Q (%)
    run_rate_ttm:              Optional[float]  # sum of 4 most recent quarters (Bn)
    prior_year_comp_depressed: bool             # True → dampen momentum extrapolation
    period_end:                Optional[date]
    guard_messages:            list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ticker":                    self.ticker,
            "source_metric":             self.source_metric,
            "raw_q_value":               self.raw_q_value,
            "yoy_comparable_growth":     self.yoy_comparable_growth,
            "qoq_growth":                self.qoq_growth,
            "run_rate_ttm":              self.run_rate_ttm,
            "prior_year_comp_depressed": self.prior_year_comp_depressed,
            "period_end":                self.period_end.isoformat() if self.period_end else None,
            "guard_messages":            self.guard_messages,
        }
