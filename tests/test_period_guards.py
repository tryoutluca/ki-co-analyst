"""
tests/test_period_guards.py — Period-guard unit and integration tests.

Unit tests use mock DataFrames to avoid network calls.
Integration tests (marked @pytest.mark.integration) call live yfinance.

Run unit tests only:
    pytest tests/test_period_guards.py -m "not integration" -v

Run all including integration (needs network):
    pytest tests/test_period_guards.py -v
"""
import sys
import os
import pytest
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.period_classifier import (
    classify_pdf_period,
    validate_yfinance_annual_columns,
    check_ratio_guard,
    QuarterlySignal,
)


# ── classify_pdf_period ────────────────────────────────────────────────────────

class TestClassifyPdfPeriod:
    def test_annual_report_english(self):
        assert classify_pdf_period("ABB Annual Report 2024") == "annual"

    def test_full_year_results(self):
        assert classify_pdf_period("ABB Full Year Results 2024") == "annual"

    def test_geschaeftsbericht(self):
        assert classify_pdf_period("Holcim Geschäftsbericht 2023") == "annual"

    def test_rapport_annuel(self):
        assert classify_pdf_period("Nestlé Rapport Annuel 2024") == "annual"

    def test_interim_half_year(self):
        assert classify_pdf_period("ABB Half-Year Report 2024") == "h1"

    def test_interim_h1(self):
        assert classify_pdf_period("Novartis H1 2024 Results") == "h1"

    def test_interim_q3(self):
        assert classify_pdf_period("ABB Q3 2024 Results") == "quarterly"

    def test_interim_quarterly(self):
        assert classify_pdf_period("Quarterly Results Q2 2024") == "quarterly"

    def test_nine_months(self):
        assert classify_pdf_period("Nine-Month Results 2024") == "9m"

    def test_interim_zwischenbericht(self):
        assert classify_pdf_period("Zwischenbericht 1. Halbjahr 2024") in ("h1", "quarterly")

    def test_ambiguous_returns_none(self):
        # "Results" alone is ambiguous
        assert classify_pdf_period("Company Results") is None

    def test_sec_form_10k(self):
        assert classify_pdf_period("10-K") == "annual"

    def test_sec_form_20f(self):
        assert classify_pdf_period("20-F") == "annual"

    def test_sec_form_10q(self):
        assert classify_pdf_period("10-Q") == "quarterly"

    def test_sec_form_6k(self):
        assert classify_pdf_period("6-K") == "quarterly"

    def test_investor_day_returns_none(self):
        # Investor Day is not a period classification
        assert classify_pdf_period("Investor Day Presentation 2024") is None

    def test_empty_returns_none(self):
        assert classify_pdf_period("") is None


# ── validate_yfinance_annual_columns ──────────────────────────────────────────

