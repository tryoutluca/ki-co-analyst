"""
agents/news_research.py — Autonome Nachrecherche des News-Agenten.

Das LLM sieht die bereits gesammelte Nachrichtenlage und entscheidet selbst,
ob und wonach es gezielt nachsuchen muss (Tool-Use-Schleife). Der Code setzt
die Leitplanken: Suchbudget, Zeitfenster, und alle Treffer laufen danach durch
die deterministische Filterung der sentiment_engine (Relevanz, Dedup, Gewichte).
"""
from __future__ import annotations

import os
import sys
from datetime import date

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import tavily_search
from tools.sentiment_engine import company_short_name, company_query_name

MAX_SEARCHES = 3
MAX_ROUNDS = 5          # LLM-Aufrufe inkl. Abschluss (und ggf. abgelehntem Abschluss)
RESULTS_PER_SEARCH = 5
MIN_REAL_ITEMS = 3      # darunter ist mindestens eine Suche Pflicht (vom Code erzwungen)


@tool
def search_news(query: str, reason: str) -> str:
    """Sucht gezielt aktuelle News (letzte 12 Monate) zu einer konkreten offenen Frage.

    Args:
        query: Kurze englische Suchanfrage (3-6 Wörter) inkl. Firmenname,
            z.B. "Holcim antitrust investigation".
        reason: Warum diese Suche nötig ist (welche Lücke sie schliesst).
    """
    return ""  # Ausführung erfolgt kontrolliert in run_news_research()


@tool
def finish_research(real_company_items: int, reason: str) -> str:
    """Beendet die Recherche.

    Args:
        real_company_items: Anzahl Meldungen (Meilensteine + News + eigene
            Suchtreffer), die WIRKLICH dieses Unternehmen betreffen — ohne
            Namensvettern und separat börsennotierte Töchter.
        reason: Ein Satz, warum die Nachrichtenlage jetzt ausreicht.
    """
    return ""


RESEARCH_PROMPT = """Du bist Research-Analyst in einem Buy-Side-Team. Vor der eigentlichen \
Sentiment-Analyse prüfst du, ob die gesammelte Nachrichtenlage ausreicht. Du hast das \
Werkzeug search_news (Budget: maximal {max_searches} Suchen).

Suche NUR, wenn mindestens einer dieser Fälle vorliegt:
1. Ein materielles Ereignis wird angerissen, aber Details/Ausgang fehlen \
(z.B. Übernahmeangebot, behördliche Untersuchung, Klage, Gewinnwarnung, Managementabgang, \
Rating-Herabstufung, Produktrückruf, Kapitalerhöhung).
2. Dünne Nachrichtenlage: kaum firmenspezifische Meldungen aus glaubwürdigen Quellen.
3. Ein für dieses Geschäftsmodell zentrales Thema fehlt komplett \
(z.B. Optionality-Play: Finanzierung/Cash-Runway; Bank: Kreditqualität/Regulierung; \
Zykliker: Auftragseingang/Nachfrage).

Suche NICHT nach: Kursbewertungen, Analysten-Kurszielen, allgemeinen Marktberichten \
oder Themen, die bereits abgedeckt sind.

ACHTUNG NAMENSVETTERN: Die Liste ist nur per Namensabgleich vorgefiltert. Prüfe, welche \
Meldungen WIRKLICH dieses Unternehmen betreffen (nicht ein gleichnamiges anderes \
Unternehmen/Produkt oder eine separat börsennotierte Tochter). Beurteile die \
Nachrichtenlage nur anhand der echten Treffer.

PFLICHT-REGEL: Bleiben nach Abzug der Fremdtreffer weniger als 3 echte, \
firmenspezifische Meldungen (Meilensteine + News zusammen), MUSST du mindestens \
eine Suche durchführen — z.B. nach Auftragslage, Ergebnissen oder Guidance.

Regeln:
- Kurze englische Queries (3-6 Wörter), immer mit dem vollen Firmennamen \
(z.B. "Comet Holding", nicht nur "Comet").
- Jede Suche braucht eine konkrete reason.
- Nach jedem Suchergebnis entscheidest du neu, ob eine weitere Suche nötig ist.
- Ist die Lage ausreichend klar (und die Pflicht-Regel erfüllt), rufe finish_research \
auf. Bei guter Datenlage ist sofortiges finish_research ohne Suche ein valides und \
häufig korrektes Ergebnis."""


def _format_situation(
    company: str, ticker: str, sector: str, industry: str, business_model: str,
    news: list[dict], milestones: list[dict], evidence_weight: float, thin: bool,
) -> str:
    lines = [
        f"Datum: {date.today().isoformat()}",
        f"Unternehmen: {company} ({ticker}) | Sektor: {sector} | Industrie: {industry}",
        f"Geschäftsmodell: {business_model}",
        f"Evidenzgewicht der Nachrichtenlage: {evidence_weight:.2f}"
        + (" → DÜNN" if thin else ""),
        "",
        "=== STRATEGISCHE MEILENSTEINE ===",
    ]
    lines += [f"  [{m['id']}] {m.get('published', 'N/A')} | {m.get('source', '')} | {m['headline']}"
              for m in milestones] or ["  (keine)"]
    lines.append("\n=== FIRMEN-NEWS ===")
    lines += [f"  [{n['id']}] {n.get('published', 'N/A')} | {n.get('source', '')} | {n['headline']}"
              for n in news] or ["  (keine)"]
    return "\n".join(lines)


