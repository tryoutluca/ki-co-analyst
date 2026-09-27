"""
tests/test_news_research.py — Leitplanken der autonomen Nachrecherche.

LLM und Tavily werden simuliert; getestet wird die Steuerlogik im Code
(Suchbudget, Pflicht-Regel, Query-Korrektur), nicht das Modellverhalten.

    pytest tests/test_news_research.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage

import agents.news_research as nr


def _search(query, reason="Lücke", i=0):
    return {"name": "search_news", "args": {"query": query, "reason": reason}, "id": f"s{i}"}


def _finish(real, reason="ok", i=0):
    return {"name": "finish_research", "args": {"real_company_items": real, "reason": reason},
            "id": f"f{i}"}


class _FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def bind_tools(self, tools, tool_choice=None):
        return self

    def invoke(self, messages):
        self.calls += 1
        return AIMessage(content="", tool_calls=self.script.pop(0))


def _run(monkeypatch, script):
    fake = _FakeLLM(script)
    queries = []
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr(nr, "ChatOpenAI", lambda **kw: fake)
    monkeypatch.setattr(nr, "tavily_search", lambda q, **kw: queries.append(q) or [
        {"title": f"Comet Holding news {len(queries)}", "url": f"https://x/{len(queries)}",
         "content": "", "published": "2026-09-01", "source": "x"}
    ])
    results, log = nr.run_news_research(
        "COTN.SW", "Comet Holding AG", "Technology", "Semis", "cyclical",
        [], [], evidence_weight=0.2, thin_threshold=1.5,
    )
    return results, log, queries, fake


def test_finish_without_search_accepted_when_enough_items(monkeypatch):
    results, log, queries, fake = _run(monkeypatch, [[_finish(5)]])
    assert queries == [] and fake.calls == 1
    assert log[-1]["real_company_items"] == 5


def test_thin_finish_rejected_until_search(monkeypatch):
    results, log, queries, fake = _run(monkeypatch, [
        [_finish(1)],                                 # abgelehnt
        [_search("Comet Holding orders")],
        [_finish(2, i=1)],                            # jetzt akzeptiert (Suche erfolgt)
    ])
    assert any("guardrail" in e for e in log)
    assert queries == ["Comet Holding orders"]
    assert log[-1]["real_company_items"] == 2
    assert len(results) == 1


def test_search_budget_enforced(monkeypatch):
    results, log, queries, fake = _run(monkeypatch, [
        [_search("Comet Holding a", i=0), _search("Comet Holding b", i=1)],
        [_search("Comet Holding c", i=2), _search("Comet Holding d", i=3)],
    ])
    assert len(queries) == nr.MAX_SEARCHES
    assert "ausgeschöpft" in log[-1]["decision"]


def test_company_name_prepended_to_query(monkeypatch):
    _, _, queries, _ = _run(monkeypatch, [[_search("antitrust probe")], [_finish(3)]])
    assert queries == ["Comet Holding antitrust probe"]


def test_no_api_key_skips(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    results, log = nr.run_news_research(
        "COTN.SW", "Comet Holding AG", "", "", "", [], [], 0.0, 1.5,
    )
    assert results == [] and "übersprungen" in log[0]["decision"]
