"""
tools/sentiment_engine.py — Deterministische Sentiment-Aggregation.

Analog zur MultiplesEngine: Das LLM liefert nur Einzelurteile (sentiment_impact
pro News, Richtung pro Makro-/Industriefaktor). Filterung, Gewichtung und der
Gesamtscore werden hier reproduzierbar in Python berechnet.

Pipeline:
  1. prepare_milestones() / prepare_company_news() / prepare_research_items()
                             — Junk-/Relevanzfilter → Dedup (auch quellenübergreifend)
                               → Ranking → IDs (M*, N*, R*)
  2. (LLM bewertet jedes Item einzeln, referenziert via id)
  3. aggregate_sentiment()   — Quellen × Recency × Relevanz gewichtet,
                               4-Ebenen-Gewichtung, Shrinkage bei dünner Datenlage
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

# ── Konstanten ────────────────────────────────────────────────────────────────

# 4-Ebenen-Gewichtung (identisch zum NEWS_PROMPT)
COMPONENT_WEIGHTS = {
    "milestones": 0.30,
    "industry":   0.30,
    "macro":      0.25,
    "news":       0.15,
}

LABEL_VALUES = {
    "sehr positiv":  1.0,
    "positiv":       0.5,
    "neutral":       0.0,
    "negativ":      -0.5,
    "sehr negativ": -1.0,
}

DIRECTION_VALUES = {"tailwind": 1.0, "neutral": 0.0, "headwind": -1.0}

RELEVANCE_WEIGHTS = {
    "direkt":         1.0,   # Firma in der Headline
    "erwähnt":        0.5,   # Firma nur im Summary
    "sammelartikel":  0.3,   # Listicle / Vergleich mit vielen Tickern
}

# Quellen-Tiers: Schlüssel werden als Substring im normalisierten Quellnamen
# bzw. in der URL-Domain gesucht.
_SOURCE_TIERS: list[tuple[float, tuple[str, ...]]] = [
    (1.0, ("reuters", "bloomberg", "financial times", "ft.com", "wall street journal",
           "wsj", "dow jones", "barron", "economist", "nzz")),
    (0.8, ("cnbc", "marketwatch", "handelsblatt", "cash.ch", "finews", "awp",
           "investor's business daily", "investors.com", "associated press", "apnews",
           "nikkei", "faz", "sueddeutsche", "les echos", "forbes", "fortune")),
    (0.4, ("zacks", "simply wall", "simplywall", "motley fool", "fool.com",
           "marketbeat", "gurufocus", "insider monkey", "insidermonkey", "tipranks",
           "benzinga", "seeking alpha", "seekingalpha", "investorplace",
           "yahoo", "investing.com", "stocktitan", "globenewswire", "prnewswire",
           "business wire", "businesswire")),
]
DEFAULT_SOURCE_WEIGHT = 0.6   # unbekannt, z.B. Fachpresse

RECENCY_HALF_LIFE_DAYS = 14.0
MAX_AGE_DAYS = 120
MAX_NEWS_ITEMS = 15
DEDUP_JACCARD = 0.6

# Strategische Meilensteine wirken länger nach als Tagesnews: ein 12 Monate
# alter Divestment-Entscheid zählt noch ~25 %, nicht ~6 % (wie bei 90 Tagen)
MILESTONE_HALF_LIFE_DAYS = 180.0
# Meilensteine: gleiches Ereignis wird oft sehr unterschiedlich betitelt
MILESTONE_DEDUP_JACCARD = 0.4
MILESTONE_MAX_AGE_DAYS = 400
MAX_MILESTONES = 8
MAX_RESEARCH_ITEMS = 6

# Kurs-/Übersichtsseiten und Deal-Datenbanken statt echter Meldungen
_JUNK_TITLE = re.compile(
    r"stock price,? news,? quote|stock quote|share price\b|^list of \d+|\bprofile\b.*\bcompetitors\b",
    re.IGNORECASE,
)
_JUNK_DOMAINS = ("tracxn.com", "craft.co", "cbinsights.com", "facebook.com")

# Shrinkage-Prior: Soviel "Evidenzgewicht" entspricht einer neutralen Pseudo-News.
# Zwei positive Zacks-Artikel sollen keinen 9/10-Score erzeugen.
SHRINKAGE_PRIOR = 1.0
# Unterhalb dieses Evidenzgewichts (News + Meilensteine) wird self_confidence gedeckelt
THIN_EVIDENCE_THRESHOLD = 1.5
THIN_EVIDENCE_CONF_CAP = 0.55
DIVERGENCE_WARN_POINTS = 3

_LEGAL_SUFFIXES = {
    "ag", "sa", "se", "nv", "n.v.", "plc", "ltd", "ltd.", "limited", "inc", "inc.",
    "corp", "corp.", "corporation", "co", "co.", "company", "holding", "holdings",
    "group", "gmbh", "spa", "s.a.", "asa", "ab", "oyj", "kgaa", "&",
}
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at",
    "is", "are", "as", "its", "it", "after", "from", "this", "that", "be", "has",
    "der", "die", "das", "und", "mit", "für", "von", "im", "auf",
}
_TICKER_TOKEN = re.compile(r"\b[A-Z]{2,6}\b")
# Börsenkürzel und Akronyme, die in Headlines wie Ticker aussehen
_NON_TICKER_TOKENS = {
    "SWX", "SIX", "NYSE", "LSE", "NASDAQ", "ETR", "XETRA", "OTC", "TSX", "EPA", "AMS",
    "ETF", "ETFS", "CEO", "CFO", "AI", "US", "USA", "EU", "UK", "IPO", "EPS", "Q1", "Q2",
    "Q3", "Q4", "FY", "HY", "DC", "AG", "SA", "PLC",
}
_LISTICLE_PATTERN = re.compile(
    r"\b(\d+\s+(\w+\s+)?(stocks?|etfs?|picks|names)\b|etfs?\b|vs\.?|which (is|stock)|better (value|buy))",
    re.IGNORECASE,
)


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def source_weight(source: str | None, url: str | None = None) -> float:
    """Glaubwürdigkeitsgewicht einer Quelle (Name oder URL-Domain)."""
    haystacks = []
    if source:
        haystacks.append(source.lower())
    if url and url.startswith("http"):
        haystacks.append(urlparse(url).netloc.lower())
    for weight, keys in _SOURCE_TIERS:
        if any(k in h for h in haystacks for k in keys):
            return weight
    return DEFAULT_SOURCE_WEIGHT


def recency_weight(
    published_ts: float | None, now_ts: float, half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Exponentieller Zerfall mit Halbwertszeit *half_life_days*."""
    if not published_ts:
        return 0.5   # unbekanntes Datum: mittleres Gewicht statt Ausschluss
    age_days = max(0.0, (now_ts - published_ts) / 86400)
    return 0.5 ** (age_days / half_life_days)