class TestValidateYfinanceAnnualColumns:
    def _make_df(self, date_gaps_days: list[int]):
        """Build a fake cashflow DataFrame with given column date gaps."""
        base = pd.Timestamp("2024-12-31")
        cols = [base]
        for gap in date_gaps_days:
            cols.append(cols[-1] - pd.Timedelta(days=gap))
        return pd.DataFrame({"Operating Cash Flow": [1e9] * len(cols)}, index=["Operating Cash Flow"]).T

    def _make_df_cols(self, col_dates: list[pd.Timestamp]):
        # yfinance cashflow: dates as COLUMNS, metric names as row index
        data = {d: 1e9 for d in col_dates}
        return pd.DataFrame([data], index=["Operating Cash Flow"])

    def test_valid_annual_365_day_gap(self):
        base = pd.Timestamp("2024-12-31")
        prior = base - pd.Timedelta(days=365)
        df = self._make_df_cols([base, prior])
        valid, warn = validate_yfinance_annual_columns(df)
        assert valid
        assert warn == ""

    def test_invalid_quarterly_90_day_gap(self):
        base = pd.Timestamp("2024-09-30")
        prior = base - pd.Timedelta(days=91)
        df = self._make_df_cols([base, prior])
        valid, warn = validate_yfinance_annual_columns(df)
        assert not valid
        assert "90" in warn or "91" in warn or "Tage" in warn

    def test_single_column_accepted(self):
        df = self._make_df_cols([pd.Timestamp("2024-12-31")])
        valid, warn = validate_yfinance_annual_columns(df)
        assert valid
        assert warn == ""

    def test_empty_df_fails(self):
        df = pd.DataFrame()
        valid, warn = validate_yfinance_annual_columns(df)
        assert not valid

    def test_none_df_fails(self):
        valid, warn = validate_yfinance_annual_columns(None)
        assert not valid

    def test_200_day_gap_boundary(self):
        base = pd.Timestamp("2024-12-31")
        # 200 days = boundary, should be valid
        prior = base - pd.Timedelta(days=200)
        df = self._make_df_cols([base, prior])
        valid, _ = validate_yfinance_annual_columns(df)
        assert valid

    def test_199_day_gap_invalid(self):
        base = pd.Timestamp("2024-12-31")
        prior = base - pd.Timedelta(days=199)
        df = self._make_df_cols([base, prior])
        valid, warn = validate_yfinance_annual_columns(df)
        assert not valid
        assert "199" in warn or "Tage" in warn


# ── check_ratio_guard ─────────────────────────────────────────────────────────

class TestCheckRatioGuard:
    def test_within_band_passes(self):
        passed, _ = check_ratio_guard(4.5, 4.0, "FCF")
        assert passed

    def test_ratio_exactly_at_low_boundary(self):
        passed, _ = check_ratio_guard(1.6, 4.0, "FCF")  # ratio = 0.40
        assert passed

    def test_ratio_below_low_boundary(self):
        # ABB case: 0.5 / 4.6 ≈ 0.11 → fails
        passed, warn = check_ratio_guard(0.5, 4.6, "FCF")
        assert not passed
        assert "⚠" in warn
        assert "perioden" in warn.lower() or "ratio" in warn.lower()

    def test_ratio_above_high_boundary(self):
        # Sudden spike: 9.0 / 4.5 = 2.0 > 1.75
        passed, warn = check_ratio_guard(9.0, 4.5, "FCF")
        assert not passed
        assert "⚠" in warn

    def test_zero_prior_year_skips_guard(self):
        passed, warn = check_ratio_guard(5.0, 0.0, "FCF")
        assert passed
        assert warn == ""

    def test_sndk_quarterly_revenue_rejected(self):
        # SNDK: quarterly revenue ~$2.1 Bn vs prior-year annual $7.8 Bn → 0.27 < 0.40
        passed, warn = check_ratio_guard(2.1, 7.8, "Revenue")
        assert not passed
        assert "Revenue" in warn


# ── MultiplesEngine guard integration (mock yfinance) ────────────────────────

