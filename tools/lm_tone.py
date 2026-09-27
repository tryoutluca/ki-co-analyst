"""
tools/lm_tone.py — Loughran-McDonald-Tonalität der Geschäftsberichte.

Deterministisch, kein LLM: misst pro Geschäftsjahr den Anteil negativer,
unsicherer, rechtlicher (litigious) und einschränkender Wörter im Jahresbericht
und vergleicht das jüngste mit dem Vorjahr. Nicht das Niveau ist das Signal
(Branchen schreiben unterschiedlich), sondern die VERÄNDERUNG im selben
Dokumenttyp derselben Firma (vgl. Cohen/Malloy/Nguyen 2020, "Lazy Prices";
Loughran/McDonald 2011).

Wortlisten: tools/data/lm_wordlists.json (LM Master Dictionary 2018, nur
englisch — deutschsprachige Berichte werden als "nicht anwendbar" markiert).
Lizenz: frei für akademische/Research-Nutzung; kommerzielle Nutzung erfordert
eine Lizenz der Autoren (https://sraf.nd.edu).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_WORDLIST_PATH = Path(__file__).parent / "data" / "lm_wordlists.json"

CATEGORIES = ("negative", "positive", "uncertainty", "litigious",
              "constraining", "weak_modal", "strong_modal")

MIN_WORDS = 5000            # darunter ist ein Jahresvergleich zu verrauscht
MAX_WORDCOUNT_RATIO = 3.0   # grösserer Unterschied → Dokumente vermutlich nicht vergleichbar
NEGATION_WINDOW = 3         # LM 2011: "not good" zählt nicht als positiv
_NEGATIONS = {"no", "not", "none", "neither", "never", "nobody"}

# Relative Veränderung (Jahr vs. Vorjahr), ab der ein Signal ausgegeben wird
SIGNAL_THRESHOLDS = {
    "negative":     15.0,
    "uncertainty":  15.0,
    "litigious":    20.0,
    "constraining": 20.0,
    "weak_modal":   20.0,
}
TREND_THRESHOLD = 10.0      # Risikosprache (neg + unsicher + litigious) ±10% → Trend

_SIGNAL_LABELS = {
    "negative":     "Negative Formulierungen",
    "uncertainty":  "Unsicherheits-Formulierungen",
    "litigious":    "Rechtliche/Litigation-Sprache",
    "constraining": "Einschränkende Formulierungen (Covenants, Auflagen)",
    "weak_modal":   "Vage Modalverben (may, could, might)",
}

_EN_MARKERS = {"the", "and", "of", "to", "for", "is", "on", "that", "with", "by", "are", "was"}
_DE_MARKERS = {"der", "die", "und", "das", "von", "zu", "mit", "für", "den", "des", "ist", "im"}
_TOKEN = re.compile(r"[a-zäöüß]+")


@lru_cache(maxsize=1)
def load_wordlists() -> dict[str, frozenset[str]]:
    data = json.loads(_WORDLIST_PATH.read_text(encoding="utf-8"))
    return {c: frozenset(data[c]) for c in CATEGORIES}


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def is_english(tokens: list[str]) -> bool:
    if not tokens:
        return False
    en = sum(1 for t in tokens if t in _EN_MARKERS)
    de = sum(1 for t in tokens if t in _DE_MARKERS)
    return en / len(tokens) >= 0.06 and en > de


def analyze_text(text: str) -> dict:
    """Tonalitätsprofil eines Textes: Anteile je Kategorie in % aller Wörter."""
    tokens = tokenize(text)
    n = len(tokens)
    result = {"word_count": n, "english": is_english(tokens)}
    if n == 0:
        return {**result, **{f"{c}_pct": 0.0 for c in CATEGORIES}, "net_tone": 0.0}

    lists = load_wordlists()
    counts = dict.fromkeys(CATEGORIES, 0)
    for i, tok in enumerate(tokens):
        for c in CATEGORIES:
            if tok in lists[c]:
                if c == "positive" and _NEGATIONS.intersection(tokens[max(0, i - NEGATION_WINDOW):i]):
                    continue
                counts[c] += 1

    for c in CATEGORIES:
        result[f"{c}_pct"] = round(100 * counts[c] / n, 4)
    pos, neg = counts["positive"], counts["negative"]
    result["net_tone"] = round((pos - neg) / (pos + neg), 4) if pos + neg else 0.0
    return result


def analyze_by_year(chunks: list[tuple[str, dict]]) -> list[dict]:
    """Aggregiert Chunks (text, metadata) der Jahresberichte pro fiscal_year.
    Nur period_class == "annual". Returns Liste, neuestes Jahr zuerst."""
    by_year: dict[int, list[str]] = {}
    doc_types: dict[int, set[str]] = {}
    seen: set[str] = set()
    for text, meta in chunks:
        if meta.get("period_class") != "annual":
            continue
        try:
            year = int(meta.get("fiscal_year") or 0)
        except (TypeError, ValueError):
            continue
        if not year or not text or text in seen:
            continue
        seen.add(text)
        by_year.setdefault(year, []).append(text)
        doc_types.setdefault(year, set()).add(str(meta.get("type") or "unknown"))

    years = []
    for year in sorted(by_year, reverse=True):
        profile = analyze_text("\n".join(by_year[year]))
        years.append({"fiscal_year": year, **profile, "doc_types": sorted(doc_types[year])})
    return years


def _rel_change(new: float, old: float) -> float | None:
    if old <= 0:
        return None
    return round(100 * (new - old) / old, 1)


def build_tone_report(years: list[dict]) -> dict:
    """Vergleicht das jüngste mit dem vorherigen verwertbaren Jahr → Signale + Trend."""
    usable = [y for y in years if y.get("english") and y.get("word_count", 0) >= MIN_WORDS]
    base = {
        "method": "Loughran-McDonald (2018), Anteil an allen Wörtern des Jahresberichts",
        "years": years,
        "comparison": None,
        "tone_trend": None,
        "signals": [],
    }
    if not years:
        return {**base, "applicable": False, "reason": "Keine Jahresberichte im IR-Cache."}
    if not usable:
        non_en = [y["fiscal_year"] for y in years if not y.get("english")]
        reason = (
            f"Jahresberichte nicht englisch ({', '.join(map(str, non_en))}) — "
            "LM-Wörterbuch ist nur für englische Texte validiert."
            if non_en else f"Zu wenig Text (< {MIN_WORDS} Wörter pro Jahr)."
        )
        return {**base, "applicable": False, "reason": reason}
    if len(usable) < 2:
        return {**base, "applicable": True,
                "reason": f"Nur ein verwertbares Jahr ({usable[0]['fiscal_year']}) — kein Vorjahresvergleich möglich."}

    latest, prior = usable[0], usable[1]
    changes = {
        c: _rel_change(latest[f"{c}_pct"], prior[f"{c}_pct"])
        for c in CATEGORIES
    }

    notes = []
    ratio = max(latest["word_count"], prior["word_count"]) / max(1, min(latest["word_count"], prior["word_count"]))
    if ratio > MAX_WORDCOUNT_RATIO:
        notes.append(f"Textumfang unterscheidet sich um Faktor {ratio:.1f}")
    if latest["doc_types"] != prior["doc_types"]:
        notes.append(f"Dokumenttypen verschieden ({latest['doc_types']} vs. {prior['doc_types']})")
    comparable = not notes

    risk_now = sum(latest[f"{c}_pct"] for c in ("negative", "uncertainty", "litigious"))
    risk_before = sum(prior[f"{c}_pct"] for c in ("negative", "uncertainty", "litigious"))
    risk_change = _rel_change(risk_now, risk_before)
    if risk_change is None:
        trend = None
    elif risk_change >= TREND_THRESHOLD:
        trend = "verschlechtert"
    elif risk_change <= -TREND_THRESHOLD:
        trend = "verbessert"
    else:
        trend = "stabil"

    signals = []
    for c, threshold in SIGNAL_THRESHOLDS.items():
        ch = changes.get(c)
        if ch is not None and ch >= threshold:
            signals.append(
                f"{_SIGNAL_LABELS[c]}: {prior[f'{c}_pct']:.2f}% → {latest[f'{c}_pct']:.2f}% "
                f"der Wörter (+{ch:.0f}% ggü. FY{prior['fiscal_year']})"
            )
    if not comparable and signals:
        signals = [s + " [eingeschränkt vergleichbar]" for s in signals]

    return {
        **base,
        "applicable": True,
        "reason": "",
        "comparison": {
            "latest_year": latest["fiscal_year"],
            "prior_year": prior["fiscal_year"],
            "rel_change_pct": changes,
            "risk_language_change_pct": risk_change,
            "net_tone_change": round(latest["net_tone"] - prior["net_tone"], 4),
            "comparable": comparable,
            "comparability_note": "; ".join(notes),
        },
        "tone_trend": trend,
        "signals": signals,
    }


def compute_ir_tone(chunks: list[tuple[str, dict]], cache_path: Path | None = None) -> dict:
    """Berechnet Jahresprofile aus den IR-Chunks, führt sie mit früher
    berechneten Jahren zusammen (der IR-Cache enthält je Lauf evtl. nur die
    fehlenden Jahre) und erstellt den Vergleichsreport."""
    fresh = analyze_by_year(chunks)
    stored: dict[int, dict] = {}
    if cache_path and cache_path.exists():
        try:
            stored = {int(y["fiscal_year"]): y for y in json.loads(cache_path.read_text(encoding="utf-8"))}
        except (ValueError, KeyError, TypeError):
            stored = {}
    for y in fresh:
        stored[y["fiscal_year"]] = y        # neu berechnete Jahre ersetzen alte
    years = sorted(stored.values(), key=lambda y: y["fiscal_year"], reverse=True)
    if cache_path and fresh:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(years, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return build_tone_report(years)


def format_tone_for_prompt(tone: dict | None) -> str:
    """Kompakter Textblock für LLM-Prompts (Risk-Agent)."""
    if not tone:
        return ""
    lines = ["\n=== TONALITÄT GESCHÄFTSBERICHTE (Loughran-McDonald, deterministisch) ==="]
    if not tone.get("applicable"):
        lines.append(f"Nicht anwendbar: {tone.get('reason', '')}")
        return "\n".join(lines)
    for y in tone.get("years", [])[:3]:
        if not y.get("english"):
            continue
        lines.append(
            f"  FY{y['fiscal_year']}: negativ {y['negative_pct']:.2f}% | unsicher {y['uncertainty_pct']:.2f}% | "
            f"litigious {y['litigious_pct']:.2f}% | einschränkend {y['constraining_pct']:.2f}% | "
            f"Netto-Ton {y['net_tone']:+.2f} ({y['word_count']:,} Wörter)"
        )
    comp = tone.get("comparison")
    if comp:
        ch = comp.get("risk_language_change_pct")
        lines.append(
            f"  Trend FY{comp['prior_year']}→FY{comp['latest_year']}: {tone.get('tone_trend') or 'n/v'} "
            f"(Risikosprache {f'{ch:+.1f}%' if ch is not None else 'n/v'})"
        )
        if not comp.get("comparable"):
            lines.append(f"  ⚠ Eingeschränkt vergleichbar: {comp['comparability_note']}")
    elif tone.get("reason"):
        lines.append(f"  {tone['reason']}")
    for s in tone.get("signals", []):
        lines.append(f"  • {s}")
    return "\n".join(lines)
