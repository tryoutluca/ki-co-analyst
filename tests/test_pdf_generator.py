"""
tests/test_pdf_generator.py — PDF-Export des Memos (ohne Netzwerk).

Regressionen: ungültige Farbe "#xd97706" (Export brach immer ab) und
key_risks als Objekte, die still verworfen wurden.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("reportlab")
pypdf = pytest.importorskip("pypdf")

from backend.pdf_generator import generate_memo_pdf


def _text(pdf: bytes) -> str:
    return "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


@pytest.mark.parametrize("rec", ["KAUFEN", "ÜBERGEWICHTEN", "HALTEN", "UNTERGEWICHTEN", "VERKAUFEN"])
def test_pdf_builds_for_every_recommendation(rec):
    pdf = generate_memo_pdf({"ticker": "X", "company": "X AG", "date": "2026-09-26",
                             "final_recommendation": rec})
    assert pdf.startswith(b"%PDF")


def test_object_and_string_risks_rendered():
    pdf = generate_memo_pdf({
        "ticker": "X", "company": "X AG", "date": "2026-09-26", "final_recommendation": "HALTEN",
        "key_risks": [
            {"description": "Zinsanstieg belastet Bau", "affected_segment": "Europa",
             "time_horizon": "mittelfristig", "quantification": "Umsatz -3 %"},
            "Text-Risiko",
        ],
    })
    text = _text(pdf)
    assert "Zinsanstieg belastet Bau" in text
    assert "Text-Risiko" in text
