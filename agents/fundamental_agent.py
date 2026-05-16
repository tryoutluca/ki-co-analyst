from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from dotenv import load_dotenv
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import (
    get_stock_info, get_financial_statements, get_price_history,
    get_cashflow_data, get_historical_multiples, get_peer_financials,
)
from tools.ir_rag_tool import get_ir_analysis, consensus_estimates_from_ir
from tools.schemas import FundamentalAgentOutput
from tools.valuation_engine import build_full_financials
from tools.multiples_engine import MultiplesEngine

load_dotenv()

llm    = ChatOpenAI(model="gpt-5.4-mini")
parser = JsonOutputParser(pydantic_object=FundamentalAgentOutput)

_DEFAULT_MULTIPLES = ["P/E", "EV/EBITDA", "P/B", "ROE"]


def get_relevant_multiples(sector: str) -> list:
    """Fragt das LLM welche Kennzahlen für den Sektor am relevantesten sind."""
    try:
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Du bist ein erfahrener Finanzanalyst. Antworte ausschliesslich mit einem JSON-Array."),
            ("human", (
                "Welche 4-6 Bewertungskennzahlen (Multiples) sind für den Sektor '{sector}' "
                "nach Standard-Finanzanalyse am relevantesten? "
                "Antworte NUR mit einem JSON-Array von Strings, z.B. [\"P/E\", \"EV/EBITDA\"]. "
                "Kein erklärender Text."
            )),
        ])
        chain = prompt | llm | StrOutputParser()
        raw = chain.invoke({"sector": sector})
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return _DEFAULT_MULTIPLES
        multiples = json.loads(raw[start:end])
        if isinstance(multiples, list) and multiples:
            return multiples
    except Exception:
        pass
    return _DEFAULT_MULTIPLES


