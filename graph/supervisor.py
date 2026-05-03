from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
from datetime import date
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.fundamental_agent import run_fundamental_agent
from agents.news_agent import run_news_agent
from agents.risk_agent import run_risk_agent
from tools.schemas import SupervisorOutput

load_dotenv()

llm = ChatAnthropic(model="claude-sonnet-4-5")
parser = JsonOutputParser(pydantic_object=SupervisorOutput)

SUPERVISOR_PROMPT = """Du bist der Senior Portfolio Manager und leitende Analyst einer Schweizer
Asset Management Firma. Drei Junior-Analysten haben ihre Spezialanalysen abgeliefert. Deine Aufgabe:

SCHRITT 1 — QUALITÄTSPRÜFUNG (vor der Synthese):
Prüfe aktiv die Konsistenz der drei Analysen:
- Stimmen die Zahlen überein? (z.B. KGV beim Fundamental- und Risk-Agent — flag wenn Differenz >5%)
- Gibt es Widersprüche zwischen den Empfehlungen?
- Sind alle Quellen vollständig und glaubwürdig?
- Hat der Fundamental-Agent die Makro-Risiken aus dem News-Agent berücksichtigt?
- Sind die Conviction Killers des Risk-Agents in der Fundamentalanalyse reflektiert?
Dokumentiere JEDEN Qualitätscheck mit Ergebnis: bestanden/Warnung/fehlgeschlagen

SCHRITT 2 — SYNTHESE nach professionellen Buy-Side Standards:

GEWICHTUNG (dynamisch anpassen):
- Fundamental: 50% Basisgewicht
  → Erhöhe auf 60% wenn Makro neutral und Risk-Argumente schwach
  → Reduziere auf 40% wenn Makro stark negativ ODER Conviction Killers vorhanden
- News/Sentiment: 20% Basisgewicht
  → Erhöhe auf 30% wenn klares Makro-Ereignis (Zinsentscheid, Krieg, Krise)
  → Reduziere auf 10% wenn nur Soft-News ohne operativen Bezug
- Risk/Advocatus: 30% Basisgewicht
  → Erhöhe auf 40% wenn Conviction Killers überzeugend
  → Reduziere auf 20% wenn Gegenargumente schwach oder spekulativ

EMPFEHLUNGS-SKALA (5-stufig — Buy-Side Standard):

  Basis-Schwellenwerte (Upside/Downside zum Price Target):
    KAUFEN         > +15%  UND Conviction hoch
    ÜBERGEWICHTEN  +5% bis +15%  ODER Conviction mittel mit positivem Makro
    HALTEN         -5% bis +5%   ODER widersprüchliche Agenten-Signale
    UNTERGEWICHTEN -15% bis -5%  ODER Conviction niedrig mit negativem Makro
    VERKAUFEN      < -15%  ODER aktive Conviction Killers + negatives Makro

  WICHTIG — Upside ist NICHT alleiniger Faktor:
  Gewichtete Formel:
    Score = (Upside_Pct × 0.40)
           + (Sentiment_Score/10 × 100 × 0.20)
           + (Risk_Adjustment × 0.40)

  Risk_Adjustment:
    Keine Conviction Killers aktiv:     +10
    1 Conviction Killer aktiv:           0
    2+ Conviction Killers aktiv:        -15
    Makro headwind:                      -5
    Makro tailwind:                      +5

  Beispiel bei 11% Upside:
    Keine Conviction Killers + neutrales Makro + Sentiment 6/10:
    Score = (11 × 0.40) + (60 × 0.20) + (10 × 0.40)
           = 4.4 + 12 + 4 = 20.4 → ÜBERGEWICHTEN

    Mit 2 Conviction Killern:
    Score = (11 × 0.40) + (60 × 0.20) + (-15 × 0.40)
           = 4.4 + 12 - 6 = 10.4 → HALTEN (korrekt wegen Risiko)

  Score → Empfehlung Mapping:
    Score > 25:          KAUFEN
    Score 15 bis 25:     ÜBERGEWICHTEN
    Score 5 bis 15:      HALTEN
    Score -5 bis 5:      UNTERGEWICHTEN
    Score < -5:          VERKAUFEN

  CONVICTION LEVEL bei 5-stufiger Skala:
    hoch:    KAUFEN oder VERKAUFEN (klare Richtung)
    mittel:  ÜBERGEWICHTEN oder UNTERGEWICHTEN
    niedrig: HALTEN (maximale Unsicherheit)

CONVICTION LEVEL Regeln:
- hoch: Alle drei Agenten zeigen dieselbe Richtung UND keine Conviction Killers
- mittel: Zwei von drei Agenten einig ODER ein Conviction Killer vorhanden
- niedrig: Widersprüche zwischen Agenten ODER zwei+ Conviction Killers

INVESTMENT CASE Regeln:
- Exakt 3-5 Bulletpoints
- Jeder Punkt: konkrete Zahl + Peer-Vergleich oder historischer Vergleich + Quelle
- Kein Punkt ohne Zahl — "günstige Bewertung" ist NICHT ausreichend
- Letzter Punkt immer: Katalysator der die These auslöst

CONSENSUS ESTIMATES Tabelle:
- 2 historische Jahre (A=Actual) aus Finanzkennzahlen
- 3 Vorwärtsjahre (E=Estimate) aus Konsensschätzungen
- Falls Schätzungen fehlen: markiere als "n/v — Bloomberg/FactSet empfohlen"

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON.
{format_instructions}"""


