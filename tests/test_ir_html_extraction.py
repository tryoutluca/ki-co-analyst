"""
tests/test_ir_html_extraction.py — HTML-Extraktion der IR-Pipeline (ohne Netzwerk).

Regression für den SEC-iXBRL-Bug: Fliesstext in <div> statt <p> und Zahlen in
kurzen Tabellenzellen gingen verloren (Apple 10-K: ~10 % des Texts erfasst).

    pytest tests/test_ir_html_extraction.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from tools.ir_rag_tool import (
    _table_to_text,
    _extract_html_blocks,
    _6K_REPORT_DESC,
    _XBRL_REPORT_NAME,
)

SEC_STYLE = """
<html><body>
<div style="display:none"><ix:header>dei:EntityRegistrantName Apple Inc.</ix:header></div>
<div><span>Item 7. Management's Discussion and Analysis of Financial Condition</span></div>
<div><div><span>The Company's net sales increased during 2025 compared to 2024 driven by iPhone and Services.</span></div></div>
<div><span>Net sales by category (dollars in millions):</span></div>
<table>
  <tr><td></td><td>2025</td><td></td><td>2024</td></tr>
  <tr><td>iPhone</td><td>$</td><td>209,586</td><td>$</td><td>201,183</td></tr>
  <tr><td>Total net sales</td><td>$</td><td>416,161</td><td>$</td><td>391,035</td></tr>
  <tr><td>Gross margin percentage</td><td>46.9</td><td>%</td><td>46.2</td><td>%</td></tr>
  <tr><td>Net loss</td><td>(1,234</td><td>)</td></tr>
</table>
</body></html>
"""


def _blocks(html):
    return _extract_html_blocks(BeautifulSoup(html, "html.parser").body)


class TestTableToText:
    def test_rows_keep_numbers_and_merge_symbols(self):
        table = BeautifulSoup(SEC_STYLE, "html.parser").find("table")
        text = _table_to_text(table)
        assert "Total net sales | 416,161 | 391,035" in text
        assert "Gross margin percentage | 46.9% | 46.2%" in text
        assert "Net loss | (1,234)" in text
        assert "$" not in text

    def test_header_row_kept(self):
        table = BeautifulSoup(SEC_STYLE, "html.parser").find("table")
        assert _table_to_text(table).splitlines()[0] == "2025 | 2024"


class TestExtractBlocks:
    def test_div_prose_extracted(self):
        texts = [t for t, _ in _blocks(SEC_STYLE)]
        assert any("net sales increased during 2025" in t for t in texts)

    def test_no_duplicate_from_nested_divs(self):
        texts = [t for t, _ in _blocks(SEC_STYLE)]
        assert sum("net sales increased" in t for t in texts) == 1

    def test_table_is_one_block_with_label(self):
        tables = [t for t, _ in _blocks(SEC_STYLE) if t.startswith("[Tabelle:")]
        assert len(tables) == 1
        assert tables[0].startswith("[Tabelle: Net sales by category (dollars in millions):]")
        assert "416,161" in tables[0]

    def test_table_cells_not_emitted_separately(self):
        texts = [t for t, _ in _blocks(SEC_STYLE)]
        assert not any(t == "Total net sales" for t in texts)

    def test_priority_flag(self):
        prio = {t[:30]: p for t, p in _blocks(SEC_STYLE)}
        assert any(p for t, p in prio.items() if "net sales" in t.lower())

    def test_classic_p_layout_still_works(self):
        html = "<html><body><p>Revenue grew strongly in the fiscal year to CHF 5.2 billion.</p></body></html>"
        assert [t for t, _ in _blocks(html)] == ["Revenue grew strongly in the fiscal year to CHF 5.2 billion."]


class TestSixKSelection:
    def test_report_descriptions(self):
        assert _6K_REPORT_DESC.search("99.1 FINANCIAL REPORT Q2 2026")
        assert _6K_REPORT_DESC.search("Interim financial report")
        assert not _6K_REPORT_DESC.search("EXHIBIT 4.1")
        assert not _6K_REPORT_DESC.search("EX-99")

    def test_xbrl_report_name(self):
        assert _XBRL_REPORT_NAME.match("ubs-20260630.htm")
        assert not _XBRL_REPORT_NAME.match("edgar2q26ubspillar.htm")
        assert not _XBRL_REPORT_NAME.match("f6k_090826.htm")