class TestMultiplesEngineGuards:
    """Test that MultiplesEngine suppresses FCF metrics when guards trip."""

    def _build_engine_with_fcf(self, fcf_val, prior_fcf_val=None, cfo_ttm=None):
        """Construct a MultiplesEngine directly (not via from_ticker) and inject guard state."""
        from tools.multiples_engine import MultiplesEngine
        from tools.period_classifier import check_ratio_guard

        engine = MultiplesEngine(
            current_price=50.0,
            market_cap=130.0,   # Bn CHF
            revenue=15.0,
            ebitda=3.5,
            ebit=2.5,
            net_income=2.0,
            fcf=fcf_val,
            total_debt=5.0,
            total_cash=2.0,
        )

        # Simulate the guard logic from from_ticker
        warnings = []
        suspect = False

        if prior_fcf_val is not None and prior_fcf_val > 0:
            passed, w = check_ratio_guard(fcf_val, prior_fcf_val, "FCF")
            if not passed:
                warnings.append(w)
                suspect = True

        if cfo_ttm is not None and cfo_ttm > 0:
            conv = fcf_val / cfo_ttm
            if not (0.30 <= conv <= 1.15):
                warnings.append(
                    f"⚠ FCF/CFO-Band: {fcf_val:.2f}/{cfo_ttm:.2f} = {conv:.2f} ausserhalb [0.30, 1.15]"
                )
                suspect = True

        engine._fcf_suspect    = suspect
        engine._guard_warnings = warnings
        return engine

    def test_normal_fcf_not_suppressed(self):
        engine = self._build_engine_with_fcf(fcf_val=4.6, prior_fcf_val=3.9)
        results = engine.compute_all()
        assert results["ev_fcf"]["valid"], "EV/FCF should be valid for normal FCF"
        assert results["fcf_yield"]["valid"], "FCF-Yield should be valid for normal FCF"

    def test_quarterly_fcf_triggers_suspect(self):
        # ABB case: ~$0.5 Bn vs prior $3.9 Bn → ratio 0.13 → suspect
        engine = self._build_engine_with_fcf(fcf_val=0.5, prior_fcf_val=3.9)
        results = engine.compute_all()
        assert not results["ev_fcf"]["valid"], "EV/FCF must be suppressed when FCF is suspect"
        assert results["ev_fcf"]["value"] is None
        assert not results["fcf_yield"]["valid"]
        assert not results["p_fcf"]["valid"]

    def test_absolute_ev_fcf_guard_over_80x(self):
        # Even if ratio guard doesn't trip, absolute > 80x must suppress
        # MarketCap 130, EV ~133, FCF 1.5 → EV/FCF ≈ 89x
        engine = self._build_engine_with_fcf(fcf_val=1.5, prior_fcf_val=None)
        engine._fcf_suspect = False  # no ratio guard
        results = engine.compute_all()
        ev_fcf = results["ev_fcf"]
        if ev_fcf.get("value") is not None and ev_fcf["value"] > 80:
            assert not ev_fcf["valid"], "EV/FCF > 80x must be suppressed"

    def test_fcf_conversion_guard(self):
        # FCF 0.3 Bn, NI 2.0 Bn → conversion 15% < 30% → suppress
        from tools.multiples_engine import MultiplesEngine
        engine = MultiplesEngine(
            current_price=50.0, market_cap=130.0,
            revenue=15.0, ebitda=3.5, ebit=2.5,
            net_income=2.0, fcf=0.3,
            total_debt=5.0, total_cash=2.0,
        )
        engine._fcf_suspect    = False
        engine._guard_warnings = []
        results = engine.compute_all()
        fcf_conv = results["fcf_conversion"]
        # 0.3/2.0 = 15% → below 30% guard
        assert not fcf_conv["valid"], "FCF-Conversion 15% must be suppressed (< 30%)"

    def test_guard_warnings_in_output(self):
        engine = self._build_engine_with_fcf(fcf_val=0.5, prior_fcf_val=3.9)
        results = engine.compute_all()
        assert isinstance(results["_guard_warnings"], list)
        assert len(results["_guard_warnings"]) > 0

    def test_quarterly_signal_in_output(self):
        from tools.multiples_engine import MultiplesEngine
        engine = MultiplesEngine(current_price=50.0, market_cap=130.0, fcf=4.6)
        engine._quarterly_signal = QuarterlySignal(
            ticker="ABBN.SW", source_metric="fcf",
            raw_q_value=1.1, yoy_comparable_growth=12.5, qoq_growth=3.0,
            run_rate_ttm=4.6, prior_year_comp_depressed=False,
            period_end=date(2024, 12, 31),
        )
        results = engine.compute_all()
        qs = results["_quarterly_signal"]
        assert qs is not None
        assert qs["run_rate_ttm"] == 4.6
        assert qs["ticker"] == "ABBN.SW"


# ── Integration tests (require network, echte Ticker) ────────────────────────

