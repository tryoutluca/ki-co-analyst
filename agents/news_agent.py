from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import (
    get_recent_news, get_stock_info,
    get_macro_indicators, get_industry_indicators,
    get_strategic_milestones,
)
from tools.schemas import NewsAgentOutput
from tools.sentiment_engine import (
    prepare_company_news, prepare_milestones, prepare_research_items,
    apply_sentiment_engine, THIN_EVIDENCE_THRESHOLD,
)
from agents.news_research import run_news_research

load_dotenv()

llm = ChatOpenAI(model="gpt-5.4-mini")
parser = JsonOutputParser(pydantic_object=NewsAgentOutput)

NEWS_PROMPT = """Du bist ein Senior Buy-Side Analyst. Trenne Signal von Rauschen — strukturelle \
Meilensteine zählen mehr als tagesaktuelle Headlines.

DATENPRIORITÄT (höchste zuerst):
1. Strategische Meilensteine (letzte 12 Monate): CEO/CFO-Wechsel, M&A, Spin-offs, \
   regulatorische Entscheide, strategische Pivots — dauerhafter Einfluss auf den Investment Case
2. Industrie-Dynamiken: sektorale Trends und Wettbewerbsveränderungen
3. Makro-Indikatoren: zyklische Rücken-/Gegenwinde
4. Tagesaktuelle News: nur relevant bei unmittelbarer, materialspezifischer Kursauswirkung

ANALYSE-FRAMEWORK (Gewichtung des Gesamt-Sentiments):
  • Strategische Meilensteine:     30%
  • Industriespezifische Faktoren: 30%
  • Makroökonomische Indikatoren:  25%
  • Tagesaktuelle News:            15%

WICHTIGE GRUNDSÄTZE:
1. Gib für JEDE News die EXAKTE URL und EXAKTE Headline an — fehlt die URL: "nicht verfügbar"
2. Tagge bei jeder News den betroffenen Revenue-Bereich in eckigen Klammern
3. Quell-Bewertung: Bloomberg/Reuters/FT/WSJ = sehr hoch; cash.ch/Handelsblatt = hoch; \
   Yahoo Finance = mittel; Social Media = niedrig
4. Tägliches Rauschen EXPLIZIT von strukturellen Veränderungen trennen
5. Ein strukturell negativer Meilenstein (z.B. CEO-Vakuum, Kartellverfahren) kann gute \
   Fundamentaldaten überstimmen

MAKRO-ANALYSE (macro_indicators):
- Erkläre IMMER den Transmissionsmechanismus: WARUM und über welchen Kanal
- Beispiel: "Steigende SNB-Zinsen → höhere Hypothekenkosten → gedämpfte Bauaktivität \
  → niedrigere Zementnachfrage → Gegenwind für Holcim"

INDUSTRIE-ANALYSE (industry_factors):
- Belege jedes Thema mit der relevantesten Headline aus den Daten
- Bewerte ob sektorale Dynamiken das spezifische Geschäftsmodell stärken oder schwächen

EINZELBEWERTUNG DER NEWS (news_items):
- Jede Firmen-News (ID N1, N2, …), jeder Meilenstein (ID M1, M2, …) und jeder
  Nachrecherche-Treffer (ID R1, R2, …) erhält GENAU EINEN Eintrag in news_items mit
  dem Feld "id" (z.B. "N3", "M1", "R2")
- sentiment_impact bewertet NUR die fundamentale Bedeutung dieser einen Meldung für
  den Investment Case — isoliert, ohne Rücksicht auf andere Meldungen
- Reine Bewertungs-/Kursbetrachtungen ohne neue Information ("Stock looks fairly
  valued", "Is X outperforming?") sind "neutral"
- relevant=false setzen, wenn die Meldung gar nicht dieses Unternehmen betrifft:
  Namensvetter (z.B. "Comet Ridge" oder ein "Comet"-Browser bei Comet Holding),
  separat börsennotierte Tochter (z.B. "ABB India" bei ABB Ltd) oder nur beiläufige
  Erwähnung. Solche Items fliessen NICHT in den Score ein.
- Der Gesamtscore wird aus diesen Einzelurteilen deterministisch vom System berechnet
  (Quellen-, Recency- und Relevanzgewichtung). Präzise Einzelurteile sind daher
  wichtiger als das Gesamturteil.

SENTIMENT-BERECHNUNG:
- overall_sentiment_score (1-10): dein eigenes Gesamturteil gemäss obiger
  4-Ebenen-Gewichtung (dient als Plausibilitätscheck gegen den berechneten Score)
- overall_macro_direction: aggregiertes Urteil über alle Makro-Indikatoren
- overall_industry_direction: aggregiertes Urteil über alle Industrie-Faktoren

sentiment_vs_fundamentals_reasoning MUSS Fundamentaldaten aktiv mit News-Signalen kontrastieren:
"Fundamental: [konkrete Kennzahl + Wert aus dem Kontext, z.B. EV/EBITDA 8x vs Peer 10x] | \
Strategisch: [wichtigster Meilenstein der letzten 12 Monate] | \
Makro: [tailwind/neutral/headwind] | Industrie: [tailwind/neutral/headwind] | \
Fazit: [z.B. Solide Zahlen, aber CEO-Vakuum erhöht Ausführungsrisiko]"

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON. Kein erklärender Text.

{format_instructions}"""


