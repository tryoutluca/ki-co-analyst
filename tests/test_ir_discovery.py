"""
tests/test_ir_discovery.py — Dokumentauswahl und RAG-Kontext der IR-Pipeline (ohne Netzwerk).

Regressionen aus echten Fällen: Roche (Halbjahresbericht als Jahresbericht,
Finance Report nicht erkannt), Givaudan (Protokolle als Jahresbericht),
Sika (Jahr nur zweistellig), Kontext-Kappung (Bilanz/Cashflow abgeschnitten).

    pytest tests/test_ir_discovery.py -v
"""
import sys
import os
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.documents import Document
from langchain_community.embeddings import DeterministicFakeEmbedding
from langchain_community.vectorstores import FAISS

import tools.ir_rag_tool as ir


def _doc(text, filename, year, url=None):
    label = f"{text} {filename} {url or ''}".lower()
    cls = ir._classify_pdf_label(label)
    return {"url": url or f"https://x.com/{filename}", "filename": filename,
            "type": cls[0] if cls else "other", "priority": cls[1] if cls else 99,
            "year": year, "text": text, "format": "pdf", "source": "test"}


class TestClassification:
    def test_halbjahresbericht_is_interim(self):
        assert ir._classify_pdf_label("download halbjahresbericht 2026 hy26d.pdf")[0] == "interim_report"

    def test_finance_report_is_annual(self):
        assert ir._classify_pdf_label("download finance report 2025 fb25e.pdf")[0] == "annual_report"

    def test_integrated_report_and_gcfr(self):
        assert ir._classify_pdf_label(" giv-2025-integrated-report.pdf")[0] == "annual_report"
        assert ir._classify_pdf_label(" giv-2025-gcfr.pdf")[0] == "annual_report"

    def test_geschaeftsbericht_with_umlaut(self):
        assert ir._classify_pdf_label("download geschäftsbericht 2025 ar25d.pdf")[0] == "annual_report"

    def test_transcripts_excluded(self):
        assert ir._classify_pdf_label("transcript giv-transcript-2025-full-year-results.pdf") is None

    def test_quarter_documents_interim(self):
        assert ir._classify_pdf_label("q1 2025 financial information abb-q1-2025-financial-information.pdf")[0] == "interim_report"

    def test_q4_full_year_not_interim(self):
        cls = ir._classify_pdf_label("q4 and full-year 2025 results annual report")
        assert cls[0] == "annual_report"


class TestAnnualSelection:
    def test_best_document_per_year(self):
        docs = [
            _doc("Download Annual Report 2025", "ar25e.pdf", 2025),
            _doc("Download Finance Report 2025", "fb25e.pdf", 2025),
            _doc("Download Geschäftsbericht 2025", "ar25d.pdf", 2025),
            _doc("Download Full-Year 2025 Presentation", "irp260129-a.pdf", 2025),
            _doc("Download Finance Report 2024", "fb24e.pdf", 2024),
        ]
        out = ir._deduplicate_and_spread(docs, max_annual=3, max_latest=0)
        annual = [d["filename"] for d in out if d["period_class"] == "annual"]
        assert annual == ["fb25e.pdf", "fb24e.pdf"]

    def test_wanted_years_one_doc_per_year(self):
        docs = [_doc("Annual Report 2025", "ar25e.pdf", 2025),
                _doc("Finance Report 2025", "fb25e.pdf", 2025),
                _doc("Finance Report 2024", "fb24e.pdf", 2024)]
        out = ir._deduplicate_and_spread(docs, max_latest=0, wanted_years={2025})
        assert [d["filename"] for d in out] == ["fb25e.pdf"]

    def test_english_preferred_over_german(self):
        docs = [_doc("Geschäftsbericht 2025", "ar25d.pdf", 2025),
                _doc("Annual Report 2025", "ar25e.pdf", 2025)]
        out = ir._deduplicate_and_spread(docs, max_latest=0)
        assert out[0]["filename"] == "ar25e.pdf"

    def test_report_preferred_over_presentation_for_interim(self):
        yr = date.today().year
        docs = [_doc(f"Half-Year {yr} Presentation", "irp-a.pdf", yr),
                _doc(f"Half-Year Report {yr}", f"hy{yr % 100}e.pdf", yr)]
        out = ir._deduplicate_and_spread(docs, max_annual=0, max_latest=1)
        assert out[0]["filename"] == f"hy{yr % 100}e.pdf"


class TestHelpers:
    def test_year_from_label(self):
        yr = date.today().year
        assert ir._year_from_label("Annual Report 2024", yr) == 2024
        assert ir._year_from_label(f"glo-ar-{(yr - 1) % 100}-annual-report.pdf", yr) == yr - 1
        assert ir._year_from_label("annual-report.pdf", yr) == 0

    def test_registrable_domain(self):
        assert ir._registrable_domain("library.e.abb.com") == "abb.com"
        assert ir._registrable_domain("www.nestle.com") == "nestle.com"
        assert ir._registrable_domain("www.example.co.uk") == "example.co.uk"

    def test_coverage_insufficient(self):
        cur = date.today().year
        fresh = [{"period_class": "annual", "year": cur - 1}, {"period_class": "annual", "year": cur - 2}]
        stale = [{"period_class": "annual", "year": cur - 4}, {"period_class": "annual", "year": cur - 5}]
        single = [{"period_class": "annual", "year": cur - 1}]
        assert ir._annual_coverage_insufficient(stale)
        assert ir._annual_coverage_insufficient(single)
        if date.today().month >= 4:   # ab April muss der Vorjahresbericht da sein
            assert not ir._annual_coverage_insufficient(fresh)
            # wanted_years-Modus: ein fehlendes Jahr nachladen ist ausreichend
            assert not ir._annual_coverage_insufficient(single, wanted_years={cur - 1})


class TestRagContext:
    def _store(self):
        chunks = []
        for year in (2025, 2024):
            for topic in ("income statement sales operating profit", "balance sheet total assets equity",
                          "cash flow statement free cash flow", "dividend per share proposal"):
                chunks.append(Document(
                    page_content=f"{topic} {year} " + "x" * 1400,
                    metadata={"period_class": "annual", "fiscal_year": year, "page": 1, "source": "r.pdf"},
                ))
        chunks.append(Document(page_content="quarterly H1 sales", metadata={
            "period_class": "quarterly", "fiscal_year": 2026, "page": 1, "source": "q.pdf"}))
        emb = DeterministicFakeEmbedding(size=32)
        return FAISS.from_documents(chunks, emb), emb

    def test_every_year_and_full_chunks(self):
        vs, emb = self._store()
        with patch.object(ir, "_get_emb", return_value=emb):
            ctx = ir._build_rag_context(vs, "annual", char_cap=80_000)
        assert "GESCHÄFTSJAHR 2025" in ctx and "GESCHÄFTSJAHR 2024" in ctx
        assert "x" * 1400 in ctx                       # keine 400-Zeichen-Kürzung
        for topic in ("balance sheet", "cash flow", "dividend"):
            assert topic in ctx
        assert "quarterly H1" not in ctx               # Periodenfilter greift

    def test_no_duplicate_chunks(self):
        vs, emb = self._store()
        with patch.object(ir, "_get_emb", return_value=emb):
            ctx = ir._build_rag_context(vs, "annual", char_cap=80_000)
        assert ctx.count("income statement sales operating profit 2025") == 1
