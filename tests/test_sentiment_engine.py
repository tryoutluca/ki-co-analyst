"""
tests/test_sentiment_engine.py — Deterministische Sentiment-Aggregation.

    pytest tests/test_sentiment_engine.py -m "not integration" -v
"""
import sys
import os
import pytest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.sentiment_engine import (
    source_weight,
    recency_weight,
    company_name_core,
    classify_relevance,
    dedupe_news,
    prepare_company_news,
    prepare_milestones,
    prepare_research_items,
    company_short_name,
    company_query_name,
    aggregate_sentiment,
    apply_sentiment_engine,
    to_score,
    THIN_EVIDENCE_CONF_CAP,
)
from tools.finance_tools import parse_yf_news_item

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def _news(headline, source="Reuters", days_ago=1, summary="", url=None):
    ts = (NOW - timedelta(days=days_ago)).timestamp()
    return {
        "headline": headline, "title": headline, "summary": summary,
        "source": source, "published_ts": ts, "published": "x",
        "url": url or f"https://example.com/{abs(hash(headline))}",
    }


# ── yfinance-Parsing ─────────────────────────────────────────────────────────

class TestParseYfNews:
    def test_new_nested_format(self):
        item = {"id": "x", "content": {
            "title": "ABB wins order", "summary": "S",
            "pubDate": "2026-09-23T14:31:00Z",
            "provider": {"displayName": "Zacks"},
            "canonicalUrl": {"url": "https://finance.yahoo.com/a"},
        }}
        out = parse_yf_news_item(item)
        assert out["headline"] == "ABB wins order"
        assert out["source"] == "Zacks"
        assert out["url"] == "https://finance.yahoo.com/a"
        assert out["published_ts"] == datetime(2026, 9, 23, 14, 31, tzinfo=timezone.utc).timestamp()

    def test_legacy_flat_format(self):
        item = {"title": "T", "publisher": "Reuters", "link": "https://r.com/x",
                "providerPublishTime": 1_700_000_000}
        out = parse_yf_news_item(item)
        assert out["headline"] == "T"
        assert out["source"] == "Reuters"
        assert out["published_ts"] == 1_700_000_000

    def test_missing_date(self):
        out = parse_yf_news_item({"content": {"title": "T"}})
        assert out["published"] == "N/A"
        assert out["published_ts"] is None


# ── Gewichte ─────────────────────────────────────────────────────────────────

class TestWeights:
    def test_source_tiers(self):
        assert source_weight("Reuters") == 1.0
        assert source_weight("cash.ch") == 0.8
        assert source_weight("Zacks") == 0.4
        assert source_weight("Energy Global") == 0.6

    def test_source_from_url_domain(self):
        assert source_weight("N/A", "https://www.reuters.com/business/x") == 1.0

    def test_recency_half_life(self):
        now = NOW.timestamp()
        assert recency_weight(now, now) == pytest.approx(1.0)
        assert recency_weight(now - 14 * 86400, now) == pytest.approx(0.5)
        assert recency_weight(None, now) == 0.5


# ── Relevanz ─────────────────────────────────────────────────────────────────