def _extract(output, key, default=None):
    """Works for both dict and Pydantic model outputs from junior agents."""
    if isinstance(output, dict):
        return output.get(key, default)
    return getattr(output, key, default)


def _build_quality_checks(fundamental_output, news_output, risk_output) -> list[dict]:
    """Pre-flight consistency checks passed to the supervisor as context."""
    checks = []

    # 1. Fair value present
    fv = _extract(fundamental_output, "fair_value_estimate")
    checks.append({
        "check": "Fair Value im Fundamental-Output vorhanden",
        "result": "bestanden" if fv else "fehlgeschlagen",
        "comment": f"fair_value_estimate={fv}" if fv else "Wert fehlt",
    })

    # 2. Sentiment score present
    score = _extract(news_output, "overall_sentiment_score")
    checks.append({
        "check": "Sentiment Score im News-Output vorhanden",
        "result": "bestanden" if score is not None else "fehlgeschlagen",
        "comment": f"overall_sentiment_score={score}" if score is not None else "Wert fehlt",
    })

    # 3. Scenarios probability sum
    scenarios = _extract(risk_output, "scenarios", [])
    if scenarios:
        total = sum(
            s.get("probability_pct", 0) if isinstance(s, dict) else s.probability_pct
            for s in scenarios
        )
        checks.append({
            "check": "Szenario-Wahrscheinlichkeiten summieren auf 100%",
            "result": "bestanden" if total == 100 else "Warnung",
            "comment": f"Summe={total}%" if total != 100 else "OK",
        })
    else:
        checks.append({
            "check": "Szenario-Wahrscheinlichkeiten summieren auf 100%",
            "result": "Warnung",
            "comment": "Keine Szenarien im Risk-Output gefunden",
        })

    # 4. Macro risks reflected check
    macro_ignored = _extract(risk_output, "macro_risks_ignored", [])
    checks.append({
        "check": "Makro-Risiken aus News-Agent in Fundamentalanalyse berücksichtigt",
        "result": "Warnung" if macro_ignored else "bestanden",
        "comment": f"{len(macro_ignored)} ignorierte Makro-Risiken" if macro_ignored else "Keine unberücksichtigten Makro-Risiken",
    })

    # 5. Recommendation direction check
    fund_rec = _extract(fundamental_output, "recommendation", "")
    risk_rec = _extract(risk_output, "original_recommendation", "")
    consistent = fund_rec == risk_rec
    checks.append({
        "check": "Empfehlung konsistent zwischen Fundamental- und Risk-Agent",
        "result": "bestanden" if consistent else "Warnung",
        "comment": f"Fundamental={fund_rec}, Risk={risk_rec}",
    })

    return checks