def company_short_name(company_name: str) -> str:
    """'Roche Holding AG' → 'Roche'; 'Swiss Re AG' → 'Swiss Re' (Originalschreibweise)."""
    tokens = [t for t in re.split(r"[\s,]+", company_name or "") if t]
    while tokens and tokens[-1].lower() in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


_PURE_LEGAL_FORMS = _LEGAL_SUFFIXES - {"holding", "holdings", "group", "company"}


def company_query_name(company_name: str) -> str:
    """Name für Websuchen: nur Rechtsform entfernen, 'Holding'/'Group' behalten.
    'Comet Holding AG' → 'Comet Holding' (statt 'Comet' → Namensvettern);
    'ABB Ltd' → 'ABB'."""
    tokens = [t for t in re.split(r"[\s,]+", company_name or "") if t]
    while len(tokens) > 1 and tokens[-1].lower() in _PURE_LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


def company_name_core(company_name: str) -> str:
    """'Roche Holding AG' → 'roche'; 'Swiss Re AG' → 'swiss re'."""
    return company_short_name(company_name).lower()


def _is_junk(item: dict) -> bool:
    title = item.get("headline") or item.get("title") or ""
    url = item.get("url") or ""
    return bool(_JUNK_TITLE.search(title)) or any(d in url for d in _JUNK_DOMAINS)