def _format_results(results: list[dict]) -> str:
    if not results:
        return "Keine Treffer."
    return "\n".join(
        f"- {r.get('published', 'N/A')} | {r.get('source', '')} | {r.get('title', '')}\n"
        f"  {(r.get('content') or '')[:200]}"
        for r in results
    )


def run_news_research(
    ticker: str,
    company_name: str,
    sector: str,
    industry: str,
    business_model: str,
    prepared_news: list[dict],
    prepared_milestones: list[dict],
    evidence_weight: float,
    thin_threshold: float,
) -> tuple[list[dict], list[dict]]:
    """Autonome Nachrecherche. Returns (rohe Treffer, research_log).

    research_log-Einträge: {"query", "reason", "results"} je Suche, plus ein
    abschliessender {"decision": ...}-Eintrag mit der Begründung des LLM.
    """
    if not os.getenv("TAVILY_API_KEY"):
        return [], [{"decision": "Nachrecherche übersprungen (TAVILY_API_KEY fehlt)"}]

    short_name = company_short_name(company_name) or ticker
    query_name = company_query_name(company_name) or ticker
    # tool_choice="required": jede Runde endet in einer Suche oder in finish_research —
    # so kann der Code die Pflicht-Regel prüfen, statt Freitext zu interpretieren
    llm = ChatOpenAI(model="gpt-5.4-mini").bind_tools(
        [search_news, finish_research], tool_choice="required",
    )
    messages = [
        SystemMessage(RESEARCH_PROMPT.format(max_searches=MAX_SEARCHES)),
        HumanMessage(_format_situation(
            company_name, ticker, sector, industry, business_model,
            prepared_news, prepared_milestones,
            evidence_weight, evidence_weight < thin_threshold,
        )),
    ]

    results: list[dict] = []
    log: list[dict] = []
    searches = 0

    finished = False
    for _ in range(MAX_ROUNDS):
        ai = llm.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:   # sollte wegen tool_choice="required" nicht vorkommen
            log.append({"decision": "Recherche ohne Abschluss beendet."})
            break

        finish_call = None
        for tc in ai.tool_calls:
            if tc["name"] == "finish_research":
                finish_call = tc
                continue
            if searches >= MAX_SEARCHES:
                messages.append(ToolMessage(
                    "Suchbudget erschöpft — keine weiteren Suchen möglich.",
                    tool_call_id=tc["id"],
                ))
                continue
            query = str(tc["args"].get("query", "")).strip()
            reason = str(tc["args"].get("reason", "")).strip()
            # Leitplanke: Firmenname muss in der Query stehen
            if short_name.lower() not in query.lower():
                query = f"{query_name} {query}"
            searches += 1
            try:
                hits = tavily_search(query, topic="news", time_range="year",
                                     max_results=RESULTS_PER_SEARCH)
            except Exception as e:
                hits = []
                reason += f" [Fehler: {e}]"
            results.extend(hits)
            log.append({"query": query, "reason": reason, "results": len(hits)})
            print(f"      [research] 🔎 \"{query}\" — {reason[:120]} → {len(hits)} Treffer")
            messages.append(ToolMessage(_format_results(hits), tool_call_id=tc["id"]))

        if finish_call:
            args = finish_call["args"]
            try:
                real = int(args.get("real_company_items", 0))
            except (TypeError, ValueError):
                real = 0
            reason = str(args.get("reason", "")).strip()
            # Leitplanke: dünne Lage ohne jede Suche wird nicht akzeptiert
            if real < MIN_REAL_ITEMS and searches == 0:
                log.append({"guardrail": f"Abschluss abgelehnt: nur {real} echte Meldungen, keine Suche"})
                print(f"      [research] ⛔ Abschluss abgelehnt ({real} echte Meldungen < "
                      f"{MIN_REAL_ITEMS}, noch keine Suche)")
                messages.append(ToolMessage(
                    f"Abgelehnt: Nur {real} echte Meldungen (< {MIN_REAL_ITEMS}) und noch keine "
                    "Suche durchgeführt. Führe mindestens eine gezielte Suche durch.",
                    tool_call_id=finish_call["id"],
                ))
            else:
                log.append({"decision": reason or "Recherche abgeschlossen.",
                            "real_company_items": real})
                print(f"      [research] ✓ {real} echte Meldungen — {reason[:140]}")
                finished = True
                break

        if searches >= MAX_SEARCHES:
            log.append({"decision": f"Suchbudget ({MAX_SEARCHES}) ausgeschöpft."})
            finished = True
            break

    if not finished and not any("decision" in e for e in log):
        log.append({"decision": f"Rundenlimit ({MAX_ROUNDS}) erreicht."})
    return results, log
