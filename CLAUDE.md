# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Backend (FastAPI)
uvicorn backend.api:app --reload --port 8000
# With local auth (required for login):
ADMIN_PASSWORD=test uvicorn backend.api:app --reload --port 8000

# Frontend (Next.js)
cd frontend && npm run dev        # dev server on :3000
cd frontend && npx tsc --noEmit   # type-check only

# Tests
pytest tests/test_period_guards.py -m "not integration" -v   # unit only (no network)
pytest tests/test_period_guards.py -v                          # all incl. live yfinance
pytest tests/ -m "not integration" -q                          # all unit tests (no network)

# Run a single analysis (CLI)
python main.py ABBN.SW
```

## Architecture

This is a **LangGraph multi-agent financial analysis system** with a FastAPI backend and Next.js frontend.

### Analysis Pipeline (`graph/`)

Entry point: `graph/graph.py → run_analysis(ticker)` builds a `StateGraph` and runs it.

Node execution order (defined in `graph/edges.py`):
1. `classifier` — sector/business model classification
2. `fundamental` — orchestrates all data collection + 4 parallel sub-agents
3. `news` — macro/sentiment
4. `estimate_revision` — consensus adjustment
5. `thematic` — megatrends
6. `optionality` — real options
7. `forward_estimate` — 3-year projections
8. `risk` — Advocatus Diaboli
9. `supervisor` — final synthesis → Investment Memo

Shared state is typed in `graph/state.py` (AnalysisState TypedDict). Every node reads from and writes to this state.

### Fundamental Agent (`agents/fundamental_agent.py`)

The heaviest node. Sequence:
1. Loads data: yfinance (`finance_tools.py`), IR-RAG (`ir_rag_tool.py`), historical multiples
2. Runs `MultiplesEngine.from_ticker()` — deterministic 16-multiple calculator
3. Runs 4 sub-agents in parallel via `ThreadPoolExecutor`: Quality, Growth, Valuation, Capital Allocation (`agents/sub/`)
4. Lead LLM synthesises sub-agent outputs → FundamentalAgentOutput

### Key Tools (`tools/`)

| File | Purpose |
|------|---------|
| `finance_tools.py` | yfinance wrapper — prices, financials, cashflow, historical multiples |
| `ir_rag_tool.py` | IR document pipeline: scrapes IR website → downloads PDFs → FAISS vectorstore → LLM extraction. Returns `_EMPTY_IR`-shaped dict + `ir_annual_years` (list, up to 3 annual years) + `ir_quarterly_latest` (dict or None) |
| `multiples_engine.py` | Deterministic EV/EBITDA, P/E, FCF-yield etc. Has period-contamination guards (`_fcf_suspect`, `_guard_warnings`). Never call with quarterly FCF as annual input. |
| `period_classifier.py` | `classify_pdf_period(title)` → `"annual"|"quarterly"|"h1"|"9m"|None`. Used by IR-RAG to tag document types. |
| `valuation_engine.py` | DCF model |
| `sentiment_engine.py` | Deterministic news sentiment: junk/relevance filter, cross-source dedup, source/recency weighting (news 14d, milestones 180d half-life), then aggregates the LLM's per-item ratings (IDs `M*` milestones, `N*` Yahoo news, `R*` research) into `overall_sentiment_score`. Items the LLM marks `relevant: false` (namesakes, listed subsidiaries) are excluded. LLM's own score kept as `llm_sentiment_score`; details in `sentiment_breakdown`. |
| `lm_tone.py` | Loughran-McDonald tone of annual reports (English only), YoY change → `ir_analysis["ir_tone"]` → Risk agent. Word lists in `tools/data/lm_wordlists.json` (LM 2018; research use, commercial use needs licence). Per-year results accumulate in `ir_cache/{ticker}/lm_tone.json`. |

`finance_tools.tavily_search()` is the only Tavily entry point (direct REST, no LangChain wrapper). Use `topic="news"` to get publication dates.

### News Agent Autonomy (`agents/news_research.py`)

Before the main news LLM call, a tool-use loop lets the LLM decide whether to run targeted follow-up searches (`search_news`) or stop (`finish_research`). Code-enforced guardrails: max 3 searches, `tool_choice="required"`, and finishing with < 3 real company items and no search is rejected. Results go through `prepare_research_items()` and count toward the milestone component. Log in `news_output["research_log"]`.
| `schemas.py` | Pydantic output schemas (ForwardEstimateOutput, etc.) |

### IR-RAG Document Strategy

`get_ir_analysis(ticker)` fetches:
- **3 annual reports** (10-K/20-F for US, Geschäftsbericht for CH/EU)
- **1 latest report** (quarterly if available, else annual)

All chunks are tagged with `period_class` ("annual"/"quarterly") and `fiscal_year` in metadata. Two LLM extraction passes: annual context → `ir_annual_years`, quarterly context → `ir_quarterly_latest`.

**HTML/SEC extraction** (`load_html_document`): SEC iXBRL filings put prose in `<div>` (not `<p>`) and split numbers into short table cells — `_extract_html_blocks()` reads innermost blocks and whole tables row-wise (with the preceding heading as label). Cap 400k chars for sec.gov, 60k otherwise. Foreign private issuers (`_SEC_FOREIGN_FILERS`): the quarterly doc is chosen via `_sec_6k_report_url()` (EX-99 "financial report" exhibit or `ticker-YYYYMMDD.htm` primary doc), and SEC data older than 2 years (e.g. ABB, deregistered 2024) falls back to the IR website.

**Document discovery** (`find_ir_pdfs`): IR website / SEC first (`_find_ir_pdfs_website`); for non-SEC tickers with missing, stale (< prior FY from April) or < 2 annual reports, a Tavily search fallback (`_find_ir_pdfs_via_search`) adds PDFs from the company's own domain only — needed for bot-protected / JS-only sites (Nestlé, ABB). `_PDF_TYPE_RULES` order matters (interim before annual: "Halbjahresbericht" contains "jahresbericht"). One document per fiscal year, ranked by `_annual_doc_rank` (financial report/statements > annual/integrated report > results release > presentation), English before German.

**RAG context** (`_build_rag_context`): per-fiscal-year budget, round-robin over `STANDARD_QUERIES`, full chunks, deduplicated. Budgets: `_ANNUAL_CONTEXT_CHARS` 80k, `_QUARTERLY_CONTEXT_CHARS` 40k (min 12k per year). Previously 20k/8k with 400-char chunk truncation cut off balance sheet, cash flow, EPS and dividend queries entirely.

**Routing rule:** `ir_annual_years` → historical A-columns + MultiplesEngine inputs only. `ir_quarterly_latest` → QuarterlySignal → ForwardEstimateAgent E-columns only. Never mix.

### Backend (`backend/api.py`)

FastAPI with JWT auth. Admin account auto-created at startup from `ADMIN_PASSWORD` env var (every startup — not just first deploy). Persistent data stored at `DATA_DIR` env var (Railway Volume: `/app/data`).

Key env vars:
- `ADMIN_PASSWORD` — required for login to work
- `DATA_DIR` — defaults to project root if unset (not persisted on Railway without this)
- `CORS_ORIGINS` — comma-separated frontend URLs
- `JWT_SECRET` — defaults to insecure dev value

Analysis jobs run in background threads; polled via `GET /analyse/jobs/{job_id}`.

### Frontend (`frontend/`)

Next.js App Router. **Warning:** This uses Next.js 16 with breaking changes from common training data — read `node_modules/next/dist/docs/` before writing Next.js-specific code.

Layout: `app/(app)/layout.tsx` holds sidebar open/close state, passes toggle to `Topbar` and `Sidebar`. Sidebar is an off-canvas drawer on `< lg` screens, static on `lg:`.

API calls go through `frontend/lib/api.ts` (axios). Backend URL from `NEXT_PUBLIC_API_URL` env var (defaults to `http://localhost:8000`).

### Data Flow Summary

```
yfinance (4 years)          ─┐
SEC EDGAR XBRL              ─┤→ MultiplesEngine (deterministic)
IR-RAG annual (3 years)     ─┤→ Sub-agents (LLM)
IR-RAG quarterly (1 latest) ─┘→ QuarterlySignal → ForwardEstimateAgent
```

### Period Guard Rules (critical)

The FCF period-contamination fix (ABBN.SW bug): a quarterly FCF from an IR interim PDF must never be used as the annual FCF in MultiplesEngine. Guards in `multiples_engine.py`:
- Cross-source ratio [0.40, 1.75]: IR FCF vs yfinance TTM FCF
- Prior-year ratio guard [0.40, 1.75]
- FCF/CFO band [0.30, 1.15]
- Absolute: EV/FCF > 80x or FCF-Yield < 0.5% → suppress (value: None, never "n/v")

When `_fcf_suspect = True`, all FCF-related multiples are suppressed. `_guard_warnings` are logged to stdout (captured as live-reasoning in the UI) but not shown in the final memo.