FUNDAMENTAL_PROMPT = """Du bist ein erfahrener Buy-Side Analyst.

DATENPRIORITÄT (höchste zuerst):
1. IR-Dokumente (geprüfte, bereinigte Zahlen direkt vom Unternehmen)
2. Finnhub (institutionelle Datenqualität)
3. yfinance (gute Abdeckung, gelegentlich verzögert oder bereinigungsbedingt verzerrt)
Wenn Quellen widersprechen: IR-Dokument gewinnt immer.
Differenzen zwischen Quellen immer explizit dokumentieren.

WICHTIGE GRUNDSÄTZE:
1. Verwende sektor-spezifische Kennzahlen
2. Peer-Vergleich und historischer Vergleich sind zentral
3. Gib bei jeder Kennzahl die exakte Datenquelle an (inkl. Seitenzahl bei IR)
4. Keine Halluzinationen — fehlende Daten explizit markieren
5. Investment Case braucht klare Herleitung mit Zahlen
6. Unternehmensbeschreibung: maximal 3 Sätze

KGV-VALIDIERUNG:
- Prüfe das Feld pe_validation in stock_info
- Wenn pe_validation.status = "verzerrt":
  * Verwende trailing P/E NICHT als primäres Multiple
  * Nutze stattdessen Forward P/E und EV/EBITDA als Hauptmultiples
  * Schreibe explizit in investment_case:
    "Trailing KGV nicht aussagekräftig wegen [pe_validation.warning] —
     Forward P/E [Wert]x und EV/EBITDA [Wert]x als primäre Multiples"
- Wenn pe_validation.status = "plausibel": Trailing P/E kann normal verwendet werden

EMPFEHLUNGS-LOGIK FÜR FUNDAMENTAL-AGENT (5-stufige Skala):
  Basiere Empfehlung primär auf DCF Fair Value vs. Kurs:
    > +10%:          KAUFEN
    +5% bis +10%:    ÜBERGEWICHTEN
    -5% bis +5%:     HALTEN
    -10% bis -5%:    UNTERGEWICHTEN
    < -10%:          VERKAUFEN

  Adjustiere um ±1 Stufe wenn:
  - Bewertung mehrheitlich ELEVATED → eine Stufe schlechter
  - Bewertung mehrheitlich DISCOUNT → eine Stufe besser
  - FCF Conversion ausserhalb 70–130% → eine Stufe schlechter

CASHFLOW-ANALYSE:
- Nehme FCF-Kennzahlen immer in key_metrics auf:
  FCF Yield, FCF Conversion, Net Debt/EBITDA, EV/FCF
- FCF Conversion < 70%:  flag als "Potenzielle Ergebnisqualitäts-Warnung (hohe Accruals)"
- FCF Conversion > 130%: flag als "Potenzielle Working-Capital-Anomalie — prüfen"
- Setze ir_verification_recommended=true bei FCF Conversion außerhalb 70–130%
- EV/FCF ist oft aussagekräftiger als KGV — nutze ihn als Cross-Check zur Bewertung

IR-DOKUMENTE PRIORISIERUNG:
- Wenn ir_analysis adjustierte EPS enthält (adjusted_eps_available=true):
  VERWENDE diesen Wert statt yfinance EPS — IR-Zahlen sind primäre Quelle
  Zitiere immer: "(Quelle: IR-Dokument, [adjusted_eps_source])"
- Wenn IR-Zahl >10% von yfinance abweicht: dokumentiere die Diskrepanz explizit
  Beispiel: "IR: EPS 4.52 CHF (Quelle: AR 2024, S. 45) vs. yfinance: 4.18 CHF (+8% Differenz)"
- Nutze revenue_guidance und ebitda_guidance aus ir_analysis für Ausblick-Abschnitt

FORWARD-SCHÄTZUNGEN:

SCHRITT 0 — Estimate-Jahre dynamisch bestimmen:
  Ermittle das letzte abgeschlossene Geschäftsjahr (A) aus den gelieferten Daten:
  → Prüfe IR-Dokumente und yfinance: welches ist das aktuellste Jahr mit vollständigen Istzahlen?
  → Berücksichtige abweichende Geschäftsjahre:
      Standard (Dezember-Abschluss): 2025A → 2026E, 2027E, 2028E
      März-Abschluss (z.B. Take-Two): FY2026A → FY2027E, FY2028E, FY2029E
      Juni-Abschluss:                 FY2026A → FY2027E, FY2028E, FY2029E
  → Das aktuellste A-Jahr ist das Ausgangsjahr für alle Wachstumsberechnungen
  → Berechne immer genau 3 Forward-Jahre ab dem letzten A-Jahr
  → Dokumentiere im Feld "estimate_base_year":
      z.B. "2025A" oder "FY2026A (Abschluss März 2026)"
  WICHTIG: Diese Bestimmung basiert ausschliesslich auf den gelieferten Daten.
  Falls unklar: markiere als "Letztes verfügbares Jahr — Vollständigkeit nicht bestätigt"

- Verwende forward_estimates für die Konsens-Tabelle (E+1/E+2/E+3) in key_metrics,
  wobei E+1/E+2/E+3 die dynamisch bestimmten Forward-Jahre sind
- Alle Jahresreferenzen in key_metrics und investment_case verwenden diese dynamischen Jahre
- Dokumentiere das Konfidenz-Level der Schätzungen (forward_estimates.confidence)
- Nehme den Disclaimer von forward_estimates.disclaimer in die sources-Liste auf

KRITISCH: Antworte AUSSCHLIESSLICH mit validem JSON. Kein erklärender Text.

{format_instructions}"""