class TestRelevance:
    def test_company_name_core_strips_legal_suffix(self):
        assert company_name_core("ABB Ltd") == "abb"
        assert company_name_core("Roche Holding AG") == "roche"
        assert company_name_core("Swiss Re AG") == "swiss re"
        assert company_short_name("Roche Holding AG") == "Roche"

    def test_query_name_keeps_holding(self):
        assert company_query_name("Comet Holding AG") == "Comet Holding"
        assert company_query_name("ABB Ltd") == "ABB"
        assert company_query_name("Apple Inc.") == "Apple"

    def test_direct(self):
        it = _news("Statkraft selects ABB to modernise hydropower plants")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "direkt"

    def test_adr_ticker_matches_root(self):
        it = _news("All You Need to Know About ABBNY Rating Upgrade")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "direkt"

    def test_summary_only(self):
        it = _news("AI power stocks rally", summary="ABB and Eaton gained 3%.")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "erwähnt"

    def test_irrelevant(self):
        it = _news("Watts Water Technologies Q2 Earnings Call Highlights")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") is None

    def test_listicle_many_tickers(self):
        it = _news("Zacks Blog Highlights FANUY, ABBNY, KYCCF, NVDA and ISRG")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "sammelartikel"

    def test_listicle_vs(self):
        it = _news("ENS vs. ABBNY: Which Stock Is the Better Value Option?")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "sammelartikel"

    def test_exchange_codes_not_counted_as_tickers(self):
        it = _news("ABB (SWX:ABBN), Why Is The Stock Getting Fresh Attention?")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "direkt"

    def test_listicle_with_qualifier(self):
        it = _news("Add These 4 GARP Stocks to Your Portfolio", summary="FTNT, ABBNY, EAT")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") == "sammelartikel"

    def test_no_substring_false_positive(self):
        it = _news("Abbott reports strong quarter")
        assert classify_relevance(it, "ABBN.SW", "ABB Ltd") is None


# ── Deduplizierung ───────────────────────────────────────────────────────────

class TestDedupe:
    def test_keeps_higher_tier_duplicate(self):
        a = _news("ABB agrees to buy Rotork in 4 billion pound deal", source="Zacks")
        b = _news("ABB agrees to buy Rotork in £4 billion deal", source="Reuters")
        out = dedupe_news([a, b])
        assert len(out) == 1
        assert out[0]["source"] == "Reuters"

    def test_distinct_headlines_kept(self):
        a = _news("ABB wins Vale automation contract")
        b = _news("ABB invests in LevelTen Energy")
        assert len(dedupe_news([a, b])) == 2


# ── Vorverarbeitung ──────────────────────────────────────────────────────────

