# KI-Co-Analyst

**Bachelor Thesis 2025/26 | Berner Fachhochschule | Luca Lüdi**

Ein KI-gestütztes Multi-Agent System (MAS) zur professionellen Fundamentalanalyse von Aktien auf Buy-Side-Niveau. Drei spezialisierte Junior-Agenten (Fundamental, News, Risk) liefern Teilanalysen, die ein Senior-Portfolio-Manager-Agent (Supervisor) zu einem strukturierten Investment Memo synthetisiert.

---

## Inhaltsverzeichnis

- [Architektur](#architektur)
- [Agent-Beschreibungen](#agent-beschreibungen)
- [Analyse-Pipeline](#analyse-pipeline)
- [Tools & Datenquellen](#tools--datenquellen)
- [Output-Format](#output-format)
- [Installation](#installation)
- [Konfiguration](#konfiguration)
- [Verwendung](#verwendung)
- [Unterstützte Börsen](#unterstützte-börsen)
- [Kosten pro Analyse](#kosten-pro-analyse)
- [Disclaimer](#disclaimer)

---

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│   Streamlit Web-App (app.py)  /  CLI (main.py)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│            LangGraph StateGraph (graph/)                     │
│                                                              │
│  fundamental_node ──► anomaly_check ──► corporate_actions   │
│       ↑ retry (max 2×)       │                     │        │
│                              ▼                     ▼        │
│                          news_node ────────────────►        │
│                              ↑ retry (max 1×)               │
│                              │                              │
│                              ▼                              │
│                    risk_node ──► quality ──► supervisor_review │
│                                                    │          │
│                                        ┌───────────┴──────┐  │
│                                        │  Critique Loop   │  │
│                                        │  (max 1×)        │  │
│                                        └───────────┬──────┘  │
│                                                    ▼          │
│                                              supervisor ──► END │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│   export_memo.js (Node.js)  →  investment_memo_*.docx       │
└─────────────────────────────────────────────────────────────┘
```

---

## Agent-Beschreibungen

### Fundamental Agent — `agents/fundamental_agent.py`
**Modell:** GPT-5.4-mini

Erstellt eine vollständige Fundamentalanalyse nach Buy-Side-Standard:

- Lädt Finanzkennzahlen aus yfinance (Bilanz, GuV, Cashflow), historische Multiples aus Finnhub und IR-Dokumente via RAG
- **MultiplesEngine** (`tools/multiples_engine.py`) berechnet deterministisch: EV/EBITDA, P/E, P/B, EV/Sales, P/FCF, FCF-Yield, ND/EBITDA, ROE, ROIC, FCF-Conversion — kein LLM-Halluzinations-Risiko
- **DCF-Valuation** via `tools/valuation_engine.py` mit Fair-Value-Berechnung und ELEVATED/FAIR/DISCOUNT-Assessment
- **Sektorspezifische Kennzahlen:** LLM wählt dynamisch die relevanten Multiples pro Sektor (Banken: P/B + ROE, Tech: EV/Sales + P/FCF, etc.)
- **Forward-Estimates:** deterministisch verankert via historischem CAGR, Peer-Median-Wachstum und Management Guidance aus IR-Dokumenten
- **KGV-Validierung:** Erkennt verzerrte Trailing-P/E automatisch und wechselt auf Forward P/E + EV/EBITDA
- **FCF-Analyse:** Flags bei FCF-Conversion ausserhalb 70–130%
- **5-stufige Empfehlung:** KAUFEN / ÜBERGEWICHTEN / HALTEN / UNTERGEWICHTEN / VERKAUFEN (basierend auf DCF-Upside, mit Adjustierung für Bewertungsniveau und FCF-Qualität)

### News Agent — `agents/news_agent.py`
**Modell:** GPT-5.4-mini

Analysiert Nachrichtenlage, Makro und Industrie-Dynamiken:

- Gewichtetes Sentiment-Framework: Strategische Meilensteine 30% / Industrie 30% / Makro 25% / Tagesnews 15%
- Parallele Datenabfragen via `ThreadPoolExecutor` für minimale Latenz
- Expliziter Transmissionsmechanismus für Makro-Indikatoren (z.B. SNB-Zinsen → Baukosten → Nachfrage → EPS)
- Quellenbewertung: Bloomberg/Reuters/FT/WSJ > Handelsblatt/cash.ch > Yahoo Finance
- Trennt strukturelle Veränderungen (CEO-Wechsel, M&A, Regulierung) von täglichem Rauschen

### Risk Agent — `agents/risk_agent.py`
**Modell:** GPT-5.4-mini

Agiert als Advocatus Diaboli — hinterfragt die bestehende Investmentthese:

- 5 spezifische Risiko-Kategorien: Bewertung, Makro/Zins, Operativ, Regulierung, Sentiment — jede mit konkretem Transmissionsmechanismus und Zahlen
- Prüft Confirmation Bias (z.B. selektive Verwendung Forward vs. Trailing P/E, cherry-gepickte Vergleichszeiträume)
- **Conviction Killers:** max. 2 monitorbare Ereignisse/Schwellenwerte, die die Investment-These sofort invalidieren
- 3 Szenarien (Bear/Base/Bull) mit Wahrscheinlichkeiten (Summe = 100%)
- Automatische Abwertung: 2 aktive Conviction Killers → Empfehlung 2 Stufen schlechter

### Supervisor — `graph/supervisor.py`
**Modell:** Claude Sonnet 4.5

Senior Portfolio Manager — Qualitätsprüfung und finale Synthese:

- **Schritt 1 — Qualitätsprüfung:** Konsistenzcheck aller drei Analysen (Zahlendifferenzen >5%, Quellenvollständigkeit, Widersprüche zwischen Agenten)
- **Schritt 2 — Synthese:** Gewichtete Formel (Fundamental 80% / News 10% / Risk 10%), adjustierbar auf 60/20/20 bei sehr schlechtem Sentiment (≤ 3/10)
- **Senior Review Loop:** Kann gezielt eine Analyse zur Überarbeitung zurückschicken (max. 1× pro Analyse)
- Erstellt das finale Investment Memo mit Price Target, Conviction Level und allen Qualitäts-Checks

---

## Analyse-Pipeline

```
START
  │
  ▼ fundamental_node        → Fundamentalanalyse + IR RAG + MultiplesEngine + DCF
  │   └─ Bei unvollständigem Output: bis zu 2× Retry
  │
  ▼ anomaly_check_node      → Erkennt statistische Ausreisser (EPS-Sprünge, Margen-Anomalien)
  │
  ▼ corporate_actions_node  → Prüft M&A, Spin-offs, Kapitalerhöhungen (optional, bei Anomalie)
  │
  ▼ news_node               → News, Makro, Industrie-Sentiment
  │   └─ Bei unvollständigem Output: bis zu 1× Retry
  │
  ▼ risk_node               → Adversariales Risk-Assessment
  │
  ▼ quality_node            → Automatische Qualitäts-Scores (Datenvollständigkeit, Konsistenz)
  │
  ▼ supervisor_review_node  → Senior-Analyst prüft alle drei Analysen auf Konsistenz
  │   └─ Bei Kritik: Critique-Loop → gezielte Überarbeitung (max. 1×)
  │
  ▼ supervisor_node         → Finale Synthese → Investment Memo
  │
  ▼ END
```

---

## Tools & Datenquellen

| Tool | Datei | Beschreibung |
|------|-------|--------------|
| **Finance Tools** | `tools/finance_tools.py` | yfinance (Kurse, Financials, Cashflow), Finnhub (hist. Multiples, Peer-Daten), Tavily (News-Suche) |
| **IR RAG Pipeline** | `tools/ir_rag_tool.py` | Automatisches Scraping & Download von IR-Dokumenten (PDF, PPTX, DOCX) von Unternehmens-IR-Seiten; RAG via FAISS Vectorstore + Claude Haiku |
| **Multiples Engine** | `tools/multiples_engine.py` | Deterministische Berechnung aller Bewertungskennzahlen aus IR + yfinance (kein LLM) |
| **Valuation Engine** | `tools/valuation_engine.py` | DCF Fair-Value, 3-Jahres-Forward-Estimates verankert an historischem CAGR + Peer-Median |
| **Schemas** | `tools/schemas.py` | Pydantic-Modelle für alle Agent-Outputs (type-safe JSON-Parsing) |

### Datenquellen-Priorität (Fundamental Agent)
1. **IR-Dokumente** — geprüfte, bereinigte Zahlen direkt vom Unternehmen (höchste Priorität)
2. **Finnhub** — institutionelle Datenqualität, historische Multiples
3. **yfinance** — breite Abdeckung, gelegentlich verzögert oder bereinigungsbedingt verzerrt

Widersprüche zwischen Quellen werden immer explizit dokumentiert.

---

## Output-Format

Pro Analyse werden drei Dateien generiert:

| Datei | Format | Inhalt |
|-------|--------|--------|
| `output_memo_{TICKER}.json` | JSON | Vollständiger strukturierter Output aller Agenten inkl. Routing-Log |
| `output_memo_{TICKER}.txt` | Text | Lesbares Investment Memo |
| `investment_memo_{TICKER}.docx` | Word | Formatiertes A4-Dokument (A4, professionelles Layout via `export_memo.js`) |

### Struktur des finalen Memos (JSON-Auszug)

```json
{
  "company_name": "Holcim AG",
  "ticker": "HOLN.SW",
  "sector": "Basic Materials",
  "current_price": 87.5,
  "final_recommendation": "ÜBERGEWICHTEN",
  "price_target": 98.0,
  "upside_pct": 12.0,
  "conviction_level": "mittel",
  "investment_case": "...",
  "key_metrics": [...],
  "valuation_table": [...],
  "_full_financials": [...],
  "scenarios": {
    "bear": { "probability_pct": 25, "target": 70.0, "description": "..." },
    "base": { "probability_pct": 55, "target": 98.0, "description": "..." },
    "bull": { "probability_pct": 20, "target": 115.0, "description": "..." }
  },
  "conviction_killers": [...],
  "quality_checks": [...],
  "routing_log": [...],
  "analysis_duration_s": 87.4
}
```

---

## Installation

### Voraussetzungen
- Python 3.11+
- Node.js 18+ (für Word-Export)
- API Keys: OpenAI, Anthropic, Finnhub, Tavily

### 1. Repository klonen
```bash
git clone https://github.com/tryoutluca/ki-portfolio-manager
cd ki-portfolio-manager
```

### 2. Virtuelle Umgebung erstellen
```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate
```

### 3. Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Node.js Dependencies (Word-Export)
```bash
npm install
```

---

## Konfiguration

### API Keys einrichten

```bash
cp .env.example .env
```

Dann `.env` öffnen und alle Keys eintragen:

| Variable | Beschreibung | Bezugsquelle | Kosten |
|----------|-------------|--------------|--------|
| `OPENAI_API_KEY` | GPT-4o-mini für 3 Junior-Agenten | platform.openai.com | Pay-per-use |
| `ANTHROPIC_API_KEY` | Claude Sonnet für Supervisor + IR RAG | console.anthropic.com | Pay-per-use |
| `FINNHUB_API_KEY` | Historische Multiples, Peer-Daten | finnhub.io | Kostenlos (Free Tier) |
| `TAVILY_API_KEY` | News-Suche für News-Agent | tavily.com | Kostenlos (Free Tier) |

---

## Verwendung

### Web-App (empfohlen)
```bash
streamlit run app.py
```
Öffnet automatisch `http://localhost:8501`

Features:
- Ticker-Eingabe mit automatischer Exchange-Suffix-Erkennung
- Echtzeit-Fortschrittsanzeige für alle Pipeline-Stufen
- Interaktive Anzeige aller Agent-Outputs und Qualitäts-Checks
- Word-Export direkt aus dem Browser
- **Demo-Modus:** vollständige Beispielanalyse ohne API Keys laden (Button "Demo laden")

### Terminal-CLI
```bash
python main.py
```
Interaktive Ticker-Eingabe, dann automatischer Pipeline-Ablauf (~60–120 Sekunden).

### Direkte API-Nutzung
```python
from graph.graph import run_analysis

result = run_analysis("HOLN.SW")
print(result["final_recommendation"])  # z.B. "ÜBERGEWICHTEN"
print(result["price_target"])          # z.B. 98.0
print(result["upside_pct"])            # z.B. 12.0
```

---

## Unterstützte Börsen

| Exchange | Suffix | Beispiel-Ticker |
|----------|--------|-----------------|
| US NASDAQ / NYSE | *(keiner)* | `AAPL`, `MSFT`, `NVDA`, `GOOGL`, `AMZN` |
| SIX Swiss Exchange | `.SW` | `HOLN.SW`, `NESN.SW`, `NOVN.SW`, `UBSG.SW`, `LONN.SW` |
| XETRA (Deutschland) | `.DE` | `SAP.DE`, `SIE.DE`, `BMW.DE`, `BAYN.DE` |
| London Stock Exchange | `.L` | `SHEL.L`, `AZN.L`, `HSBA.L`, `BP.L` |
| Euronext Paris | `.PA` | `MC.PA`, `OR.PA`, `BNP.PA` |

Der Ticker-Validator in `main.py` erkennt bekannte Schweizer, Deutsche und Londoner Ticker automatisch und fügt den korrekten Exchange-Suffix hinzu.

---

## Kosten pro Analyse

Circa **$0.05–0.20 USD** pro vollständiger Analyse (abhängig von Ticker, IR-Dokumenten-Länge und ob der Critique-Loop ausgelöst wird):

| Komponente | Modell | Kosten (ca.) |
|------------|--------|--------------|
| Supervisor (Synthese + Review) | Claude Sonnet 4.5 | ~$0.05 |
| IR RAG Analyse | Claude Haiku/Sonnet | ~$0.02–0.10 |
| Fundamental Agent | GPT-4o-mini | ~$0.02 |
| News Agent | GPT-4o-mini | ~$0.01 |
| Risk Agent | GPT-4o-mini | ~$0.01 |
| Finnhub + Tavily | — | kostenlos |

---

## Projektstruktur

```
ki-portfolio-manager/
├── agents/
│   ├── fundamental_agent.py    # Fundamentalanalyse + MultiplesEngine + DCF
│   ├── news_agent.py           # News, Makro, Industrie-Sentiment
│   └── risk_agent.py           # Advocatus Diaboli — Risk Assessment
├── graph/
│   ├── graph.py                # LangGraph StateGraph + run_analysis()
│   ├── supervisor.py           # Supervisor Agent (Claude Sonnet)
│   ├── nodes.py                # Alle Graph-Knoten (fundamental, news, risk, quality, ...)
│   ├── edges.py                # Routing-Logik + Retry-Conditions
│   └── state.py                # AnalysisState TypedDict
├── tools/
│   ├── finance_tools.py        # yfinance, Finnhub, Tavily
│   ├── ir_rag_tool.py          # IR-Dokument RAG Pipeline (FAISS Vectorstore)
│   ├── multiples_engine.py     # Deterministische Kennzahlen-Berechnung
│   ├── valuation_engine.py     # DCF + Forward-Estimates
│   └── schemas.py              # Pydantic Output-Schemas
├── ir_cache/                   # Lokal gecachte IR-Dokumente (PDF/PPTX/DOCX)
├── app.py                      # Streamlit Web-App (~1600 Zeilen)
├── main.py                     # Terminal CLI mit Ticker-Validator
├── export_memo.js              # Node.js Word-Export (docx-Bibliothek)
├── requirements.txt            # Python Dependencies
├── package.json                # Node.js Dependencies
└── .env.example                # API Key Template
```

---

## Deployment (Railway) & Datenbank

### Benötigte Env-Vars

| Variable | Zweck | Pflicht |
|---|---|---|
| `DATABASE_URL` | Railway-Managed-Postgres-Connection-String. Gesetzt → `tools/financial_db.py` nutzt Postgres (psycopg + Connection-Pool). Fehlt → lokaler SQLite-Fallback (`DATA_DIR/financials.db`). | Empfohlen in Prod |
| `DATA_DIR` | Pfad zum Railway-Volume (z.B. `/app/data`) für Historie/Credentials und den SQLite-Fallback. Ohne Volume gehen Daten bei jedem Deploy verloren. | Ja |
| `ADMIN_PASSWORD` | Admin-Account (`admin`) wird bei jedem Start neu daraus gehasht. Nötig für Login und für alle `/db/*`-Endpoints (`require_admin`). | Ja |
| `JWT_SECRET` | Signaturschlüssel für Login-Tokens. Ohne Setzen wird ein unsicherer Dev-Default verwendet. | Ja (Prod) |
| `CORS_ORIGINS` | Komma-separierte erlaubte Frontend-URLs. | Ja |
| `DB_STALENESS_DAYS` | Cache-Freshness-Schwelle für `get_historical_financials` (Default 30). | Nein |
| API-Keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `TAVILY_API_KEY`) | Von den jeweiligen Agenten/Tools benötigt. | Ja |

### Postgres-Migration (einmalig, von SQLite)

```bash
DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py
```

Liest die lokale/Volume-SQLite (`financials.db`) und schreibt alle Zeilen per Upsert
(gleiche Quellen-Priorität wie im Live-Betrieb: sec_xbrl > ir_pdf > yfinance) nach
Postgres. Idempotent — kann gefahrlos mehrfach laufen.

### Externer Zugriff (DBeaver / TablePlus)

Railway stellt für Managed-Postgres eine öffentliche Connection-URL bereit
(Projekt → Postgres-Service → Tab **"Connect"** → "Public Network"). Damit in
DBeaver/TablePlus verbinden:

1. Neue PostgreSQL-Verbindung anlegen.
2. Host/Port/Database/User/Passwort aus der öffentlichen Railway-URL übernehmen
   (Format `postgresql://user:pass@host:port/dbname` — Werte 1:1 in die
   entsprechenden Felder eintragen).
3. SSL: "Require" aktivieren (Railway verlangt TLS für die öffentliche Verbindung).
4. Tabelle `financial_data` sowie die View `qa_report` (Datenqualitäts-Übersicht
   pro Ticker: Jahre, ohne Währung, ohne Umsatz, letztes Update) sind direkt
   abfragbar.

**Achtung:** Die öffentliche Postgres-URL ist ein Credential — nicht in Tickets,
Chats oder Screenshots teilen.

---

## Disclaimer

Dieses System wurde im Rahmen einer Bachelor Thesis an der Berner Fachhochschule entwickelt und dient **ausschliesslich zu Forschungs- und Demonstrationszwecken**. Es stellt **keine Anlageberatung** dar. Die generierten Analysen und Empfehlungen ersetzen nicht die professionelle Beurteilung eines zugelassenen Finanzberaters. Investitionen in Wertpapiere sind mit Risiken verbunden.