def run_fundamental_agent(ticker: str) -> FundamentalAgentOutput:
    """Führt Fundamentalanalyse durch — gibt strukturiertes JSON zurück."""

    print(f"      Hole Unternehmensdaten...")
    stock_info    = get_stock_info.invoke(ticker)
    financials    = get_financial_statements.invoke(ticker)
    price_history = get_price_history.invoke(ticker)

    print(f"      Hole Cashflow-Daten...")
    cashflow_data = get_cashflow_data.invoke(ticker)

    print(f"      Hole historische Multiples...")
    historical_multiples = get_historical_multiples.invoke(ticker)

    print(f"      Analysiere IR-Dokumente (RAG)...")
    ir_analysis = get_ir_analysis.invoke(ticker)

    sector = stock_info.get("sector", "N/A")

    print(f"      Berechne Multiples via MultiplesEngine...")
    try:
        engine = MultiplesEngine.from_ticker(
            ticker           = ticker,
            ir_analysis      = ir_analysis or {},
            financial_source = (
                f"IR-Dokument {ir_analysis.get('document_date', '')}"
                if ir_analysis else "yfinance"
            ),
        )
        all_multiples = engine.compute_all()
        _summary      = all_multiples.get("_summary", {})
        _price_meta   = all_multiples.get("_price_data", {})
        print(
            f"      ✅ MultiplesEngine: "
            f"{_summary.get('valid', 0)}/{_summary.get('total_calculated', 0)} "
            f"Kennzahlen berechnet | "
            f"Kurs: {_price_meta.get('current_price')} "
            f"{_price_meta.get('currency')} (yfinance)"
        )
    except Exception as e:
        print(f"      ⚠ MultiplesEngine Fehler: {e}")
        all_multiples = {}

    print(f"      Berechne Konsensschätzungen (dynamische Vorwärtsjahre)...")
    forward_estimates = consensus_estimates_from_ir(
        ticker,
        ir_analysis,
        historical_multiples,
        sector,
    )
    relevant_multiples = get_relevant_multiples(sector)

    # Build a concise IR context block for the prompt
    ir_context = _format_ir_context(ir_analysis, forward_estimates)

    # Build deterministic multiples context block
    multiples_context = _format_multiples_context(all_multiples)

    prompt = ChatPromptTemplate.from_messages([
        ("system", FUNDAMENTAL_PROMPT),
        ("human", """Analysiere {ticker} ({company}) im Sektor {sector}.

RELEVANTE KENNZAHLEN FÜR DIESEN SEKTOR: {multiples}

UNTERNEHMENSDATEN (Quelle: yfinance — inkl. KGV-Validierung):
{stock_info}

FINANZKENNZAHLEN (Quelle: yfinance):
{financials}

CASHFLOW-DATEN (Quelle: yfinance):
{cashflow_data}

HISTORISCHE MULTIPLES (Quelle: Finnhub):
{historical_multiples}

KURSENTWICKLUNG 3 MONATE (Quelle: yfinance):
{price_history}

{ir_context}

{multiples_context}

AUFGABEN:
1. Erstelle die strukturierte Fundamentalanalyse als JSON.
2. Für cashflow_metrics: übernimm die Rohdaten aus CASHFLOW-DATEN und setze \
ir_verification_recommended=true wenn fcf_conversion_pct außerhalb 70–130%.
3. Wenn pe_validation.status="verzerrt": verwende Forward P/E + EV/EBITDA als primäre Multiples.
4. Wenn IR adjustierte EPS verfügbar: verwende diese als primären EPS-Wert mit Quellenangabe.
5. Markiere fehlende Daten mit "nicht verfügbar — manuelle Ergänzung empfohlen"."""),
    ])

    chain = prompt | llm | parser

    result = chain.invoke({
        "ticker":               ticker,
        "company":              stock_info.get("name", ticker),
        "sector":               sector,
        "multiples":            ", ".join(relevant_multiples),
        "stock_info":           json.dumps(stock_info,           ensure_ascii=False),
        "financials":           json.dumps(financials,           ensure_ascii=False),
        "cashflow_data":        json.dumps(cashflow_data,        ensure_ascii=False),
        "historical_multiples": json.dumps(historical_multiples, ensure_ascii=False),
        "price_history":        json.dumps(price_history,        ensure_ascii=False),
        "ir_context":           ir_context,
        "multiples_context":    multiples_context,
        "format_instructions":  parser.get_format_instructions(),
    })

    # ── MultiplesEngine Post-Processing ──────────────────────────────────────
    # Deterministische Werte überschreiben LLM-Output für Kennzahlen
    if isinstance(result, dict) and all_multiples:
        sector = result.get("sector", "")
        result["valuation_table"] = _build_valuation_table(all_multiples, sector)
        result["all_multiples"]   = all_multiples
        p = all_multiples.get("_price_data", {})
        if p.get("current_price"):
            result["current_price"] = p["current_price"]
        if p.get("market_cap_bn"):
            result["market_cap_bn"] = p["market_cap_bn"]

    # ── Vollständige Finanzübersicht (3A + 3E) ────────────────────────────────
    print(f"      Erstelle vollständige Finanzübersicht...")
    full_financials = build_full_financials(
        ticker, stock_info, financials, cashflow_data,
        ir_analysis, forward_estimates, historical_multiples
    )

    # ── Peer-Vergleich ────────────────────────────────────────────────────────
    print(f"      Erstelle Peer-Vergleich...")
    peer_comparison = get_peer_financials(ticker)

    # ── Valuation Engine Inputs (DCF + Multiples) ─────────────────────────────
    from tools.valuation_engine import run_dcf, build_valuation_table
    valuation = {
        "dcf_inputs":      run_dcf(ir_analysis, financials, cashflow_data, stock_info),
        "valuation_table": build_valuation_table(
            run_dcf(ir_analysis, financials, cashflow_data, stock_info)
        ),
    }

    # Anhängen an result für Supervisor
    if isinstance(result, dict):
        result["_full_financials"]  = full_financials
        result["_peer_comparison"]  = peer_comparison
        result["_valuation_engine"] = valuation

    return result