class TestPrepare:
    def test_filters_and_assigns_ids(self):
        items = [
            _news("ABB wins Vale automation contract", days_ago=2),
            _news("Watts Water Q2 call highlights"),
            _news("ABB old news", days_ago=200),
            {"error": "boom"},
        ]
        prepared, stats = prepare_company_news(items, "ABBN.SW", "ABB Ltd", now=NOW)
        assert [p["id"] for p in prepared] == ["N1"]
        assert stats == {"raw": 3, "junk": 0, "irrelevant": 1, "too_old": 1, "duplicates": 0, "used": 1}

    def test_max_items_keeps_highest_weight(self):
        items = [_news(f"ABB item number {i} unique{i}", source="Zacks", days_ago=30) for i in range(5)]
        items.append(_news("ABB Reuters exclusive story", source="Reuters", days_ago=1))
        prepared, _ = prepare_company_news(items, "ABBN.SW", "ABB Ltd", now=NOW, max_items=2)
        assert any(p["source"] == "Reuters" for p in prepared)

    def test_milestones_skip_info(self):
        assert prepare_milestones([{"info": "nichts"}], "ABBN.SW", "ABB Ltd", now=NOW)[0] == []
        ms, _ = prepare_milestones(
            [{"title": "ABB CEO change", "url": "https://www.ft.com/x",
              "published_ts": NOW.timestamp()}],
            "ABBN.SW", "ABB Ltd", now=NOW,
        )
        assert ms[0]["id"] == "M1" and ms[0]["weight"] == 1.0

    def test_milestone_recency_half_life_180d(self):
        ms, _ = prepare_milestones(
            [_news("ABB sells robotics division to SoftBank", source="reuters.com", days_ago=180)],
            "ABBN.SW", "ABB Ltd", now=NOW,
        )
        assert ms[0]["recency_weight"] == pytest.approx(0.5, abs=0.01)

    def test_milestone_same_event_different_wording_merged(self):
        ms, stats = prepare_milestones([
            _news("ABB Group to sell ABB Robotics to SoftBank for $5.375B", source="therobotreport.com"),
            _news("ABB to divest Robotics division to SoftBank Group", source="new.abb.com"),
        ], "ABBN.SW", "ABB Ltd", now=NOW)
        assert len(ms) == 1 and stats["duplicates"] == 1

    def test_milestone_different_quarters_not_merged(self):
        ms, _ = prepare_milestones([
            _news("ABB Q2 results"), _news("ABB Q1 results"),
        ], "ABBN.SW", "ABB Ltd", now=NOW)
        assert len(ms) == 2

    def test_milestone_relevance_uses_content(self):
        item = {"title": "Big deal announced", "content": "ABB agreed to acquire Rotork.",
                "url": "https://x.com/a", "source": "x.com"}
        ms, _ = prepare_milestones([item], "ABBN.SW", "ABB Ltd", now=NOW)
        assert ms[0]["relevance"] == "erwähnt"

    def test_junk_quote_pages_removed(self):
        items = [
            _news("ABB Ltd (ABBN.SW) Stock Price, News, Quote & History - Yahoo Finance"),
            _news("List of 48 Acquisitions by ABB (Sep 2026)", url="https://tracxn.com/abb"),
        ]
        ms, stats = prepare_milestones(items, "ABBN.SW", "ABB Ltd", now=NOW)
        assert ms == [] and stats["junk"] == 2

    def test_news_duplicate_of_milestone_excluded(self):
        ms, _ = prepare_milestones(
            [_news("ABB agrees to buy Rotork in 4 billion pound deal", source="reuters.com")],
            "ABBN.SW", "ABB Ltd", now=NOW,
        )
        news, stats = prepare_company_news(
            [_news("ABB agrees to buy Rotork in £4 billion deal", source="Zacks"),
             _news("ABB wins Vale automation contract")],
            "ABBN.SW", "ABB Ltd", now=NOW, exclude=ms,
        )
        assert [n["headline"] for n in news] == ["ABB wins Vale automation contract"]
        assert stats["duplicates"] == 1

    def test_research_items_ids_and_exclude(self):
        existing, _ = prepare_company_news([_news("ABB wins Vale automation contract")],
                                           "ABBN.SW", "ABB Ltd", now=NOW)
        research, _ = prepare_research_items(
            [_news("ABB wins Vale automation contract", url=existing[0]["url"]),
             _news("ABB faces EU antitrust probe")],
            "ABBN.SW", "ABB Ltd", exclude=existing, now=NOW,
        )
        assert [r["id"] for r in research] == ["R1"]
        assert "antitrust" in research[0]["headline"]


# ── Aggregation ──────────────────────────────────────────────────────────────

def _llm(news_items, industry="neutral", macro="neutral", llm_score=5):
    return {
        "overall_sentiment_score": llm_score,
        "news_items": news_items,
        "industry_factors": [{"direction": industry}] * 3,
        "macro_indicators": [{"impact_on_company": macro}] * 3,
        "self_confidence": 0.8,
    }