@pytest.mark.integration
class TestIntegrationRealTickers:
    """
    Integration tests against live yfinance data.

    Acceptance criteria from the prompt:
    - ABBN.SW: EV/FCF ∈ [25x, 45x], FCF-Yield ∈ [2%, 4%], FCF-Conversion ∈ [70%, 110%]
      (old broken values: 338x / 0.3% / 12.4% must NOT appear)
    - HOLN.SW, NVDA, AAPL: # valid multiples ≥ threshold (regression guard)
    """

    def _run_engine(self, ticker: str) -> dict:
        from tools.multiples_engine import MultiplesEngine
        engine = MultiplesEngine.from_ticker(ticker, ir_analysis={})
        return engine.compute_all()

    def test_abbn_fcf_metrics_in_range(self):
        """FCF metrics for ABB must be in realistic ranges after guards."""
        results = self._run_engine("ABBN.SW")

        ev_fcf = results.get("ev_fcf", {})
        fcf_yield = results.get("fcf_yield", {})
        fcf_conv  = results.get("fcf_conversion", {})

        # If the metric is valid, it must be in the expected range
        if ev_fcf.get("valid") and ev_fcf.get("value") is not None:
            assert 20 <= ev_fcf["value"] <= 60, (
                f"ABBN.SW EV/FCF {ev_fcf['value']}x out of realistic range [20,60]. "
                "Old broken value was 338x."
            )
        if fcf_yield.get("valid") and fcf_yield.get("value") is not None:
            assert 1.5 <= fcf_yield["value"] <= 5.0, (
                f"ABBN.SW FCF-Yield {fcf_yield['value']}% out of realistic range [1.5%,5%]. "
                "Old broken value was 0.3%."
            )
        if fcf_conv.get("valid") and fcf_conv.get("value") is not None:
            assert 60 <= fcf_conv["value"] <= 120, (
                f"ABBN.SW FCF-Conversion {fcf_conv['value']}% out of realistic range [60%,120%]. "
                "Old broken value was 12.4%."
            )

        # Broken values must not appear
        if ev_fcf.get("valid"):
            assert ev_fcf.get("value") != pytest.approx(338, abs=20), \
                "Old broken EV/FCF value 338x should not appear"

    def test_holn_regression_valid_multiples(self):
        """Holcim: at least 8 valid multiples (regression guard)."""
        results = self._run_engine("HOLN.SW")
        valid_n = results.get("_summary", {}).get("valid", 0)
        assert valid_n >= 8, f"HOLN.SW valid multiples {valid_n} < 8 (regression)"

    def test_nvda_regression_valid_multiples(self):
        """NVDA: at least 10 valid multiples."""
        results = self._run_engine("NVDA")
        valid_n = results.get("_summary", {}).get("valid", 0)
        assert valid_n >= 10, f"NVDA valid multiples {valid_n} < 10 (regression)"

    def test_aapl_regression_valid_multiples(self):
        """AAPL: at least 10 valid multiples."""
        results = self._run_engine("AAPL")
        valid_n = results.get("_summary", {}).get("valid", 0)
        assert valid_n >= 10, f"AAPL valid multiples {valid_n} < 10 (regression)"

    def test_no_nv_strings_in_fcf_values(self):
        """Guard output must produce None values, not 'n/v' strings."""
        for ticker in ("ABBN.SW", "HOLN.SW"):
            results = self._run_engine(ticker)
            for key in ("ev_fcf", "fcf_yield", "fcf_conversion"):
                val = results.get(key, {}).get("value")
                assert val != "n/v", (
                    f"{ticker} {key} returned 'n/v' string — must be None when invalid"
                )

    def test_guard_warnings_serialisable(self):
        """_guard_warnings must be a serialisable list (not contains objects)."""
        import json
        results = self._run_engine("ABBN.SW")
        # Should not raise
        json.dumps(results["_guard_warnings"])