def _format_multiples_context(all_multiples: dict) -> str:
    """Baut den deterministischen Multiples-Block für den LLM-Prompt."""
    if not all_multiples:
        return ""

    def fmt(key):
        r = all_multiples.get(key, {})
        if r.get("valid"):
            return f"{r['value']} ({r['formula']})"
        return "n/v"

    ev_formula = all_multiples.get("_enterprise_value", {}).get("formula", "n/v")

    return f"""=== DETERMINISTISCH BERECHNETE KENNZAHLEN ===
(Kurs + MarktKap: yfinance | Fundamentaldaten: IR-Dokument)

EV/EBITDA:       {fmt("ev_ebitda")}
EV/EBIT:         {fmt("ev_ebit")}
EV/Sales:        {fmt("ev_sales")}
P/E:             {fmt("pe_ratio")}
P/B:             {fmt("pb_ratio")}
P/FCF:           {fmt("p_fcf")}
Div-Yield:       {fmt("dividend_yield")}
FCF-Yield:       {fmt("fcf_yield")}
ND/EBITDA:       {fmt("nd_ebitda")}
EBITDA-Marge:    {fmt("ebitda_margin")}
EBIT-Marge:      {fmt("ebit_margin")}
FCF-Conversion:  {fmt("fcf_conversion")}
ROE:             {fmt("roe")}
ROIC:            {fmt("roic")}
Umsatz-Wachstum: {fmt("revenue_growth")}
EPS-Wachstum:    {fmt("eps_growth")}

Enterprise Value: {ev_formula}

WICHTIG: Diese Werte sind DETERMINISTISCH BERECHNET.
Das LLM darf sie NICHT ändern oder überschreiben.
Verwende diese Werte direkt für valuation_table."""


def _build_valuation_table(all_multiples: dict, sector: str) -> list:
    """Baut valuation_table deterministisch aus MultiplesEngine-Ergebnissen."""
    sector_lower = sector.lower()

    if any(w in sector_lower for w in ["bank", "versicher", "financ"]):
        primary = [("P/B", "pb_ratio"), ("ROE", "roe"), ("P/E", "pe_ratio")]
    elif any(w in sector_lower for w in ["immobil", "reit", "real estate"]):
        primary = [("EV/EBITDA", "ev_ebitda"), ("Div-Yield", "dividend_yield"), ("P/B", "pb_ratio")]
    elif any(w in sector_lower for w in ["tech", "software", "saas"]):
        primary = [("EV/Sales", "ev_sales"), ("EV/EBITDA", "ev_ebitda"), ("P/FCF", "p_fcf")]
    else:
        primary = [
            ("EV/EBITDA", "ev_ebitda"),
            ("P/E",       "pe_ratio"),
            ("EV/Sales",  "ev_sales"),
            ("P/FCF",     "p_fcf"),
            ("Div-Yield", "dividend_yield"),
        ]

    table = []
    for label, key in primary:
        m = all_multiples.get(key, {})
        if m.get("valid"):
            table.append({
                "metric":             label,
                "current_value":      str(m["value"]),
                "peer_average":       "n/v",
                "historical_average": "n/v",
                "assessment":         "FAIR",
                "calculation":        m["formula"],
                "source":             m["source"],
            })
    return table


