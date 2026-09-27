"""
tests/test_lm_tone.py — Loughran-McDonald-Tonalität (deterministisch, ohne Netzwerk).

    pytest tests/test_lm_tone.py -v
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.lm_tone import (
    load_wordlists,
    analyze_text,
    analyze_by_year,
    build_tone_report,
    compute_ir_tone,
    format_tone_for_prompt,
    is_english,
    tokenize,
    MIN_WORDS,
)

FILLER = "the company and its board of directors reviewed the report for the year with care "


def _doc(extra: str, words: int = MIN_WORDS + 500) -> str:
    """Englischer Fülltext mit eingestreuten Signalwörtern."""
    base_words = len(FILLER.split())
    return (FILLER * (words // base_words)) + " " + extra


def _chunks(year: int, text: str, doc_type: str = "annual_report", period: str = "annual"):
    return [(text, {"period_class": period, "fiscal_year": year, "type": doc_type})]


class TestWordlists:
    def test_categories_loaded(self):
        lists = load_wordlists()
        assert "loss" in lists["negative"]
        assert "uncertain" in lists["uncertainty"]
        assert "litigation" in lists["litigious"]
        assert "achieve" in lists["positive"]
        assert "may" in lists["weak_modal"]

    def test_liability_not_negative(self):
        # Kern-Idee von LM: 'liability' ist im Finanzkontext neutral (Harvard-IV zählt es negativ)
        assert "liability" not in load_wordlists()["negative"]


class TestAnalyzeText:
    def test_counts_categories(self):
        r = analyze_text("the loss was uncertain and litigation may follow")
        assert r["word_count"] == 8
        assert r["negative_pct"] > 0
        assert r["uncertainty_pct"] > 0
        assert r["litigious_pct"] > 0

    def test_negated_positive_not_counted(self):
        assert analyze_text("we did not achieve our goals")["positive_pct"] == 0
        assert analyze_text("we did achieve our goals")["positive_pct"] > 0

    def test_empty(self):
        r = analyze_text("")
        assert r["word_count"] == 0 and r["net_tone"] == 0.0

    def test_language_detection(self):
        assert is_english(tokenize(FILLER * 5))
        assert not is_english(tokenize(
            "der Umsatz und das Ergebnis der Gruppe sind im Jahr gestiegen, die Marge ist für den Konzern stabil " * 5
        ))


class TestByYear:
    def test_groups_annual_only(self):
        chunks = (_chunks(2024, "loss " * 10) + _chunks(2023, "gain " * 10)
                  + _chunks(2025, "quarter", period="quarterly"))
        years = analyze_by_year(chunks)
        assert [y["fiscal_year"] for y in years] == [2024, 2023]

    def test_duplicate_chunks_counted_once(self):
        chunks = _chunks(2024, "loss loss") + _chunks(2024, "loss loss")
        assert analyze_by_year(chunks)[0]["word_count"] == 2


class TestReport:
    def test_worsening_tone_detected(self):
        prior = _doc("uncertain " * 20)
        latest = _doc("uncertain " * 60 + "litigation " * 40 + "loss " * 40)
        rep = build_tone_report(analyze_by_year(_chunks(2025, latest) + _chunks(2024, prior)))
        assert rep["applicable"]
        assert rep["tone_trend"] == "verschlechtert"
        assert rep["comparison"]["latest_year"] == 2025
        assert any("Unsicherheit" in s for s in rep["signals"])

    def test_stable_tone(self):
        text = _doc("uncertain " * 30 + "loss " * 30)
        rep = build_tone_report(analyze_by_year(_chunks(2025, text) + _chunks(2024, text + " x")))
        assert rep["tone_trend"] == "stabil"
        assert rep["signals"] == []

    def test_german_report_not_applicable(self):
        de = "der Umsatz und das Ergebnis der Gruppe sind im Jahr gestiegen " * 1000
        rep = build_tone_report(analyze_by_year(_chunks(2025, de) + _chunks(2024, de)))
        assert not rep["applicable"]
        assert "nicht englisch" in rep["reason"]

    def test_single_year_no_comparison(self):
        rep = build_tone_report(analyze_by_year(_chunks(2025, _doc("loss"))))
        assert rep["applicable"] and rep["comparison"] is None

    def test_comparability_flag_on_doc_type_change(self):
        rep = build_tone_report(analyze_by_year(
            _chunks(2025, _doc("uncertain " * 80), doc_type="presentation")
            + _chunks(2024, _doc("uncertain " * 20))
        ))
        assert rep["comparison"]["comparable"] is False
        assert all("eingeschränkt vergleichbar" in s for s in rep["signals"])


class TestCacheMerge:
    def test_years_accumulate_across_runs(self, tmp_path):
        cache = tmp_path / "lm_tone.json"
        compute_ir_tone(_chunks(2024, _doc("loss " * 10)), cache_path=cache)
        rep = compute_ir_tone(_chunks(2025, _doc("loss " * 50)), cache_path=cache)
        assert [y["fiscal_year"] for y in rep["years"]] == [2025, 2024]
        assert rep["comparison"]["prior_year"] == 2024
        assert len(json.loads(cache.read_text(encoding="utf-8"))) == 2


class TestPromptFormat:
    def test_contains_trend_and_signals(self):
        rep = build_tone_report(analyze_by_year(
            _chunks(2025, _doc("uncertain " * 80)) + _chunks(2024, _doc("uncertain " * 20))
        ))
        txt = format_tone_for_prompt(rep)
        assert "FY2024→FY2025" in txt and "•" in txt

    def test_none(self):
        assert format_tone_for_prompt(None) == ""

    def test_prior_year_without_risk_words_does_not_crash(self):
        rep = build_tone_report(analyze_by_year(
            _chunks(2025, _doc("uncertain " * 20)) + _chunks(2024, _doc(""))
        ))
        assert rep["comparison"]["risk_language_change_pct"] is None
        assert "n/v" in format_tone_for_prompt(rep)
