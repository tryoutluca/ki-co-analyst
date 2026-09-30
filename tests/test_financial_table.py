"""
tests/test_financial_table.py — Vollständigkeit der Finanzübersicht (ohne Netzwerk/LLM).

Regressionen aus der Nestlé-Analyse: fehlendes KGV der E-Jahre trotz Kurs+EPS,
EBIT-%/FCF/ROIC der E-Jahre fest auf "-", EBITDA/ROIC älterer Ist-Jahre fehlend,
yfinance-Zeilen nach IR-Zeilen komplett verworfen.

    pytest tests/test_financial_table.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.estimate_revision import complete_forward_rows, apply_estimate_adjustments
from tools.finance_tools import _db_rows_to_hist_dict, _yf_gap_fill_due, _yf_gap_fill_attempts
from agents.fundamental_agent import _roic_from_ir_year

A_ROWS = [
    {"year": f"{y}A", "type": "A", "revenue_bn": rev, "ebitda_bn": eb, "ebit_margin_pct": em,
     "fcf_bn": fcf, "net_debt_bn": nd, "nd_ebitda": round(nd / eb, 2), "roic_pct": roic,
     "eps_adj": eps, "net_income_bn": ni, "dps": dps, "capex_bn": cap}
    for y, rev, eb, em, fcf, nd, roic, eps, ni, dps, cap in [
        (2023, 93.0, 17.5, 17.3, 10.4, 49.6, 14.0, 4.80, 11.2, 3.00, 5.0),
        (2024, 91.4, 18.3, 17.2, 10.7, 56.0, 15.0, 4.77, 10.9, 3.05, 5.2),
        (2025, 89.5, 15.9, 16.1, 9.2, 51.4, 15.2, 4.42, 9.0, 3.10, 4.8),
    ]
]
# E-Zeile wie aus build_forward_rows_from_thesis (Lücken als "-")
E_ROW = {"year": "2026E", "type": "E", "revenue_bn": 92.17, "ebitda_bn": 16.67,
         "ebitda_margin_pct": 18.1, "ebit_margin_pct": "-", "eps_adj": 4.55, "fcf_bn": "-",
         "roic_pct": "-", "pe_ratio": "-", "dps": "-", "nd_ebitda": "-",
         "source": "forward_estimate_agent (Wachstumsthese)"}


class TestCompleteForwardRows:
    def test_pe_from_price_and_eps(self):
        out = complete_forward_rows(A_ROWS + [E_ROW], current_price=77.17)
        assert out[-1]["pe_ratio"] == round(77.17 / 4.55, 1)

    def test_derived_fields_from_3y_median(self):
        e = complete_forward_rows(A_ROWS + [E_ROW], current_price=77.17)[-1]
        assert e["ebit_margin_pct"] == 17.2            # Median 17.3/17.2/16.1
        assert e["roic_pct"] == 15.0                   # Median 14/15/15.2
        assert e["fcf_bn"] == pytest.approx(92.17 * (10.4 / 93.0), rel=1e-3)  # Median-FCF-Marge
        assert e["dps"] == 3.10
        assert e["nd_ebitda"] == round(51.4 / 16.67, 2)
        assert "abgeleitet:" in e["source"]

    def test_existing_values_never_overwritten(self):
        e = {**E_ROW, "ebit_margin_pct": 19.0, "pe_ratio": 20.0}
        out = complete_forward_rows(A_ROWS + [e], current_price=77.17)[-1]
        assert out["ebit_margin_pct"] == 19.0 and out["pe_ratio"] == 20.0

    def test_actual_rows_untouched(self):
        out = complete_forward_rows(A_ROWS + [E_ROW], current_price=77.17)
        assert out[:3] == A_ROWS

    def test_no_price_no_pe(self):
        assert complete_forward_rows(A_ROWS + [E_ROW])[-1]["pe_ratio"] == "-"

    def test_estimate_revision_still_derives(self):
        res = apply_estimate_adjustments({"_full_financials": A_ROWS + [E_ROW]}, [])
        row = res["revised_forward_rows"][0]
        assert row["ebit_margin_pct"] == 17.2 and row["roic_pct"] == 15.0


class TestHistDerivation:
    def test_ebit_and_ebitda_from_margin_and_da(self):
        hist = _db_rows_to_hist_dict([{"fiscal_year": 2021, "revenue_bn": 87.088,
                                       "ebit_margin_pct": 17.4, "da_bn": 3.5, "net_debt_bn": 32.9}])
        y = hist["2021"]
        assert y["ebit_bn"] == round(87.088 * 0.174, 4)
        assert y["ebitda_bn"] == round(87.088 * 0.174 + 3.5, 4)
        assert y["nd_ebitda"] == round(32.9 / y["ebitda_bn"], 2)

    def test_no_invented_ebitda_without_da(self):
        hist = _db_rows_to_hist_dict([{"fiscal_year": 2021, "revenue_bn": 87.0, "ebit_margin_pct": 17.4}])
        assert hist["2021"]["ebitda_bn"] is None


class TestRoicFromIr:
    def test_formula(self):
        yr = {"ebit_bn": 12.277, "tax_rate_pct": 24.6, "total_equity_bn": 30.0, "net_debt_bn": 51.4}
        assert _roic_from_ir_year(yr) == round(12.277 * (1 - 0.246) / 81.4 * 100, 1)

    def test_missing_component(self):
        assert _roic_from_ir_year({"ebit_bn": 12.0, "total_equity_bn": 30.0, "net_debt_bn": 50.0}) is None


class TestYfGapFill:
    def test_due_once_per_day(self):
        _yf_gap_fill_attempts.clear()
        rows = [{"fiscal_year": y, "ebitda_bn": None, "da_bn": None, "total_equity_bn": None, "roic_pct": None}
                for y in (2022, 2023, 2024, 2025)]
        assert _yf_gap_fill_due("TST", rows) is True
        assert _yf_gap_fill_due("TST", rows) is False   # nicht bei jedem Aufruf erneut

    def test_not_due_without_gaps(self):
        _yf_gap_fill_attempts.clear()
        rows = [{"fiscal_year": 2025, "ebitda_bn": 1, "da_bn": 1, "total_equity_bn": 1, "roic_pct": 1}]
        assert _yf_gap_fill_due("TST2", rows) is False


class TestUpsertFillsGaps:
    def test_lower_priority_fills_nulls_only(self, tmp_path, monkeypatch):
        import tools.financial_db as db
        if db._BACKEND != "sqlite":
            pytest.skip("nur SQLite-Backend")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        db.init_db()
        base = {"ticker": "TST.SW", "fiscal_year": 2023, "period_type": "annual", "quarter": None}
        db.upsert_financials([{**base, "source": "ir_pdf", "quality_score": 2.5,
                               "revenue_bn": 93.0, "ebit_margin_pct": 17.3}])
        # yfinance (niedrigere Priorität) danach: darf Umsatz NICHT ändern, aber Lücken füllen
        db.upsert_financials([{**base, "source": "yfinance", "revenue_bn": 99.9,
                               "da_bn": 3.4, "total_equity_bn": 30.0, "roic_pct": 14.1}])
        row = db.get_annual_history("TST.SW", n_years=5)[0]
        assert row["revenue_bn"] == 93.0
        assert row["da_bn"] == 3.4 and row["total_equity_bn"] == 30.0 and row["roic_pct"] == 14.1
        assert row["source"] == "ir_pdf"
