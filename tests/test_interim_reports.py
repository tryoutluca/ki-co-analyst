"""
tests/test_interim_reports.py — Zwischenberichte & Guidance (ohne Netzwerk/LLM).

Regression Rieter (RIEN.SW, Sept. 2026): "rieter-semi-annual-report-2026-en.pdf" wurde
als Jahresbericht 2026 eingestuft → keine Quartalsextraktion, H1-Zahlen im Jahres-Kontext,
Guidance 2026 (nur im H1-Bericht) ging verloren; ein Halbjahr wäre zudem ×4 annualisiert
und als "Q2" in der DB gelandet.

    pytest tests/test_interim_reports.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.period_classifier import classify_pdf_period
from langchain_core.documents import Document

from tools.ir_rag_tool import _classify_pdf_label, _interim_guidance, _key_figures_chunks
from agents.fundamental_agent import _interim_months
from agents.forward_estimate_agent import _build_guidance_block


class TestSemiAnnualClassification:
    @pytest.mark.parametrize("label", [
        "rieter-semi-annual-report-2026-en.pdf",
        "Semi-Annual Report 2026",
        "semiannual report 2025",
        "Semi annual report H1",
    ])
    def test_pdf_label_is_interim(self, label):
        # Aufrufer übergeben das Label lowercased (Linktext + Dateiname)
        assert _classify_pdf_label(label.lower())[0] == "interim_report"

    def test_period_classifier_h1(self):
        assert classify_pdf_period("rieter-semi-annual-report-2026-en.pdf") == "h1"
        assert classify_pdf_period("Semi-Annual Report 2026") == "h1"

    def test_annual_report_unchanged(self):
        assert _classify_pdf_label("rieter-annual-report-2025-en.pdf")[0] == "annual_report"
        assert classify_pdf_period("Annual Report 2025") == "annual"


class TestKeyFiguresPage:
    KEY_PAGE = ("CHF million 2024 2025 Order intake 725.5 703.4 Sales 859.1 685.1 EBITDA 82.9 13.1 "
                "Operating EBIT 33.9 2.5 EBIT 28.0 -43.9 Net profit 10.4 -63.4 Capital expenditure "
                "-25.6 -15.2 Net debt (-) / net liquidity (+) -230.3 184.3 Dividend per share 2.00 0.00 "
                "Equity ratio 33.7 53.3")

    def _doc(self, text, page, year=2025, pc="annual", src="ar2025.pdf"):
        return Document(page_content=text, metadata={"page": page, "fiscal_year": year,
                                                     "period_class": pc, "source": src})

    def test_finds_key_figures_page(self):
        docs = [self._doc("Letter to shareholders: sales declined, EBIT negative.", 3),
                self._doc(self.KEY_PAGE, 1),
                self._doc("Segment sales EBITDA", 40)]
        out = _key_figures_chunks(docs, "annual", 2025)
        assert [d.metadata["page"] for d in out] == [1]

    def test_other_year_and_late_pages_ignored(self):
        docs = [self._doc(self.KEY_PAGE, 1, year=2024), self._doc(self.KEY_PAGE, 150)]
        assert _key_figures_chunks(docs, "annual", 2025) == []


class TestInterimMonths:
    @pytest.mark.parametrize("period,months", [
        ({"quarter": "H1 2026"}, 6),
        ({"quarter": "9M 2026"}, 9),
        ({"quarter": "Q1 2026"}, 3),
        ({"quarter": "Q2 2026", "period_months": 6}, 6),   # Feld schlägt Label
        ({"quarter": "Halbjahr 2026"}, 6),
    ])
    def test_months(self, period, months):
        assert _interim_months(period) == months


class TestInterimGuidance:
    PERIODS = [{"fiscal_year": 2026, "quarter": "H1 2026"}]

    def test_extracted(self):
        g = _interim_guidance({"guidance_fiscal_year": 2026, "guidance_change": "confirmed",
                               "guidance_current_fy": "Sales of CHF 1.3 to 1.5 billion"}, self.PERIODS)
        assert g == {"fiscal_year": 2026, "statement": "Sales of CHF 1.3 to 1.5 billion",
                     "change": "confirmed", "source": "Zwischenbericht H1 2026"}

    def test_fiscal_year_fallback_from_periods(self):
        g = _interim_guidance({"guidance_current_fy": "0-3% EBIT margin"}, self.PERIODS)
        assert g["fiscal_year"] == 2026

    def test_not_found(self):
        assert _interim_guidance({"guidance_current_fy": "not found"}, self.PERIODS) is None


class TestGuidanceBlock:
    def test_interim_guidance_and_actuals(self):
        f_out = {"_ir_analysis": {
            "guidance_latest": {"fiscal_year": 2026, "statement": "Sales CHF 1.3-1.5 bn",
                                "change": "confirmed", "source": "Zwischenbericht H1 2026"},
            "guidance_2026": "Sales CHF 1.3-1.5 bn [Zwischenbericht H1 2026]",
            "ir_quarterly_periods": [{"quarter": "H1 2026", "revenue_bn": 0.5767, "ebit_bn": -0.0399}],
        }}
        block = _build_guidance_block(f_out)
        assert "Guidance FY2026 (Zwischenbericht H1 2026, confirmed)" in block
        assert "Ist H1 2026: Umsatz 0.5767 Mrd, EBIT -0.0399 Mrd" in block
        assert block.count("1.3-1.5") == 1          # nicht doppelt aus guidance_2026

    def test_empty(self):
        assert "Keine Guidance" in _build_guidance_block({})