def _format_macro_text(macro_data: dict) -> str:
    lines = ["=== MAKROÖKONOMISCHE DATEN ==="]

    fx = macro_data.get("fx_rates", {})
    if fx:
        lines.append("\n[FX-Kurse (yfinance)]")
        for pair, d in fx.items():
            lines.append(f"  {pair}: {d.get('value')} (5d-Veränderung: {d.get('change_5d_pct')}%, Trend: {d.get('trend')})")

    rates = macro_data.get("rate_proxies", {})
    if rates:
        lines.append("\n[Zins-Proxies (yfinance)]")
        for name, d in rates.items():
            lines.append(f"  {name}: {d.get('value_pct')}% (10d-Änderung: {d.get('change_10d_bp')}bp, Trend: {d.get('trend')})")

    cal = macro_data.get("economic_calendar", [])
    if cal:
        lines.append("\n[Wirtschaftskalender]")
        for e in cal:
            lines.append(f"  {e.get('date')} | {e.get('event')}: Aktuell={e.get('actual')} Schätzung={e.get('estimate')} Vorherig={e.get('previous')}")

    news = macro_data.get("macro_news", [])
    if news:
        lines.append("\n[Makro-News]")
        for i, item in enumerate(news, 1):
            lines.append(f"  {i}. [{item.get('published')}] {item.get('headline')} (Quelle: {item.get('source')})")
            if item.get("summary"):
                lines.append(f"     {item.get('summary')[:150]}")

    return "\n".join(lines)


def _format_industry_text(industry_data: dict) -> str:
    lines = ["=== INDUSTRIESPEZIFISCHE INDIKATOREN ==="]
    lines.append(f"Sektor: {industry_data.get('sector')} | Industrie: {industry_data.get('industry')}")
    lines.append(f"Relevante Themen: {', '.join(industry_data.get('topics', []))}")

    news_per_topic = industry_data.get("news_per_topic", {})
    for topic, articles in news_per_topic.items():
        lines.append(f"\n[{topic}]")
        if articles:
            for a in articles:
                lines.append(f"  • [{a.get('published')}] {a.get('headline')} (Quelle: {a.get('source')})")
        else:
            lines.append("  Keine aktuellen News gefunden.")

    return "\n".join(lines)


_RELEVANCE_LABEL = {
    "direkt":        "Firma in Headline",
    "erwähnt":       "Firma nur im Text erwähnt",
    "sammelartikel": "Sammel-/Vergleichsartikel",
}


def _format_items_text(title: str, items: list, stats: dict, empty_msg: str) -> str:
    """Gemeinsames Format für Meilensteine (M*), Firmen-News (N*) und Nachrecherche (R*)."""
    lines = [
        f"=== {title} ===",
        f"Filter: {stats.get('raw', 0)} roh → {stats.get('junk', 0)} Kurs-/Übersichtsseiten, "
        f"{stats.get('irrelevant', 0)} irrelevant, {stats.get('too_old', 0)} zu alt, "
        f"{stats.get('duplicates', 0)} Duplikate entfernt → {stats.get('used', 0)} verwendet",
    ]
    if not items:
        lines.append(empty_msg)
    for item in items:
        text = item.get("summary") or item.get("content") or "N/A"
        lines.append(
            f"\n[{item['id']}] {item.get('headline', 'N/A')}\n"
            f"   Quelle: {item.get('source', 'N/A')} | Published: {item.get('published', 'N/A')} | "
            f"Relevanz: {_RELEVANCE_LABEL.get(item.get('relevance'), '-')}\n"
            f"   {text[:300]}\n"
            f"   URL: {item.get('url', 'nicht verfügbar')}"
        )
    return "\n".join(lines)