class TestAggregate:
    def test_score_mapping(self):
        assert to_score(0.0) == 5
        assert to_score(1.0) == 10
        assert to_score(-1.0) == 1

    def test_all_neutral_is_5(self):
        news, _ = prepare_company_news([_news("ABB update")], "ABBN.SW", "ABB Ltd", now=NOW)
        out = aggregate_sentiment(_llm([{"id": "N1", "sentiment_impact": "neutral"}]), news, [])
        assert out["score"] == 5

    def test_deterministic(self):
        news, _ = prepare_company_news([_news("ABB big win")], "ABBN.SW", "ABB Ltd", now=NOW)
        llm = _llm([{"id": "N1", "sentiment_impact": "sehr positiv"}], industry="tailwind")
        assert aggregate_sentiment(llm, news, []) == aggregate_sentiment(llm, news, [])

    def test_shrinkage_thin_evidence(self):
        # Ein einzelner Zacks-Artikel "sehr positiv" darf die News-Komponente nicht auf +1 heben
        news, _ = prepare_company_news([_news("ABB upgrade", source="Zacks")], "ABBN.SW", "ABB Ltd", now=NOW)
        out = aggregate_sentiment(_llm([{"id": "N1", "sentiment_impact": "sehr positiv"}]), news, [])
        assert 0 < out["components"]["news"] < 0.5

    def test_milestones_outweigh_daily_news(self):
        news, _ = prepare_company_news([_news("ABB order win")], "ABBN.SW", "ABB Ltd", now=NOW)
        ms, _ = prepare_milestones([
            _news("ABB CEO resigns", source="reuters.com"),
            _news("ABB antitrust probe opened", source="ft.com"),
        ], "ABBN.SW", "ABB Ltd", now=NOW)
        llm = _llm([
            {"id": "N1", "sentiment_impact": "sehr positiv"},
            {"id": "M1", "sentiment_impact": "sehr negativ"},
            {"id": "M2", "sentiment_impact": "sehr negativ"},
        ])
        assert aggregate_sentiment(llm, news, ms)["score"] < 5

    def test_llm_irrelevant_items_excluded(self):
        ms, _ = prepare_milestones([
            _news("Comet Holding raises guidance", source="reuters.com"),
            _news("Comet Ridge acquires Santos stake", source="reuters.com"),
        ], "COTN.SW", "Comet Holding AG", now=NOW)
        ids = {m["headline"]: m["id"] for m in ms}
        llm = _llm([
            {"id": ids["Comet Holding raises guidance"], "sentiment_impact": "positiv"},
            {"id": ids["Comet Ridge acquires Santos stake"], "sentiment_impact": "sehr negativ",
             "relevant": False},
        ])
        out = aggregate_sentiment(llm, [], ms)
        assert out["excluded_as_irrelevant"] == [ids["Comet Ridge acquires Santos stake"]]
        assert out["components"]["milestones"] > 0
        assert not any("nicht bewertet" in w for w in out["warnings"])

    def test_research_counts_as_milestone_component(self):
        research, _ = prepare_research_items(
            [_news("ABB faces EU antitrust probe", source="reuters.com")],
            "ABBN.SW", "ABB Ltd", exclude=[], now=NOW,
        )
        llm = _llm([{"id": "R1", "sentiment_impact": "sehr negativ"}])
        out = aggregate_sentiment(llm, [], [], prepared_research=research)
        assert out["components"]["milestones"] < 0
        assert out["research_items"] == 1

    def test_matching_fallback_by_url(self):
        news, _ = prepare_company_news([_news("ABB win", url="https://r.com/1")], "ABBN.SW", "ABB Ltd", now=NOW)
        llm = _llm([{"url": "https://r.com/1", "sentiment_impact": "positiv"}])
        assert aggregate_sentiment(llm, news, [])["items_rated"] == 1

    def test_missing_components_renormalised(self):
        out = aggregate_sentiment(
            {"news_items": [], "industry_factors": [], "macro_indicators": [],
             "overall_industry_direction": "tailwind"}, [], []
        )
        assert out["effective_weights"] == {"industry": 1.0}
        assert out["score"] == 10

    def test_divergence_warning(self):
        out = aggregate_sentiment(_llm([], llm_score=9), [], [])
        assert any("weicht stark" in w for w in out["warnings"])


class TestApply:
    def test_overrides_score_and_keeps_llm_score(self):
        out = apply_sentiment_engine(_llm([], industry="headwind", macro="headwind", llm_score=7), [], [])
        assert out["llm_sentiment_score"] == 7
        assert out["overall_sentiment_score"] == 1
        assert "sentiment_breakdown" in out

    def test_thin_evidence_caps_confidence(self):
        out = apply_sentiment_engine(_llm([]), [], [])
        assert out["self_confidence"] == THIN_EVIDENCE_CONF_CAP