def _ticker_root(ticker: str) -> str:
    return (ticker or "").split(".")[0].split("-")[0].upper()


def _mentions(text: str, name_core: str, root: str) -> bool:
    if not text:
        return False
    if name_core and re.search(rf"\b{re.escape(name_core)}\b", text, re.IGNORECASE):
        return True
    # Ticker-Root case-sensitiv, optional mit ADR-Suffix (ABBN → ABBNY)
    if len(root) >= 2 and re.search(rf"\b{re.escape(root)}[A-Z]{{0,2}}\b", text):
        return True
    return False


def classify_relevance(item: dict, ticker: str, company_name: str) -> str | None:
    """'direkt' | 'erwähnt' | 'sammelartikel' | None (irrelevant)."""
    headline = item.get("headline") or item.get("title") or ""
    summary = item.get("summary") or item.get("content") or ""
    name_core = company_name_core(company_name)
    root = _ticker_root(ticker)

    in_headline = _mentions(headline, name_core, root)
    in_summary = _mentions(summary, name_core, root)
    if not (in_headline or in_summary):
        return None

    # Andere Ticker zählen: eigene Firma/Ticker und Börsenkürzel ausgenommen
    own = {root, name_core.upper()}
    other_tickers = {
        t for t in _TICKER_TOKEN.findall(headline)
        if t not in _NON_TICKER_TOKENS and t not in own
        and not (len(root) >= 2 and t.startswith(root))
    }
    if len(other_tickers) >= 3 or _LISTICLE_PATTERN.search(headline):
        return "sammelartikel"
    return "direkt" if in_headline else "erwähnt"