def _format_ir_context(ir_analysis: dict, forward_estimates: dict) -> str:
    """Formats IR analysis and forward estimates as a readable prompt block."""
    lines = ["=== IR-DOKUMENTE & FORWARD-SCHÄTZUNGEN ==="]

    if ir_analysis.get("error"):
        lines.append(f"IR-Analyse: Nicht verfügbar ({ir_analysis['error']})")
    else:
        sources = ir_analysis.get("ir_sources", [])
        lines.append(f"IR-Quellen: {', '.join(sources) if sources else 'keine'}")
        lines.append(f"Datenqualität: {ir_analysis.get('data_quality', 'n/v')}")

        # EPS
        adj_eps = ir_analysis.get("adjusted_eps", "not found")
        if adj_eps != "not found":
            lines.append(
                f"Adjusted EPS: {adj_eps} "
                f"(Quelle: IR-Dokument, {ir_analysis.get('adjusted_eps_note', 'n/v')})"
            )
        else:
            lines.append("Adjusted EPS: nicht gefunden in IR-Dokumenten")

        # FCF
        fcf = ir_analysis.get("free_cashflow_bn", "not found")
        fcf_ccy = ir_analysis.get("free_cashflow_currency", "")
        lines.append(
            f"FCF (IR): {fcf} Mrd. {fcf_ccy} ({ir_analysis.get('free_cashflow_note', 'n/v')})"
        )

        # Revenue + margins
        lines.append(f"Umsatz (IR): {ir_analysis.get('revenue_bn', 'not found')} Mrd. "
                     f"{ir_analysis.get('revenue_currency', '')}")
        lines.append(f"EBITDA-Marge (IR): {ir_analysis.get('ebitda_margin_pct', 'not found')}%")
        lines.append(f"Recurring EBIT-Marge (IR): {ir_analysis.get('recurring_ebit_margin_pct', 'not found')}%")
        lines.append(f"Nettoverschuldung (IR): {ir_analysis.get('net_debt_bn', 'not found')} Mrd.")

        # Guidance
        lines.append(f"Guidance 2026: {ir_analysis.get('guidance_2026', 'not found')}")
        lines.append(f"Guidance 2027: {ir_analysis.get('guidance_2027', 'not found')}")

        # Consensus from IR (e.g. Holcim publishes own consensus sheet)
        for key, label in [
            ("consensus_eps_2026",        "Consensus EPS 2026E"),
            ("consensus_eps_2027",        "Consensus EPS 2027E"),
            ("consensus_eps_2028",        "Consensus EPS 2028E"),
            ("consensus_revenue_2026_bn", "Consensus Revenue 2026E (Mrd.)"),
            ("consensus_revenue_2027_bn", "Consensus Revenue 2027E (Mrd.)"),
            ("consensus_revenue_2028_bn", "Consensus Revenue 2028E (Mrd.)"),
        ]:
            v = ir_analysis.get(key)
            if v and v != "not found":
                lines.append(f"{label}: {v}")

        lines.append(f"Management Tone: {ir_analysis.get('management_tone', 'n/v')}")

        # P/E distortion explanation
        pe_note = ir_analysis.get("pe_distortion_explanation", "none")
        if pe_note and pe_note != "none":
            lines.append(f"KGV-Verzerrungshinweis (IR): {pe_note}")

        # yfinance discrepancies
        for disc in ir_analysis.get("yfinance_discrepancies", []):
            lines.append(f"⚠ Diskrepanz IR vs yfinance: {disc}")

        for stmt in ir_analysis.get("key_statements", []):
            lines.append(f"Key Statement: {stmt}")

    lines.append("")
    lines.append(
        f"FORWARD-SCHÄTZUNGEN (Quelle: {forward_estimates.get('source', 'n/v')}, "
        f"Konfidenz: {forward_estimates.get('confidence', 'n/v')})"
    )
    for year, est in forward_estimates.get("estimates", {}).items():
        lines.append(
            f"  {year}: Umsatz {est.get('revenue_bn', 'n/v')} Mrd. | "
            f"EBITDA-Marge {est.get('ebitda_margin_pct', 'n/v')}% | "
            f"EPS {est.get('eps', 'n/v')} "
            f"[{est.get('source', 'n/v')}]"
        )
    for assumption in forward_estimates.get("key_assumptions", []):
        lines.append(f"  Annahme: {assumption}")
    disclaimer = forward_estimates.get("disclaimer")
    if disclaimer:
        lines.append(f"  Disclaimer: {disclaimer}")

    return "\n".join(lines)


if __name__ == "__main__":
    result = run_fundamental_agent("RIEN.SW")
    print(json.dumps(result, indent=2, ensure_ascii=False))