def _evidence_weight(*item_lists: list) -> float:
    return sum(it.get("weight", 0) for items in item_lists for it in items)


def run_news_agent(
    ticker: str,
    fundamental_summary: str = "",
    supervisor_critique: str | None = None,
    business_model_context: dict | None = None,
) -> NewsAgentOutput:
    """Analysiert News, Makro und Industrie-Faktoren — gibt strukturiertes JSON zurück.

    Args:
        business_model_context: Output des Classifier-Agenten (Phase 1).
            Beeinflusst, wie stark Makro/Sektor-Treiber gewichtet werden.
    """

    # Batch 1: News + Stock-Info parallel (Stock-Info zuerst nötig für Swiss-Check)
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_news = ex.submit(get_recent_news.invoke, ticker)
        fut_info = ex.submit(get_stock_info.invoke, ticker)
        try:
            news_yfinance = fut_news.result(timeout=15)
        except Exception as e:
            print(f"      [Timeout/Fehler] get_recent_news: {e}")
            news_yfinance = []
        try:
            stock_info = fut_info.result(timeout=15)
        except Exception as e:
            print(f"      [Timeout/Fehler] get_stock_info: {e}")
            stock_info = {}

    currency     = stock_info.get("currency", "USD")
    sector       = stock_info.get("sector", "N/A")
    industry     = stock_info.get("industry", "N/A")
    company_name = stock_info.get("name", ticker)

    # Batch 2: Makro + Industrie + Meilensteine parallel
    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_macro      = ex.submit(get_macro_indicators.invoke, currency)
        fut_industry   = ex.submit(get_industry_indicators.invoke, {"sector": sector, "industry": industry})
        fut_milestones = ex.submit(get_strategic_milestones.invoke, {"ticker": ticker, "company_name": company_name})
        try:
            macro_data = fut_macro.result(timeout=15)
        except Exception as e:
            print(f"      [Timeout/Fehler] get_macro_indicators: {e}")
            macro_data = {}
        try:
            industry_data = fut_industry.result(timeout=30)
        except Exception as e:
            print(f"      [Timeout/Fehler] get_industry_indicators: {e}")
            industry_data = {}
        try:
            milestones = fut_milestones.result(timeout=30)
        except Exception as e:
            print(f"      [Timeout/Fehler] get_strategic_milestones: {e}")
            milestones = []

    # Deterministische Vorverarbeitung: Relevanzfilter, Dedup, Gewichte, IDs.
    # Meilensteine zuerst — News, die denselben Vorgang melden, zählen nicht doppelt.
    prepared_milestones, ms_stats = prepare_milestones(milestones, ticker, company_name)
    prepared_news, news_stats = prepare_company_news(
        news_yfinance, ticker, company_name, exclude=prepared_milestones,
    )
    print(
        f"      [sentiment_engine] Meilensteine: {ms_stats['raw']} roh → {ms_stats['used']} | "
        f"News: {news_stats['raw']} roh → {news_stats['used']} "
        f"({news_stats['irrelevant']} irrelevant, {news_stats['duplicates']} Duplikate)"
    )

    # Autonome Nachrecherche: LLM entscheidet selbst, ob/wonach gezielt gesucht wird
    bmt = (business_model_context or {}).get("business_model_type", "unbekannt") \
        if isinstance(business_model_context, dict) else "unbekannt"
    research_log: list[dict] = []
    prepared_research: list[dict] = []
    research_stats: dict = {}
    try:
        raw_research, research_log = run_news_research(
            ticker, company_name, sector, industry, bmt,
            prepared_news, prepared_milestones,
            evidence_weight=_evidence_weight(prepared_news, prepared_milestones),
            thin_threshold=THIN_EVIDENCE_THRESHOLD,
        )
        prepared_research, research_stats = prepare_research_items(
            raw_research, ticker, company_name,
            exclude=prepared_milestones + prepared_news,
        )
    except Exception as e:
        print(f"      [research] Fehler, fahre ohne Nachrecherche fort: {e}")
        research_log = [{"decision": f"Nachrecherche fehlgeschlagen: {e}"}]

    first_ms = milestones[0] if milestones and isinstance(milestones[0], dict) else {}
    milestones_text = _format_items_text(
        "STRATEGISCHE MEILENSTEINE (Tavily News, letzte 12 Monate)",
        prepared_milestones, ms_stats,
        first_ms.get("info") or "Keine strategischen Meilensteine gefunden.",
    )
    news_text = _format_items_text(
        "FIRMEN-NEWS (Yahoo Finance, vorgefiltert)",
        prepared_news, news_stats, "Keine firmenspezifischen News gefunden.",
    )
    research_text = ""
    if prepared_research:
        research_text = _format_items_text(
            "GEZIELTE NACHRECHERCHE (autonom; zählt wie Meilensteine)",
            prepared_research, research_stats, "",
        )
    macro_text      = _format_macro_text(macro_data)
    industry_text   = _format_industry_text(industry_data)

    fundamental_context = ""
    if fundamental_summary:
        fundamental_context = f"\n=== KONTEXT FUNDAMENTALANALYSE ===\n{fundamental_summary}\n"

    senior_feedback_block = ""
    if supervisor_critique:
        senior_feedback_block = (
            f"\n⚠️ SENIOR-ANALYST FEEDBACK (HÖCHSTE PRIORITÄT):\n"
            f"{supervisor_critique}\n"
            f"Adressiere dieses Feedback EXPLIZIT in deiner Analyse.\n"
        )

    # ── Phase 1: Klassifikations-Kontext + Confidence ─────────────────────
    classification_block = ""
    if business_model_context and isinstance(business_model_context, dict):
        bmt = business_model_context.get("business_model_type", "unknown")
        guidance_map = {
            "mature_cashflow": (
                "Makro-Sensitivität ist moderat. Fokussiere auf strukturelle Trends "
                "und unternehmensspezifische News, nicht auf Tagesrauschen."
            ),
            "growth_with_revenue": (
                "Sektor-Dynamik und Adoption-Trends sind ENTSCHEIDEND. "
                "Beobachte TAM-Expansion, Wettbewerber-Moves, Regulierungstrends."
            ),
            "optionality_play": (
                "⚠️ Bei Optionality-Plays sind Thematic-Trends und Adoption-Curve "
                "DOMINANT für die These. Tech-Breakthroughs, Regulierungsfortschritt, "
                "Cash-Runway-News verdienen höchste Aufmerksamkeit. "
                "Bewerte explizit, ob sich die ZUKUNFTS-OPTIONALITÄT verbessert oder verschlechtert."
            ),
            "cyclical": (
                "⚠️ ZYKLUS-SENSITIVITÄT ist hoch. Makro-Indikatoren (Zinsen, PMI, "
                "Bauinvestitionen, Industrieproduktion) müssen IM DETAIL mit "
                "Transmissionsmechanismus zum Unternehmen verknüpft werden."
            ),
            "financial_institution": (
                "Zins- und Regulierungs-News sind dominante Treiber. "
                "Beobachte Notenbank-Politik, Basel-Regulierung, Kreditzyklus."
            ),
        }
        guidance = guidance_map.get(bmt, "")
        classification_block = (
            f"\n=== GESCHÄFTSMODELL-KONTEXT (Phase 1 Classifier) ===\n"
            f"Klassifikation: {bmt}\n"
            f"{guidance}\n"
        )

    # ── Phase 2: Makro-Estimate-Adjustments (generisch, alle Treiberklassen) ──
    adjustment_block = (
        "\n=== MAKRO-ESTIMATE-ADJUSTMENTS (Phase 2 — Kernaufgabe) ===\n"
        "Identifiziere 0-4 makroökonomische oder sektorale Treiber, die in den\n"
        "Konsens-Forward-Estimates wahrscheinlich noch NICHT eingepreist sind,\n"
        "und quantifiziere ihren Effekt. Prüfe systematisch ALLE Treiberklassen:\n"
        "  • zinsen: Notenbank-Pfade (SNB/EZB/Fed), Hypothekar-/Kreditzinsen\n"
        "  • waehrung: FX-Bewegungen (CHF-Stärke, USD, EUR) auf Umsatz/Margen\n"
        "  • rohstoffe: Energie, Metalle, Agrar — Input-Kosten oder Absatzpreise\n"
        "  • regulierung: Zölle, Subventionen, Sanktionen, Branchenregulierung\n"
        "  • sektor_nachfrage: Endmarkt-Zyklen (Bau, Auto, AI-Capex, Konsum, Pharma)\n"
        "  • konjunktur: BIP, PMI, Arbeitsmarkt, Konsumklima\n"
        "  • geopolitik: Lieferketten, Handelskonflikte, regionale Risiken\n"
        "  • technologie_adoption: Adoptionskurven, die Nachfrage verschieben\n"
        "\n"
        "STRENGE REGELN für jedes Adjustment:\n"
        "  1. Der Treiber muss KONKRET und belegbar sein (Quelle angeben) —\n"
        "     keine allgemeinen Vermutungen ('Wirtschaft könnte sich abkühlen').\n"
        "  2. Die transmission_chain muss JEDEN Schritt vom Makro-Treiber bis\n"
        "     zur Unternehmens-Kennzahl explizit machen. Beispielformat:\n"
        "     'Treiber → Zwischeneffekt (Beleg) → Sektoreffekt → Firmeneffekt auf Metrik'.\n"
        "  3. delta_pct_low/high ehrlich schätzen — lieber breite Range mit\n"
        "     confidence='niedrig' als falsche Präzision.\n"
        "  4. BEIDE Richtungen prüfen: Rückenwinde (upside) UND Gegenwinde\n"
        "     (downside als negative Deltas). Kein Bias zu positiven Adjustments.\n"
        "  5. Eine LEERE Liste ist ein valides, oft korrektes Ergebnis — wenn\n"
        "     das Makro-Umfeld bereits im Konsens steckt, erfinde nichts.\n"
        "  6. Doppelzählung vermeiden: Wenn ein Treiber bereits explizit in\n"
        "     der Fundamentalanalyse/Guidance berücksichtigt ist, NICHT nochmals\n"
        "     als Adjustment aufführen.\n"
    )

    confidence_block = (
        "\n=== SELBST-CONFIDENCE ===\n"
        "Setze self_confidence (0.0–1.0) basierend auf:\n"
        "  ≥0.80: viele Tier-1-Quellen (Bloomberg/Reuters/FT), klares Makro-Bild, "
        "konkrete Transmissionsmechanismen identifiziert.\n"
        "  0.55–0.80: solide Datenlage, einige Lücken oder widersprüchliche Signale.\n"
        "  <0.55: dünne Newslage, viele Spekulationen, unklarer Makro-Outlook.\n"
        "Begründe in confidence_rationale.\n"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", NEWS_PROMPT),
        ("human", """Analysiere {ticker} ({company}, Sektor: {sector}, Industrie: {industry}, Währung: {currency}).

{milestones_text}

{news_text}

{research_text}

{macro_text}

{industry_text}
{fundamental_context}
{classification_block}
{adjustment_block}
{confidence_block}
{senior_feedback_block}

Erstelle die vollständige Analyse als JSON.
- Gewichte strategische Meilensteine am stärksten (30%)
- macro_indicators: mindestens 3 Einträge basierend auf den Makrodaten
- industry_factors: mindestens 3 Einträge basierend auf den Industrie-News
- estimate_adjustments: 0-4 quantifizierte Treiber nach den Regeln oben
- news_items: genau ein Eintrag pro Firmen-News [N*], Meilenstein [M*] und
  Nachrecherche-Treffer [R*], jeweils mit "id"
- Bei fehlenden URLs: schreibe "nicht verfügbar"
- sentiment_vs_fundamentals_reasoning: kontrastiere aktiv Fundamentaldaten mit News-Signalen"""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker":               ticker,
        "company":              company_name,
        "sector":               sector,
        "industry":             industry,
        "currency":             currency,
        "milestones_text":      milestones_text,
        "news_text":            news_text,
        "research_text":        research_text,
        "macro_text":           macro_text,
        "industry_text":        industry_text,
        "fundamental_context":  fundamental_context,
        "classification_block": classification_block,
        "adjustment_block":     adjustment_block,
        "confidence_block":     confidence_block,
        "senior_feedback_block": senior_feedback_block,
        "format_instructions":  parser.get_format_instructions(),
    })

    result = apply_sentiment_engine(
        result, prepared_news, prepared_milestones,
        filter_stats={"news": news_stats, "milestones": ms_stats, "research": research_stats},
        prepared_research=prepared_research,
    )
    result["research_log"] = research_log
    bd = result["sentiment_breakdown"]
    print(
        f"      [sentiment_engine] Score {bd['score']}/10 (LLM: {bd['llm_score']}) | "
        f"Komponenten: {bd['components']} | Evidenz: {bd['evidence_weight']}"
    )
    for w in bd["warnings"]:
        print(f"      [sentiment_engine] ⚠ {w}")

    return result


if __name__ == "__main__":
    result = run_news_agent("HOLN.SW")
    print(json.dumps(result, indent=2, ensure_ascii=False))