def _headline_tokens(headline: str) -> set[str]:
    words = re.findall(r"[a-zA-ZäöüÄÖÜ0-9]+", (headline or "").lower())
    # Kurze Buchstabe+Ziffer-Tokens behalten: "q1" vs. "q2" unterscheidet Ereignisse
    return {w for w in words
            if (len(w) > 2 or (any(c.isdigit() for c in w) and any(c.isalpha() for c in w)))
            and w not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _item_tokens(it: dict, ignore: frozenset[str] = frozenset()) -> set[str]:
    return _headline_tokens(it.get("headline") or it.get("title") or "") - ignore


def _is_duplicate_of(it: dict, others: list[dict], threshold: float,
                     ignore: frozenset[str]) -> bool:
    toks = _item_tokens(it, ignore)
    url = it.get("url")
    return any(
        (url and url.startswith("http") and url == o.get("url"))
        or _jaccard(toks, _item_tokens(o, ignore)) >= threshold
        for o in others
    )


def dedupe_news(
    items: list[dict],
    exclude: list[dict] | None = None,
    threshold: float = DEDUP_JACCARD,
    company_name: str = "",
) -> list[dict]:
    """Entfernt Near-Duplicates (Headline-Jaccard ≥ *threshold* oder gleiche URL).
    Behalten wird die glaubwürdigere, bei Gleichstand die neuere Version.
    Items, die ein Duplikat eines Eintrags in *exclude* sind (z.B. bereits als
    Meilenstein erfasst), werden ebenfalls entfernt — keine Doppelzählung.
    Firmennamen-Tokens zählen nicht zur Ähnlichkeit (stehen in fast jeder Headline)."""
    ignore = frozenset(_headline_tokens(company_name_core(company_name)))
    ranked = sorted(
        items,
        key=lambda it: (source_weight(it.get("source"), it.get("url")),
                        it.get("published_ts") or 0),
        reverse=True,
    )
    kept: list[dict] = []
    for it in ranked:
        if (_is_duplicate_of(it, kept, threshold, ignore)
                or _is_duplicate_of(it, exclude or [], threshold, ignore)):
            continue
        kept.append(it)
    return kept


def _now_ts(now: datetime | None) -> float:
    return (now or datetime.now(timezone.utc)).timestamp()


# ── Schritt 1: Vorverarbeitung ───────────────────────────────────────────────

def _prepare(
    items: list[dict],
    ticker: str,
    company_name: str,
    *,
    id_prefix: str,
    half_life_days: float,
    max_age_days: float,
    max_items: int,
    now: datetime | None = None,
    exclude: list[dict] | None = None,
    dedup_threshold: float = DEDUP_JACCARD,
) -> tuple[list[dict], dict]:
    """Gemeinsame Pipeline: Junk-/Alters-/Relevanzfilter → Dedup → Top-k → IDs."""
    now_ts = _now_ts(now)
    stats = {"raw": 0, "junk": 0, "irrelevant": 0, "too_old": 0, "duplicates": 0, "used": 0}

    candidates = []
    for it in items or []:
        if not isinstance(it, dict) or it.get("error") or it.get("info"):
            continue
        stats["raw"] += 1
        if _is_junk(it):
            stats["junk"] += 1
            continue
        ts = it.get("published_ts")
        if ts and (now_ts - ts) / 86400 > max_age_days:
            stats["too_old"] += 1
            continue
        rel = classify_relevance(it, ticker, company_name)
        if rel is None:
            stats["irrelevant"] += 1
            continue
        sw = source_weight(it.get("source"), it.get("url"))
        rw = recency_weight(ts, now_ts, half_life_days)
        candidates.append({
            **it,
            "headline": it.get("headline") or it.get("title") or "N/A",
            "relevance": rel,
            "source_weight": sw,
            "recency_weight": round(rw, 4),
            "weight": round(sw * rw * RELEVANCE_WEIGHTS[rel], 4),
        })

    deduped = dedupe_news(candidates, exclude=exclude, threshold=dedup_threshold,
                          company_name=company_name)
    stats["duplicates"] = len(candidates) - len(deduped)

    top = sorted(deduped, key=lambda it: it["weight"], reverse=True)[:max_items]
    top.sort(key=lambda it: it.get("published_ts") or 0, reverse=True)
    for i, it in enumerate(top, 1):
        it["id"] = f"{id_prefix}{i}"
    stats["used"] = len(top)
    return top, stats


def prepare_company_news(
    items: list[dict],
    ticker: str,
    company_name: str,
    now: datetime | None = None,
    max_items: int = MAX_NEWS_ITEMS,
    exclude: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Filtert, dedupliziert und rankt Firmen-News. Vergibt IDs N1..Nk.
    *exclude*: bereits als Meilenstein erfasste Items (werden nicht doppelt gezählt).

    Returns:
        (prepared_items, stats) — Items tragen zusätzlich id, relevance,
        source_weight, recency_weight, weight.
    """
    return _prepare(
        items, ticker, company_name, id_prefix="N",
        half_life_days=RECENCY_HALF_LIFE_DAYS, max_age_days=MAX_AGE_DAYS,
        max_items=max_items, now=now, exclude=exclude,
    )


def prepare_milestones(
    milestones: list[dict],
    ticker: str,
    company_name: str,
    now: datetime | None = None,
    max_items: int = MAX_MILESTONES,
) -> tuple[list[dict], dict]:
    """Strategische Meilensteine (Tavily News): IDs M1..Mk, Halbwertszeit 90 Tage."""
    return _prepare(
        milestones, ticker, company_name, id_prefix="M",
        half_life_days=MILESTONE_HALF_LIFE_DAYS, max_age_days=MILESTONE_MAX_AGE_DAYS,
        max_items=max_items, now=now, dedup_threshold=MILESTONE_DEDUP_JACCARD,
    )


def prepare_research_items(
    items: list[dict],
    ticker: str,
    company_name: str,
    exclude: list[dict],
    now: datetime | None = None,
    max_items: int = MAX_RESEARCH_ITEMS,
) -> tuple[list[dict], dict]:
    """Treffer der autonomen Nachrecherche: IDs R1..Rk. Zählen zur Meilenstein-
    Komponente (Recherche zielt auf materielle Ereignisse), ohne Doppelzählung
    gegenüber bereits vorhandenen News/Meilensteinen."""
    return _prepare(
        items, ticker, company_name, id_prefix="R",
        half_life_days=MILESTONE_HALF_LIFE_DAYS, max_age_days=MILESTONE_MAX_AGE_DAYS,
        max_items=max_items, now=now, exclude=exclude,
        dedup_threshold=MILESTONE_DEDUP_JACCARD,
    )


# ── Schritt 2: Aggregation ───────────────────────────────────────────────────

def _match_rated_items(
    rated: list[dict], prepared: list[dict],
) -> tuple[dict[str, float], list[str]]:
    """Ordnet LLM-bewertete news_items den vorbereiteten Items zu.
    Primär via id, Fallback via URL, dann exakte Headline.

    Returns: (labels {id: wert}, vom LLM als irrelevant markierte ids).
    Die Relevanzprüfung (Namensvettern, Töchter) ist Sprachverständnis und
    liegt deshalb beim LLM — der Regex-Filter ist nur eine grobe Vorauswahl."""
    by_id = {p["id"]: p for p in prepared}
    by_url = {p.get("url"): p for p in prepared if p.get("url", "").startswith("http")}
    by_head = {(p.get("headline") or p.get("title") or "").strip().lower(): p for p in prepared}

    labels: dict[str, float] = {}
    irrelevant: list[str] = []
    for r in rated or []:
        if not isinstance(r, dict):
            continue
        p = (by_id.get(str(r.get("id", "")).strip().upper())
             or by_url.get(r.get("url"))
             or by_head.get((r.get("headline") or "").strip().lower()))
        if not p or p["id"] in labels or p["id"] in irrelevant:
            continue
        if r.get("relevant") is False:
            irrelevant.append(p["id"])
            continue
        val = LABEL_VALUES.get(str(r.get("sentiment_impact", "")).strip().lower())
        if val is not None:
            labels[p["id"]] = val
    return labels, irrelevant


def _weighted_component(prepared: list[dict], labels: dict[str, float]) -> tuple[float | None, float]:
    """Gewichteter Mittelwert mit Shrinkage Richtung 0. Returns (wert, evidenzgewicht)."""
    num = 0.0
    w_sum = 0.0
    for p in prepared:
        if p["id"] in labels:
            num += p["weight"] * labels[p["id"]]
            w_sum += p["weight"]
    if w_sum == 0:
        return None, 0.0
    return num / (w_sum + SHRINKAGE_PRIOR), w_sum


def _direction_component(factors: list, key: str, fallback: str | None) -> float | None:
    vals = []
    for f in factors or []:
        d = f.get(key) if isinstance(f, dict) else getattr(f, key, None)
        if d in DIRECTION_VALUES:
            vals.append(DIRECTION_VALUES[d])
    if vals:
        return sum(vals) / len(vals)
    return DIRECTION_VALUES.get(fallback) if fallback else None


def to_score(x: float) -> int:
    """[-1, 1] → 1..10, neutral (0) → 5 (Supervisor: Sentiment_Component = 0)."""
    return int(max(1, min(10, math.floor(5 + 5 * x + 0.5))))


def aggregate_sentiment(
    llm_output: dict,
    prepared_news: list[dict],
    prepared_milestones: list[dict],
    filter_stats: dict | None = None,
    prepared_research: list[dict] | None = None,
) -> dict:
    """Berechnet den deterministischen Sentiment-Score aus den LLM-Einzelurteilen.
    Recherche-Treffer (R*) zählen zur Meilenstein-Komponente.

    Returns: sentiment_breakdown-Dict (Score, Komponenten, Evidenz, Warnungen).
    """
    structural = prepared_milestones + (prepared_research or [])
    all_items = prepared_news + structural
    rated = llm_output.get("news_items") or []
    labels, irrelevant = _match_rated_items(rated, all_items)

    news_val, news_w = _weighted_component(prepared_news, labels)
    ms_val, ms_w = _weighted_component(structural, labels)
    ind_val = _direction_component(
        llm_output.get("industry_factors"), "direction",
        llm_output.get("overall_industry_direction"),
    )
    mac_val = _direction_component(
        llm_output.get("macro_indicators"), "impact_on_company",
        llm_output.get("overall_macro_direction"),
    )

    components = {"milestones": ms_val, "industry": ind_val, "macro": mac_val, "news": news_val}
    available = {k: v for k, v in components.items() if v is not None}
    if available:
        w_total = sum(COMPONENT_WEIGHTS[k] for k in available)
        effective = {k: COMPONENT_WEIGHTS[k] / w_total for k in available}
        combined = sum(effective[k] * available[k] for k in available)
    else:
        effective, combined = {}, 0.0

    score = to_score(combined)
    evidence = round(news_w + ms_w, 3)

    warnings = []
    llm_score = llm_output.get("overall_sentiment_score")
    if isinstance(llm_score, (int, float)) and abs(llm_score - score) >= DIVERGENCE_WARN_POINTS:
        warnings.append(
            f"LLM-Gesamturteil ({llm_score}/10) weicht stark vom berechneten Score ({score}/10) ab"
        )
    if evidence < THIN_EVIDENCE_THRESHOLD:
        warnings.append(
            f"Dünne Nachrichtenlage (Evidenzgewicht {evidence} < {THIN_EVIDENCE_THRESHOLD})"
        )
    unrated = [p["id"] for p in all_items if p["id"] not in labels and p["id"] not in irrelevant]
    if unrated:
        warnings.append(f"Vom LLM nicht bewertete Items: {', '.join(unrated)}")

    return {
        "score": score,
        "combined_value": round(combined, 3),
        "components": {k: (round(v, 3) if v is not None else None) for k, v in components.items()},
        "effective_weights": {k: round(v, 3) for k, v in effective.items()},
        "evidence_weight": evidence,
        "items_rated": len(labels),
        "excluded_as_irrelevant": irrelevant,
        "research_items": len(prepared_research or []),
        "filter_stats": filter_stats or {},
        "llm_score": llm_score if isinstance(llm_score, (int, float)) else None,
        "warnings": warnings,
    }


def apply_sentiment_engine(
    llm_output: dict,
    prepared_news: list[dict],
    prepared_milestones: list[dict],
    filter_stats: dict | None = None,
    prepared_research: list[dict] | None = None,
) -> dict:
    """Setzt den berechneten Score als offiziellen overall_sentiment_score.
    Das LLM-Urteil bleibt als llm_sentiment_score erhalten."""
    breakdown = aggregate_sentiment(
        llm_output, prepared_news, prepared_milestones, filter_stats, prepared_research,
    )
    out = dict(llm_output)
    out["llm_sentiment_score"] = breakdown["llm_score"]
    out["overall_sentiment_score"] = breakdown["score"]
    out["sentiment_breakdown"] = breakdown

    if breakdown["evidence_weight"] < THIN_EVIDENCE_THRESHOLD:
        conf = out.get("self_confidence")
        if isinstance(conf, (int, float)) and conf > THIN_EVIDENCE_CONF_CAP:
            out["self_confidence"] = THIN_EVIDENCE_CONF_CAP
            out["confidence_rationale"] = (
                (out.get("confidence_rationale") or "")
                + f" [Engine: auf {THIN_EVIDENCE_CONF_CAP} gedeckelt — dünne Nachrichtenlage]"
            ).strip()
    return out
