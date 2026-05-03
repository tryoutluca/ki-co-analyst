# KI-Co-Portfolio-Manager

**Bachelor Thesis 2025/26 | Berner Fachhochschule | Luca Lüdi**

Multi-Agent System (MAS) zur Unterstützung von Investitionsentscheidungen für Portfolio Manager.

---

## System-Architektur

```
main.py / app.py (Streamlit)
       │
       ▼
graph/supervisor.py          ← Claude Sonnet (Synthese)
  ├── graph/fundamental_agent.py  ← GPT-4o-mini + IR RAG
  ├── graph/news_agent.py          ← GPT-4o-mini + Makro
  └── graph/risk_agent.py          ← GPT-4o-mini (Advocatus Diaboli)
       │
       ▼
tools/
  ├── finance_tools.py       ← yfinance + Finnhub + SEC
  ├── ir_rag_tool.py         ← IR-Dokumente RAG Pipeline
  ├── valuation_engine.py    ← DCF + ELEVATED/FAIR/DISCOUNT
  └── schemas.py             ← Pydantic Datenmodelle
```

---

## Installation

### 1. Repository klonen
```bash
git clone https://github.com/[dein-username]/ki-portfolio-manager
cd ki-portfolio-manager
```

### 2. Virtuelle Umgebung
```bash
python -m venv venv

# Mac/Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### 3. Python Dependencies
```bash
pip install -r requirements.txt
```

### 4. Node.js Dependencies (Word-Export)
```bash
npm install
```

### 5. API Keys konfigurieren
```bash
cp .env.example .env
```
Dann `.env` öffnen und die Keys eintragen:

| Key | Wo erhältlich | Kosten |
|-----|---------------|--------|
| `ANTHROPIC_API_KEY` | console.anthropic.com | Pay-per-use |
| `OPENAI_API_KEY` | platform.openai.com | Pay-per-use |
| `FINNHUB_API_KEY` | finnhub.io | Kostenlos (Free Tier) |

---

## Starten

### Web-App (Streamlit) — empfohlen
```bash
streamlit run app.py
```
Öffnet automatisch `http://localhost:8501`

### Terminal
```bash
python main.py
```

---

## Demo

Ohne eigene API Keys kann der **Demo-Output** geladen werden:
- In der Streamlit-App: Button "📂 Demo laden (Holcim)"
- Zeigt eine vollständige Analyse von Holcim AG (HOLN.SW)

---

## Beispiel-Ticker

| Ticker | Unternehmen | Börse |
|--------|-------------|-------|
| `HOLN.SW` | Holcim AG | SIX Swiss Exchange |
| `NESN.SW` | Nestlé SA | SIX Swiss Exchange |
| `NOVN.SW` | Novartis AG | SIX Swiss Exchange |
| `AAPL` | Apple Inc. | NASDAQ |
| `MSFT` | Microsoft Corp. | NASDAQ |
| `SAP.DE` | SAP SE | XETRA |

---

## Output

Pro Analyse werden generiert:
- `output_memo_{TICKER}.json` — vollständiger strukturierter Output
- `output_memo_{TICKER}.txt` — lesbares Text-Memo
- `Investment_Memo_{TICKER}.docx` — Word-Dokument (via `node export_memo.js`)

---

## Kosten pro Analyse

Circa **$0.05–0.15 USD** pro Analyse (abhängig von Ticker und IR-Dokumenten):
- Claude Sonnet: ~$0.05
- GPT-4o-mini (3× Agenten): ~$0.03
- Finnhub Free Tier: kostenlos

---

## Disclaimer

Dieses System wurde im Rahmen einer Bachelor Thesis entwickelt und dient
ausschliesslich zu Forschungs- und Demonstrationszwecken.
Es stellt keine Anlageberatung dar.