def synthesize_memo(
    ticker: str,
    fundamental_output,
    news_output,
    risk_output,
) -> dict:
    """
    Führt nur die Supervisor-Synthese durch — Agenten-Outputs bereits vorhanden.
    Wird von app.py genutzt damit die UI jeden Schritt live anzeigen kann.
    """
    quality_checks = _build_quality_checks(fundamental_output, news_output, risk_output)

    macro_indicators = _extract(news_output, "macro_indicators", [])
    industry_factors = _extract(news_output, "industry_factors", [])
    macro_risks_ignored = _extract(risk_output, "macro_risks_ignored", [])
    conviction_killers = _extract(risk_output, "conviction_killers", [])

    macro_context = ""
    if macro_indicators:
        macro_context = "\n### MAKRO-INDIKATOREN (News-Agent):\n"
        for m in macro_indicators:
            if isinstance(m, dict):
                macro_context += f"  • [{m.get('impact_on_company')}] {m.get('indicator')}: {m.get('mechanism')}\n"
            else:
                macro_context += f"  • [{m.impact_on_company}] {m.indicator}: {m.mechanism}\n"

    industry_context = ""
    if industry_factors:
        industry_context = "\n### INDUSTRIE-FAKTOREN (News-Agent):\n"
        for f in industry_factors:
            if isinstance(f, dict):
                industry_context += f"  • [{f.get('direction')}] {f.get('topic')}: {f.get('mechanism')}\n"
            else:
                industry_context += f"  • [{f.direction}] {f.topic}: {f.mechanism}\n"

    risk_context = ""
    if macro_risks_ignored:
        risk_context = "\n### VOM FUNDAMENTAL-AGENT IGNORIERTE MAKRO-RISIKEN:\n"
        for r in macro_risks_ignored:
            risk_context += f"  • {r}\n"

    killer_context = ""
    if conviction_killers:
        killer_context = "\n### CONVICTION KILLERS (Risk-Agent):\n"
        for k in conviction_killers:
            if isinstance(k, dict):
                killer_context += f"  [!]{k.get('description')} → Monitor: {k.get('monitoring_indicator')}\n"
            else:
                killer_context += f"  [!]{k.description} → Monitor: {k.monitoring_indicator}\n"

    quality_context = "\n### QUALITÄTSPRÜFUNG ERGEBNISSE:\n"
    for c in quality_checks:
        quality_context += f"  [{c['result']}] {c['check']}: {c['comment']}\n"

    prompt = ChatPromptTemplate.from_messages([
        ("system", SUPERVISOR_PROMPT),
        ("human", """Synthetisiere das finale Investment Memo für {ticker} ({company}).

## FUNDAMENTAL-ANALYSE (Gewicht: 50%):
{fundamental_json}

## NEWS/SENTIMENT-ANALYSE (Gewicht: 20%):
{news_json}

## RISK/ADVOCATUS-DIABOLI-ANALYSE (Gewicht: 30%):
{risk_json}

{macro_context}
{industry_context}
{risk_context}
{killer_context}
{quality_context}

AUFGABEN:
1. Übernimm die quality_checks aus dem Qualitätsprüfungs-Kontext oben (ergänze ggf.)
2. Baue die valuation_table aus den key_metrics der Fundamentalanalyse
3. Baue consensus_estimates: 2 Jahre Actual aus key_metrics + 3 Jahre Estimate aus consensus_estimates/Finanzkennzahlen
4. Übernimm scenarios aus dem Risk-Agent (Bear/Base/Bull, Summe=100%)
5. Baue macro_ampel mit genau 4 Einträgen: Makro, Branche, Unternehmen, Konkurrenz
6. Übernimm conviction_killers aus dem Risk-Agent
7. Treffe finale Empfehlung mit dynamisch gewichtetem Conviction Level
8. final_reasoning im Format: "Fundamental: [X] | Makro: [Y] | Risk: [Z] | Gewichtetes Fazit: [W]"

Datum heute: {today}
Gib das Ergebnis als JSON zurück."""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker": ticker,
        "company": _extract(fundamental_output, "company", ticker),
        "fundamental_json": json.dumps(fundamental_output, indent=2, ensure_ascii=False),
        "news_json": json.dumps(news_output, indent=2, ensure_ascii=False),
        "risk_json": json.dumps(risk_output, indent=2, ensure_ascii=False),
        "macro_context": macro_context,
        "industry_context": industry_context,
        "risk_context": risk_context,
        "killer_context": killer_context,
        "quality_context": quality_context,
        "today": date.today().isoformat(),
        "format_instructions": parser.get_format_instructions(),
    })

    return result


def run_supervisor(ticker: str) -> dict:
    """
    Orchestriert alle drei Agenten und synthetisiert das finale Investment Memo.

    Ablauf:
    [1/5] Fundamental-Agent
    [2/5] News/Sentiment-Agent
    [3/5] Risk/Advocatus-Diaboli-Agent
    [4/5] Qualitätsprüfung
    [5/5] Supervisor Synthese
    """

    print(f"\n{'='*60}")
    print(f"KI-Co-Portfolio-Manager | Analyse: {ticker}")
    print(f"{'='*60}")

    # ── [1/5] Fundamental-Agent ──────────────────────────────
    print("\n[1/5] Fundamental-Agent läuft...")
    fundamental_output = run_fundamental_agent(ticker)
    print(f"      [OK] Empfehlung: {_extract(fundamental_output, 'recommendation')} | "
          f"Fair Value: {_extract(fundamental_output, 'fair_value_estimate')}")

    # ── [2/5] News-Agent ─────────────────────────────────────
    print("\n[2/5] News/Sentiment-Agent läuft...")
    fundamental_context = (
        f"Empfehlung: {_extract(fundamental_output, 'recommendation')}, "
        f"Fair Value: {_extract(fundamental_output, 'fair_value_estimate')}, "
        f"Bewertung: {_extract(fundamental_output, 'valuation_assessment')}"
    )
    news_output = run_news_agent(ticker, fundamental_context)
    print(f"      [OK] Sentiment: {_extract(news_output, 'overall_sentiment_score')}/10 | "
          f"Outlook: {_extract(news_output, 'short_term_outlook')}")

    # ── [3/5] Risk-Agent ─────────────────────────────────────
    print("\n[3/5] Risk/Advocatus-Diaboli-Agent läuft...")
    risk_output = run_risk_agent(ticker, fundamental_output, news_output)
    scenarios = _extract(risk_output, "scenarios", [])
    bear = next((s for s in scenarios if (s.get("name") if isinstance(s, dict) else s.name) == "Bear Case"), None)
    bear_price = (bear.get("price_target") if isinstance(bear, dict) else bear.price_target) if bear else "N/A"
    print(f"      [OK] Bear-Case Kurs: {bear_price}")

    # ── [4/5] Qualitätsprüfung ───────────────────────────────
    print("\n[4/5] Qualitätsprüfung läuft...")
    quality_checks = _build_quality_checks(fundamental_output, news_output, risk_output)
    warnings = [c for c in quality_checks if c["result"] == "Warnung"]
    failures = [c for c in quality_checks if c["result"] == "fehlgeschlagen"]
    print(f"      [OK] {len(quality_checks)} Checks: "
          f"{len(quality_checks)-len(warnings)-len(failures)} bestanden, "
          f"{len(warnings)} Warnungen, {len(failures)} fehlgeschlagen")

    # ── [5/5] Supervisor Synthese ────────────────────────────
    print("\n[5/5] Supervisor synthetisiert finales Investment Memo...")

    macro_indicators = _extract(news_output, "macro_indicators", [])
    industry_factors = _extract(news_output, "industry_factors", [])
    macro_risks_ignored = _extract(risk_output, "macro_risks_ignored", [])
    conviction_killers = _extract(risk_output, "conviction_killers", [])

    macro_context = ""
    if macro_indicators:
        macro_context = "\n### MAKRO-INDIKATOREN (News-Agent):\n"
        for m in macro_indicators:
            if isinstance(m, dict):
                macro_context += f"  • [{m.get('impact_on_company')}] {m.get('indicator')}: {m.get('mechanism')}\n"
            else:
                macro_context += f"  • [{m.impact_on_company}] {m.indicator}: {m.mechanism}\n"

    industry_context = ""
    if industry_factors:
        industry_context = "\n### INDUSTRIE-FAKTOREN (News-Agent):\n"
        for f in industry_factors:
            if isinstance(f, dict):
                industry_context += f"  • [{f.get('direction')}] {f.get('topic')}: {f.get('mechanism')}\n"
            else:
                industry_context += f"  • [{f.direction}] {f.topic}: {f.mechanism}\n"

    risk_context = ""
    if macro_risks_ignored:
        risk_context = "\n### VOM FUNDAMENTAL-AGENT IGNORIERTE MAKRO-RISIKEN:\n"
        for r in macro_risks_ignored:
            risk_context += f"  • {r}\n"

    killer_context = ""
    if conviction_killers:
        killer_context = "\n### CONVICTION KILLERS (Risk-Agent):\n"
        for k in conviction_killers:
            if isinstance(k, dict):
                killer_context += f"  [!]{k.get('description')} → Monitor: {k.get('monitoring_indicator')}\n"
            else:
                killer_context += f"  [!]{k.description} → Monitor: {k.monitoring_indicator}\n"

    quality_context = "\n### QUALITÄTSPRÜFUNG ERGEBNISSE:\n"
    for c in quality_checks:
        quality_context += f"  [{c['result']}] {c['check']}: {c['comment']}\n"

    prompt = ChatPromptTemplate.from_messages([
        ("system", SUPERVISOR_PROMPT),
        ("human", """Synthetisiere das finale Investment Memo für {ticker} ({company}).

## FUNDAMENTAL-ANALYSE (Gewicht: 50%):
{fundamental_json}

## NEWS/SENTIMENT-ANALYSE (Gewicht: 20%):
{news_json}

## RISK/ADVOCATUS-DIABOLI-ANALYSE (Gewicht: 30%):
{risk_json}

{macro_context}
{industry_context}
{risk_context}
{killer_context}
{quality_context}

AUFGABEN:
1. Übernimm die quality_checks aus dem Qualitätsprüfungs-Kontext oben (ergänze ggf.)
2. Baue die valuation_table aus den key_metrics der Fundamentalanalyse
3. Baue consensus_estimates: 2 Jahre Actual aus key_metrics + 3 Jahre Estimate aus consensus_estimates/Finanzkennzahlen
4. Übernimm scenarios aus dem Risk-Agent (Bear/Base/Bull, Summe=100%)
5. Baue macro_ampel mit genau 4 Einträgen: Makro, Branche, Unternehmen, Konkurrenz
6. Übernimm conviction_killers aus dem Risk-Agent
7. Treffe finale Empfehlung mit dynamisch gewichtetem Conviction Level
8. final_reasoning im Format: "Fundamental: [X] | Makro: [Y] | Risk: [Z] | Gewichtetes Fazit: [W]"

Datum heute: {today}
Gib das Ergebnis als JSON zurück."""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker": ticker,
        "company": _extract(fundamental_output, "company", ticker),
        "fundamental_json": json.dumps(fundamental_output, indent=2, ensure_ascii=False),
        "news_json": json.dumps(news_output, indent=2, ensure_ascii=False),
        "risk_json": json.dumps(risk_output, indent=2, ensure_ascii=False),
        "macro_context": macro_context,
        "industry_context": industry_context,
        "risk_context": risk_context,
        "killer_context": killer_context,
        "quality_context": quality_context,
        "today": date.today().isoformat(),
        "format_instructions": parser.get_format_instructions(),
    })

    print(f"\n{'='*60}")
    print(f"[OK] FINALE EMPFEHLUNG: {result.get('final_recommendation')} | "
          f"Conviction: {result.get('conviction_level')} | "
          f"Price Target: {result.get('price_target')}")
    print(f"{'='*60}\n")

    return result


def format_investment_memo(result: dict) -> str:
    """Wandelt den JSON Output in ein lesbares Investment Memo um."""
    currency = result.get("currency", "")
    memo = f"""
{'='*60}
INVESTMENT MEMO — {result.get('company')} ({result.get('ticker')})
{'='*60}

EMPFEHLUNG:  {result.get('final_recommendation')}
CONVICTION:  {result.get('conviction_level')}
PRICE TARGET: {currency} {result.get('price_target')}
AKT. KURS:   {currency} {result.get('current_price')}
UPSIDE/DOWN: {result.get('upside_downside_pct')}%
DATUM:       {result.get('date')}

{'─'*60}
QUALITÄTSPRÜFUNG (Konsistenz: {result.get('data_consistency_score')}/10)
{'─'*60}
{result.get('consistency_notes')}

{'─'*60}
UNTERNEHMENSBESCHREIBUNG
{'─'*60}
{result.get('company_description')}

{'─'*60}
INVESTMENT CASE
{'─'*60}
{chr(10).join(f'• {p}' for p in result.get('investment_case', []))}

{'─'*60}
SZENARIEN
{'─'*60}
{chr(10).join(f"[{s['name']} {s['probability_pct']}%] Kursziel: {s['price_target']} | {s['key_assumption']}" for s in result.get('scenarios', []))}

{'─'*60}
RISIKEN
{'─'*60}
{chr(10).join(f'• {r}' for r in result.get('key_risks', []))}

{'─'*60}
ADVOCATUS DIABOLI
{'─'*60}
{result.get('advocatus_diaboli_summary')}

{'─'*60}
MONITORING CHECKLIST
{'─'*60}
{chr(10).join(f'□ {c}' for c in result.get('monitoring_checklist', []))}

{'─'*60}
FINALE BEGRÜNDUNG
{'─'*60}
{result.get('final_reasoning')}

{'─'*60}
QUELLEN
{'─'*60}
{chr(10).join(f'- {s}' for s in result.get('sources', []))}

{'='*60}
"""
    return memo


if __name__ == "__main__":
    result = run_supervisor("HOLN.SW")

    with open("output_memo.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    memo = format_investment_memo(result)
    print(memo)

    with open("output_memo.txt", "w", encoding="utf-8") as f:
        f.write(memo)

    print("[OK] Memo gespeichert: output_memo.json & output_memo.txt")
