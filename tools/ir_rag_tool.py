"""
tools/ir_rag_tool.py
RAG pipeline that automatically finds, downloads and analyses IR documents.

Required packages (in addition to existing requirements):
    pip install langchain-community pypdf faiss-cpu tiktoken python-pptx beautifulsoup4
"""

import os
import json
import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter  # type: ignore

from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS

try:
    from langchain_community.document_loaders import Docx2txtLoader
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

try:
    from pptx import Presentation as _PptxPresentation
    _PPTX_AVAILABLE = True
except ImportError:
    _PPTX_AVAILABLE = False

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.finance_tools import get_cashflow_data

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

IR_PAGE_PATTERNS = [
    "/investors/publications",
    "/investors",
    "/investor-relations",
    "/ir",
    "/investors/financial-results",
]

PRIORITY_KEYWORDS = [
    "consensus",
    "analyst presentation",
    "annual report",
    "financial report",
    "half-year",
    "quarterly results",
    "investor day",
    "outlook",
    "guidance",
]

EXCLUDE_KEYWORDS = [
    "sustainability",
    "governance",
    "compensation",
    "esg",
    "proxy",
]

CACHE_DIR = "./ir_cache"
CACHE_MAX_AGE_HOURS = 24

_KNOWN_IR_URLS: dict[str, str] = {
    # Swiss
    "HOLN.SW": "https://www.holcim.com/investors/publications",
    "NESN.SW": "https://www.nestle.com/investors/reports-and-presentations",
    "NOVN.SW": "https://www.novartis.com/investors/financial-data/annual-reports",
    "ROG.SW":  "https://www.roche.com/investors/annual-reports",
    "UBSG.SW": "https://www.ubs.com/global/en/investor-relations/financials",
    "RIEN.SW": "https://www.rieter.com/investor-relations/results-and-presentations/financial-reports",
    "ABBN.SW": "https://investors.abb.com/financial-information/annual-reports",
    "GEBN.SW": "https://www.geberit.com/investors/financial-reports",
    "SIKA.SW": "https://www.sika.com/en/group/investor-relations/financial-reports",
    "GIVN.SW": "https://www.givaudan.com/investors/financial-reports",
    "SCHN.SW": "https://www.schindler.com/com/internet/en/investor-relations/reports.html",
    "LONN.SW": "https://www.lonza.com/investors/financial-reports",
    "PGHN.SW": "https://www.partnersgroup.com/en/investors/shareholder-information/reports",
    "SLHN.SW": "https://www.swisslife.com/en/home/investors/publications.html",
    "BAER.SW": "https://www.juliusbaer.com/en/investor-relations/financial-reports",
    "CFR.SW":  "https://www.richemont.com/investors/financial-reports",
    "LISN.SW": "https://www.lindt-spruengli.com/investor-relations/reporting/annual-reports",
    "AAPL":    "https://investor.apple.com/financial-information/sec-filings/default.aspx",
    "MSFT":    "https://www.microsoft.com/en-us/investor/sec-filings.aspx",
    "GOOGL":   "https://abc.xyz/investor/",
    "GOOG":    "https://abc.xyz/investor/",
    "META":    "https://investor.atmeta.com/sec-filings/annual-reports",
    "AMZN":    "https://ir.aboutamazon.com/sec-filings/annual-reports",
    "NVDA":    "https://investor.nvidia.com/financial-information/sec-filings",
    "TSLA":    "https://ir.tesla.com/sec-filings/annual-reports",
    "JPM":     "https://www.jpmorganchase.com/ir/annual-report",
    "GS":      "https://www.goldmansachs.com/investor-relations/financials/",
}

# HTML anchor-text keywords used to detect IR documents when no PDFs are found
_HTML_IR_KEYWORDS = [
    "annual report", "quarterly results", "earnings", "press release",
    "presentation", "outlook", "guidance", "10-k", "10-q", "10k", "10q",
    "investor presentation", "financial results", "interim report",
]

# URL path segments that indicate a report-index sub-page (EU/CH multi-level IR sites)
_SUBPAGE_FOLLOW_PATTERNS = [
    "financial-report", "annual-report", "half-year-report", "interim-report",
    "results-and-presentations", "financial-results", "results",
    "publications", "downloads", "filings", "reports",
    "geschaeftsbericht", "jahresbericht", "halbjahresbericht", "berichte",
    "rapport-annuel", "resultats", "publications-financieres",
]

# EU/CH PDF fallback classification when _PDF_TYPE_RULES don't match
_EU_PDF_ANNUAL  = re.compile(
    r"annual|full[_\-\s]year|geschaeft|jahres|rapport[_\-\s]annuel|full[_\-\s]report",
    re.I,
)
_EU_PDF_INTERIM = re.compile(
    r"half[_\-\s]year|interim|halbjahr|semest|six[_\-\s]month|h1[-_\s\.]|h2[-_\s\.]",
    re.I,
)

# SEC EDGAR base URLs and constants
SEC_USER_AGENT         = "KI-Portfolio-Manager research@bfh.ch"
SEC_TICKERS_CACHE      = Path(CACHE_DIR) / "sec_tickers.json"
SEC_TICKERS_URL        = "https://www.sec.gov/files/company_tickers.json"
SEC_TICKERS_MAX_AGE_DAYS = 7

_SEC_EDGAR_BASE      = "https://www.sec.gov"
_SEC_HEADERS         = {
    "User-Agent": SEC_USER_AGENT,
    "Accept":     "application/json",
}
_SEC_TICKERS_CACHE   = SEC_TICKERS_CACHE
_SEC_TICKERS_CACHE_H = SEC_TICKERS_MAX_AGE_DAYS * 24

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

# Doc type → (priority, keyword pairs that must ALL appear in label)
_PDF_TYPE_RULES: list[tuple[str, int, list[str], list[str]]] = [
    # (type, priority, required_any, required_all)
    ("consensus_estimates",  1, ["consensus"],                      []),
    ("analyst_presentation", 2, ["analyst"],                        ["presentation"]),
    ("annual_report",        3, ["annual report", "financial report"], []),
    ("annual_report",        3, ["annual"],                         ["report"]),
    ("annual_report",        3, ["geschaeftsbericht", "jahresbericht", "rapport annuel"], []),
    ("interim_report",       4, ["half-year", "half year", "h1 results", "h2 results",
                                 "interim", "halbjahr", "six month"],  []),
    ("investor_day",         5, ["investor day", "investor presentation", "cmd"], []),
]

STANDARD_QUERIES = [
    "adjusted EPS earnings per share bereinigt",
    "free cash flow FCF Cashflow",
    "revenue net sales Umsatz guidance outlook Prognose",
    "EBITDA margin Marge recurring",
    "net debt Nettoverschuldung leverage",
    "dividend Dividende",
    "capital expenditure capex Investitionen",
    "consensus estimates analyst forecast 2026 2027 2028",
    "organic growth targets Ziele strategy Strategie",
    "return on invested capital ROIC",
]

_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)


# ── Lazy-init LLM / Embeddings ────────────────────────────────────────────────

_llm: ChatAnthropic | None = None
_emb: OpenAIEmbeddings | None = None


def _get_llm() -> ChatAnthropic:
    global _llm
    if _llm is None:
        _llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
    return _llm


def _get_emb() -> OpenAIEmbeddings:
    global _emb
    if _emb is None:
        _emb = OpenAIEmbeddings()
    return _emb


# ── 1. Find IR URL ────────────────────────────────────────────────────────────

def find_ir_url(ticker: str, company_name: str = "") -> str:
    """
    Returns the best IR page URL for *ticker*, or '' if not found.

    For US tickers (no '.' in symbol): SEC EDGAR is the primary source.
      Returns a canonical EDGAR browse URL that find_ir_pdfs() detects and
      routes directly to get_sec_filings().

    For EU/CH tickers: tries the known-URL mapping, then yfinance + pattern probing.
    """
    # ── US tickers: SEC EDGAR as primary path ────────────────────────────────
    if _sec_is_us_ticker(ticker):
        cik = get_sec_cik(ticker)
        if cik:
            cik_padded = cik.zfill(10)
            sec_url = (
                f"{_SEC_EDGAR_BASE}/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik_padded}"
                f"&type=10-K&dateb=&owner=include&count=10"
            )
            print(f"      SEC EDGAR: CIK={int(cik)} fuer {ticker} -> {sec_url[:70]}")
            return sec_url
        # CIK not found — fall through to website scraping below

    # ── Known hard-coded mapping (EU/CH primary, US fallback) ────────────────
    if ticker in _KNOWN_IR_URLS:
        url = _KNOWN_IR_URLS[ticker]
        try:
            r = requests.get(url, headers=_HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200:
                print(f"      IR-Seite gefunden: {url}")
                return url
        except Exception:
            pass

    # ── yfinance website + IR path patterns (EU/CH tickers) ──────────────────
    base_url = ""
    try:
        info = yf.Ticker(ticker).info
        website = info.get("website", "").strip().rstrip("/")
        if website:
            if not website.startswith("http"):
                website = "https://" + website
            base_url = website
    except Exception:
        pass

    if not base_url:
        return ""

    for path in IR_PAGE_PATTERNS:
        url = base_url + path
        try:
            r = requests.get(url, headers=_HEADERS, timeout=8, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 800:
                print(f"      IR-Seite gefunden: {url}")
                return url
        except Exception:
            continue

    return base_url


# ── 2a. SEC EDGAR helpers ─────────────────────────────────────────────────────

def _sec_is_us_ticker(ticker: str) -> bool:
    """Returns True for plain US tickers (no exchange suffix like .SW, .L, .PA)."""
    return "." not in ticker


def get_sec_cik(ticker: str) -> str | None:
    """
    Returns the 10-digit zero-padded CIK for *ticker*, or None.

    Way A (primary): SEC company_tickers.json — full list, cached 7 days locally.
    Way B (fallback): browse-edgar atom feed — parses <cik-number> from XML.
    """
    ticker_upper = ticker.upper()

    # Way A: local cache of the full tickers list (7-day TTL)
    mapping: dict = {}
    cache_ok = False
    try:
        if _SEC_TICKERS_CACHE.exists():
            age_h = (time.time() - _SEC_TICKERS_CACHE.stat().st_mtime) / 3600
            if age_h < _SEC_TICKERS_CACHE_H:
                mapping  = json.loads(_SEC_TICKERS_CACHE.read_text(encoding="utf-8"))
                cache_ok = True
    except Exception:
        pass

    if not cache_ok:
        try:
            r = requests.get(
                SEC_TICKERS_URL,
                headers=_SEC_HEADERS, timeout=12,
            )
            r.raise_for_status()
            mapping = r.json()
            _SEC_TICKERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
            _SEC_TICKERS_CACHE.write_text(
                json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
            )
            time.sleep(0.15)  # SEC rate-limit courtesy
        except Exception:
            pass

    for entry in mapping.values():
        if str(entry.get("ticker", "")).upper() == ticker_upper:
            return str(entry["cik_str"]).zfill(10)

    # Way B: EDGAR atom feed — accepts ticker directly as CIK parameter
    try:
        r = requests.get(
            f"{_SEC_EDGAR_BASE}/cgi-bin/browse-edgar",
            params={
                "company": "", "CIK": ticker, "type": "10-K",
                "dateb": "", "owner": "include", "count": "1",
                "search_text": "", "action": "getcompany", "output": "atom",
            },
            headers=_SEC_HEADERS, timeout=12,
        )
        r.raise_for_status()
        time.sleep(0.15)
        # <cik-number> tag in the atom response
        m = re.search(r"<cik-number>(\d+)</cik-number>", r.text)
        if m:
            return m.group(1).zfill(10)
        # Fallback: 10-digit CIK embedded in a URL inside the response
        m = re.search(r"CIK=(\d{10})", r.text)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None


def _sec_fetch_filing_doc_url(filing_index_url: str) -> str | None:
    """
    Parses the SEC filing index page and returns the primary document URL.
    Used when the submissions JSON doesn't supply a primaryDocument name.
    """
    try:
        r = requests.get(filing_index_url, headers=_SEC_HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(0.15)
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            doc_type = cells[0].get_text(strip=True).upper()
            doc_href = cells[2].find("a", href=True) if len(cells) > 2 else None
            if not doc_href:
                continue
            href = doc_href["href"]
            if not href.lower().endswith((".htm", ".html")):
                continue
            if "index" in href.lower():
                continue
            if doc_type in ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A"):
                return href if href.startswith("http") else _SEC_EDGAR_BASE + href
        # Fallback: first non-index htm link in the table
        for a in soup.select("table a[href]"):
            href = a["href"]
            if href.lower().endswith((".htm", ".html")) and "index" not in href.lower():
                return href if href.startswith("http") else _SEC_EDGAR_BASE + href
    except Exception:
        pass
    return None


def get_sec_filings(ticker: str, cik: str) -> list[dict]:
    """
    Fetches the three most relevant recent SEC filings for *ticker* (CIK known).

    Uses the EDGAR submissions API:
      https://data.sec.gov/submissions/CIK{cik_padded}.json

    Returns up to 3 dicts compatible with the find_ir_pdfs schema:
      {url, filename, type, priority, year, text, format="html", source}
    """
    cik_padded = cik.zfill(10)
    cik_int    = int(cik)        # numeric CIK for archive URL path

    target_forms = {
        "10-K": ("annual_report",    3),
        "10-Q": ("interim_report",   2),
        "8-K":  ("earnings_release", 1),
    }

    filings_by_type: dict[str, dict] = {}
    try:
        sub_url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
        r = requests.get(sub_url, headers=_SEC_HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(0.15)

        recent       = r.json().get("filings", {}).get("recent", {})
        form_types   = recent.get("form",            [])
        accessions   = recent.get("accessionNumber", [])
        dates        = recent.get("reportDate",      [])
        prim_docs    = recent.get("primaryDocument", [])

        for form, acc, date, prim_doc in zip(form_types, accessions, dates, prim_docs):
            form_clean = form.strip().upper()
            if form_clean not in target_forms:
                continue
            if form_clean in filings_by_type:
                continue  # keep only the most-recent filing per type

            acc_nodash   = acc.replace("-", "")
            archive_base = (
                f"{_SEC_EDGAR_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}"
            )

            # Prefer the primary document listed in the submissions JSON
            doc_url = (
                f"{archive_base}/{prim_doc}"
                if prim_doc
                else _sec_fetch_filing_doc_url(f"{archive_base}/{acc}-index.htm")
                or f"{archive_base}/{acc}-index.htm"
            )

            doc_type, priority = target_forms[form_clean]
            year_match = re.search(r"20[12]\d", date or "")
            year = int(year_match.group()) if year_match else 0

            filings_by_type[form_clean] = {
                "url":      doc_url,
                "filename": f"SEC_{form_clean}_{date}.html",
                "type":     doc_type,
                "priority": priority,
                "year":     year,
                "text":     f"{form_clean} filed {date}",
                "format":   "html",
                "source":   f"SEC EDGAR {form_clean}",
            }

            if len(filings_by_type) == 3:
                break

    except Exception as exc:
        print(f"      SEC EDGAR submissions API Fehler ({ticker}): {exc}")

    result = sorted(filings_by_type.values(), key=lambda x: x["priority"])
    print(f"      SEC EDGAR: {len(result)} Filing(s) fuer {ticker} (CIK {cik_int}).")
    return result


# keep old name as alias so any existing callers continue to work
def find_sec_filings(ticker: str) -> list[dict]:
    """Deprecated alias — resolves CIK then calls get_sec_filings()."""
    cik = get_sec_cik(ticker)
    if not cik:
        return []
    return get_sec_filings(ticker, cik)


# ── 2b. HTML document loader ──────────────────────────────────────────────────

_HTML_PRIORITY_KEYWORDS = [
    "revenue", "net sales", "guidance", "outlook", "forward",
    "earnings per share", "eps", "free cash flow", "fcf",
    "operating income", "ebitda", "segment results", "fiscal year",
    "next year", "net income", "dividend", "buyback", "capex",
]

_MAX_HTML_CHARS = 60_000


def load_html_document(url: str, doc_type: str = "unknown",
                       ticker: str = "") -> list:
    """
    Fetches *url*, strips boilerplate HTML, extracts relevant text sections,
    caps at _MAX_HTML_CHARS (60 000 chars), and returns LangChain Document chunks.

    Priority sections (paragraphs/tables containing _HTML_PRIORITY_KEYWORDS)
    are prepended so they land in the first chunks and score highest in
    similarity search.

    Cache: ./ir_cache/{ticker}/{url_hash}.html  (24-hour TTL).
    SEC EDGAR URLs automatically use the SEC-compliant User-Agent.
    """
    url_hash   = hashlib.md5(url.encode()).hexdigest()[:8]
    # Per-ticker cache dir when ticker is known, otherwise shared _html dir
    cache_dir  = Path(CACHE_DIR) / (ticker if ticker else "_html")
    cache_path = cache_dir / f"{url_hash}.html"

    raw_text: str = ""
    if cache_path.exists():
        try:
            age_h = (time.time() - cache_path.stat().st_mtime) / 3600
            if age_h < CACHE_MAX_AGE_HOURS:
                raw_text = cache_path.read_text(encoding="utf-8")
        except Exception:
            pass

    if not raw_text:
        # SEC EDGAR requires a different User-Agent (email address mandatory)
        req_headers = _SEC_HEADERS if "sec.gov" in url else _HEADERS
        try:
            r = requests.get(url, headers=req_headers, timeout=30, allow_redirects=True)
            r.raise_for_status()
        except Exception as exc:
            print(f"      HTML laden fehlgeschlagen ({url[:60]}...): {exc}")
            return []

        soup = BeautifulSoup(r.text, "html.parser")

        # Remove noise tags
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "noscript", "iframe", "form", "button"]):
            tag.decompose()

        # Prefer semantic content containers
        content_root = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id=re.compile(r"content|main|body", re.I))
            or soup.body
            or soup
        )

        # Collect text blocks (paragraphs, table rows, headings)
        priority_blocks: list[str] = []
        normal_blocks:   list[str] = []

        for elem in content_root.find_all(
            ["p", "li", "td", "th", "h1", "h2", "h3", "h4", "caption"]
        ):
            text = elem.get_text(" ", strip=True)
            if len(text) < 20:
                continue
            lower = text.lower()
            if any(kw in lower for kw in _HTML_PRIORITY_KEYWORDS):
                priority_blocks.append(text)
            else:
                normal_blocks.append(text)

        combined = "\n".join(priority_blocks) + "\n" + "\n".join(normal_blocks)
        raw_text = combined[:_MAX_HTML_CHARS]

        # Persist to cache
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(raw_text, encoding="utf-8")
        except Exception:
            pass

    if not raw_text.strip():
        return []

    doc = Document(
        page_content=raw_text,
        metadata={"source": url, "type": doc_type, "format": "html", "page": "N/A"},
    )
    chunks = _splitter.split_documents([doc])
    for i, chunk in enumerate(chunks):
        chunk.metadata.update(
            {"source": url, "type": doc_type, "format": "html", "page": i}
        )
    return chunks


# ── 2. Find IR PDFs ───────────────────────────────────────────────────────────

def find_ir_pdfs(ir_url: str, ticker: str = "") -> list[dict]:
    """
    Scrapes *ir_url* for IR documents.  Three-stage strategy:

    Stage 1 (always): scan for <a href="*.pdf"> links (existing logic).
    Stage 2 (PDF fallback): if no PDFs found, scan <a> text for IR keywords
      and return matching HTML links (marked format="html").
    Stage 3 (SEC fallback): if still empty AND ticker is a plain US ticker,
      call find_sec_filings() as last resort.

    Returns up to 4 entries, each with:
      {url, filename, type, priority, year, text, format, source}
    """
    # ── SEC EDGAR URL: extract CIK and fetch filings directly ────────────────
    if ir_url and "sec.gov" in ir_url:
        cik_match = re.search(r"CIK=(\d+)", ir_url)
        cik = cik_match.group(1) if cik_match else None
        if not cik and ticker:
            cik = get_sec_cik(ticker)
        if cik:
            return get_sec_filings(ticker, cik)
        # CIK unresolvable — fall through to generic scraping below

    if not ir_url:
        if ticker and _sec_is_us_ticker(ticker):
            cik = get_sec_cik(ticker)
            if cik:
                return get_sec_filings(ticker, cik)
        return []

    try:
        r = requests.get(ir_url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
    except Exception:
        if ticker and _sec_is_us_ticker(ticker):
            cik = get_sec_cik(ticker)
            if cik:
                return get_sec_filings(ticker, cik)
        return []

    soup     = BeautifulSoup(r.text, "html.parser")
    parsed   = urlparse(ir_url)
    base_dom = f"{parsed.scheme}://{parsed.netloc}"

    found: list[dict] = []
    seen:  set[str]   = set()

    def _resolve(href: str) -> str:
        href = href.strip()
        if href.startswith("//"):
            return parsed.scheme + ":" + href
        if href.startswith("/"):
            return base_dom + href
        if not href.startswith("http"):
            return urljoin(ir_url, href)
        return href

    # ── Stage 1: PDF links ────────────────────────────────────────────────────
    for a in soup.find_all("a", href=True):
        href = _resolve(a["href"])
        if not href.lower().endswith(".pdf"):
            continue
        if href in seen:
            continue
        seen.add(href)

        filename  = href.split("/")[-1].split("?")[0] or "document.pdf"
        link_text = a.get_text(" ", strip=True)
        label     = (link_text + " " + filename + " " + href).lower()

        if any(kw in label for kw in EXCLUDE_KEYWORDS):
            continue

        pdf_type = "other"
        priority = 99
        for t, p, any_kws, all_kws in _PDF_TYPE_RULES:
            hit_any = any(kw in label for kw in any_kws) if any_kws else True
            hit_all = all(kw in label for kw in all_kws) if all_kws else True
            if hit_any and hit_all:
                pdf_type = t
                priority = p
                break

        if pdf_type == "other":
            continue

        year_match = re.search(r"20[12][0-9]", label)
        year = int(year_match.group()) if year_match else 0

        found.append({
            "url":      href,
            "filename": filename,
            "type":     pdf_type,
            "priority": priority,
            "year":     year,
            "text":     link_text,
            "format":   "pdf",
            "source":   "IR website PDF",
        })

    if found:
        found.sort(key=lambda x: (x["priority"], -x["year"]))
        return found[:4]

    # ── Stage 1b: Follow report sub-pages (EU/CH multi-level IR sites) ────────
    # Many European IR sites have PDFs only 1-2 clicks below the landing page.
    # We collect same-domain links whose path contains a report-index keyword,
    # visit each sub-page, and search for PDFs there.
    if not (ticker and _sec_is_us_ticker(ticker)):
        subpage_candidates: list[str] = []
        for a in soup.find_all("a", href=True):
            href = _resolve(a["href"])
            if urlparse(href).netloc != parsed.netloc:
                continue
            if href in seen or href == ir_url:
                continue
            path_lower = urlparse(href).path.lower().rstrip("/")
            if any(kw in path_lower for kw in _SUBPAGE_FOLLOW_PATTERNS):
                subpage_candidates.append(href)

        seen_sub: set[str] = set()
        for subpage_url in subpage_candidates[:8]:
            if subpage_url in seen_sub:
                continue
            seen_sub.add(subpage_url)
            print(f"      Suche PDFs auf Sub-Seite: {subpage_url[:80]}...")
            try:
                r2 = requests.get(subpage_url, headers=_HEADERS, timeout=12)
                if r2.status_code != 200 or len(r2.content) < 500:
                    continue
                soup2 = BeautifulSoup(r2.text, "html.parser")

                for a in soup2.find_all("a", href=True):
                    raw_href = a["href"].strip()
                    # Resolve relative to the sub-page URL (not the original ir_url)
                    if raw_href.startswith("//"):
                        href2 = parsed.scheme + ":" + raw_href
                    elif raw_href.startswith("/"):
                        href2 = base_dom + raw_href
                    elif not raw_href.startswith("http"):
                        href2 = urljoin(subpage_url, raw_href)
                    else:
                        href2 = raw_href

                    if not href2.lower().endswith(".pdf"):
                        continue
                    if href2 in seen:
                        continue
                    seen.add(href2)

                    filename  = href2.split("/")[-1].split("?")[0] or "document.pdf"
                    link_text = a.get_text(" ", strip=True)
                    label     = (link_text + " " + filename + " " + href2).lower()

                    if any(kw in label for kw in EXCLUDE_KEYWORDS):
                        continue

                    pdf_type, priority = "other", 99
                    for t, p, any_kws, all_kws in _PDF_TYPE_RULES:
                        hit_any = any(kw in label for kw in any_kws) if any_kws else True
                        hit_all = all(kw in label for kw in all_kws) if all_kws else True
                        if hit_any and hit_all:
                            pdf_type, priority = t, p
                            break

                    # EU/CH fallback: classify by filename pattern
                    if pdf_type == "other":
                        if _EU_PDF_ANNUAL.search(label):
                            pdf_type, priority = "annual_report", 3
                        elif _EU_PDF_INTERIM.search(label):
                            pdf_type, priority = "interim_report", 4
                        else:
                            continue

                    year_match = re.search(r"20[12][0-9]", label)
                    year = int(year_match.group()) if year_match else 0

                    found.append({
                        "url":      href2,
                        "filename": filename,
                        "type":     pdf_type,
                        "priority": priority,
                        "year":     year,
                        "text":     link_text,
                        "format":   "pdf",
                        "source":   "IR sub-page PDF",
                    })

            except Exception:
                continue

            if found:
                break  # stop after first sub-page that yields PDFs

        if found:
            found.sort(key=lambda x: (x["priority"], -x["year"]))
            return found[:4]

    # ── Stage 2: HTML links with IR keyword anchors ───────────────────────────
    print(f"      Keine PDFs gefunden auf {ir_url[:60]} — suche HTML IR-Links...")
    html_found: list[dict] = []

    for a in soup.find_all("a", href=True):
        href = _resolve(a["href"])
        if href in seen:
            continue
        # Skip obvious non-content URLs
        ext = href.split("?")[0].rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "gif", "svg", "css", "js", "xml", "zip"):
            continue
        seen.add(href)

        link_text = a.get_text(" ", strip=True)
        label     = (link_text + " " + href).lower()

        if any(kw in label for kw in EXCLUDE_KEYWORDS):
            continue
        if not any(kw in label for kw in _HTML_IR_KEYWORDS):
            continue

        # Classify using the same priority rules (applied to label)
        html_type = "other"
        priority  = 99
        for t, p, any_kws, all_kws in _PDF_TYPE_RULES:
            hit_any = any(kw in label for kw in any_kws) if any_kws else True
            hit_all = all(kw in label for kw in all_kws) if all_kws else True
            if hit_any and hit_all:
                html_type = t
                priority  = p
                break

        # Also classify by HTML IR keywords when PDF rules don't match
        if html_type == "other":
            if any(kw in label for kw in ["10-k", "10k", "annual report"]):
                html_type, priority = "annual_report", 3
            elif any(kw in label for kw in ["10-q", "10q", "quarterly results", "interim"]):
                html_type, priority = "interim_report", 4
            elif any(kw in label for kw in ["earnings", "press release", "financial results"]):
                html_type, priority = "earnings_release", 1
            elif any(kw in label for kw in ["presentation", "investor presentation"]):
                html_type, priority = "analyst_presentation", 2
            else:
                continue

        year_match = re.search(r"20[12][0-9]", label)
        year = int(year_match.group()) if year_match else 0
        filename = href.split("/")[-1].split("?")[0] or "page.html"
        if not filename.endswith((".htm", ".html", ".aspx", ".php")):
            filename += ".html"

        html_found.append({
            "url":      href,
            "filename": filename,
            "type":     html_type,
            "priority": priority,
            "year":     year,
            "text":     link_text,
            "format":   "html",
            "source":   "IR website HTML",
        })

    if html_found:
        html_found.sort(key=lambda x: (x["priority"], -x["year"]))
        return html_found[:4]

    # ── Stage 3: SEC EDGAR fallback for US tickers ───────────────────────────
    if ticker and _sec_is_us_ticker(ticker):
        print(f"      Kein IR-Dokument auf Website — versuche SEC EDGAR fuer {ticker}...")
        cik = get_sec_cik(ticker)
        if cik:
            return get_sec_filings(ticker, cik)

    return []


# ── 3. Download PDF ───────────────────────────────────────────────────────────

def download_pdf(pdf_url: str, save_path: str) -> bool:
    """
    Downloads *pdf_url* to *save_path*.
    Enforces 50 MB size limit.  Returns True on success.
    """
    filename = os.path.basename(save_path)
    try:
        r = requests.get(pdf_url, headers=_HEADERS, timeout=30,
                         stream=True, allow_redirects=True)
        r.raise_for_status()

        # Pre-flight size check from Content-Length header
        content_length = int(r.headers.get("content-length", 0))
        if content_length > _MAX_FILE_BYTES:
            size_mb = content_length / 1024 / 1024
            print(f"      Überspringe {filename} ({size_mb:.1f}MB — Limit: 50MB)")
            return False

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        bytes_written = 0
        with open(save_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                bytes_written += len(chunk)
                if bytes_written > _MAX_FILE_BYTES:
                    fh.close()
                    os.remove(save_path)
                    print(f"      Überspringe {filename} (>50MB während Download)")
                    return False
                fh.write(chunk)

        size_mb = bytes_written / 1024 / 1024
        print(f"      Lade PDF: {filename} ({size_mb:.1f}MB)")
        return True
    except Exception as exc:
        print(f"      Fehler beim Download {filename}: {exc}")
        return False


# ── 4. Load document ──────────────────────────────────────────────────────────

def load_document(file_path: str, doc_type: str = "unknown") -> list:
    """
    Loads *file_path* (.pdf / .pptx / .docx), splits into chunks.
    Returns list of Document chunks with metadata, or [] on failure.
    """
    filename = os.path.basename(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    raw_docs: list[Document] = []

    try:
        if ext == ".pdf":
            loader   = PyPDFLoader(file_path)
            raw_docs = loader.load()

        elif ext == ".pptx":
            if not _PPTX_AVAILABLE:
                print(f"      python-pptx nicht installiert — überspringe {filename}")
                return []
            prs = _PptxPresentation(file_path)
            for slide_num, slide in enumerate(prs.slides, 1):
                parts: list[str] = []
                for shape in slide.shapes:
                    try:
                        txt = shape.text.strip()
                        if txt:
                            parts.append(txt)
                    except AttributeError:
                        pass
                try:
                    if slide.has_notes_slide:
                        notes = slide.notes_slide.notes_text_frame.text.strip()
                        if notes:
                            parts.append(f"[Notes] {notes}")
                except Exception:
                    pass
                slide_text = "\n".join(parts)
                if slide_text.strip():
                    raw_docs.append(Document(
                        page_content=slide_text,
                        metadata={"page": slide_num},
                    ))

        elif ext == ".docx":
            if not _DOCX_AVAILABLE:
                print(f"      Docx2txtLoader nicht verfügbar — überspringe {filename}")
                return []
            loader   = Docx2txtLoader(file_path)
            raw_docs = loader.load()

        else:
            return []

    except Exception as exc:
        print(f"      Fehler beim Laden {filename}: {exc}")
        return []

    chunks = _splitter.split_documents(raw_docs)
    for chunk in chunks:
        chunk.metadata.update({
            "source":   filename,
            "type":     doc_type,
            "page":     chunk.metadata.get("page", "N/A"),
        })
    return chunks


# ── 5. Build vectorstore ──────────────────────────────────────────────────────

def build_vectorstore(ticker: str, documents: list, source_urls: list[str]):
    """
    Returns FAISS vectorstore.
    Loads from cache if metadata.json is younger than CACHE_MAX_AGE_HOURS;
    otherwise builds from *documents* and persists to cache.
    Returns None if *documents* is empty and no valid cache exists.
    """
    cache_dir = Path(CACHE_DIR) / ticker
    meta_file = cache_dir / "metadata.json"
    index_file = cache_dir / "index.faiss"

    # Try loading valid cache
    if meta_file.exists() and index_file.exists():
        try:
            meta  = json.loads(meta_file.read_text(encoding="utf-8"))
            age_h = (time.time() - meta["timestamp"]) / 3600
            if age_h < CACHE_MAX_AGE_HOURS:
                vs = FAISS.load_local(str(cache_dir), _get_emb(),
                                      allow_dangerous_deserialization=True)
                return vs
        except Exception:
            pass  # corrupt / stale — rebuild

    if not documents:
        return None

    vs = FAISS.from_documents(documents, _get_emb())

    cache_dir.mkdir(parents=True, exist_ok=True)
    vs.save_local(str(cache_dir))
    meta_file.write_text(json.dumps({
        "ticker":      ticker,
        "timestamp":   time.time(),
        "source_urls": source_urls,
        "doc_count":   len(documents),
    }), encoding="utf-8")

    return vs


# ── 6. @tool get_ir_analysis ──────────────────────────────────────────────────

_SYNTHESIS_SYSTEM = """\
You are a financial analyst. Extract structured data from IR document excerpts.
Return ONLY valid JSON — no explanatory text before or after.
Do NOT invent numbers. If a figure is not found in the context, write "not found".
Always cite the page or section for every extracted figure.\
"""

_SYNTHESIS_HUMAN = """\
Extract structured financial data from these IR document excerpts for {company} ({ticker}).

{context}

yfinance data for cross-checking:
{yf_data}

Return ONLY this JSON structure:
{{
  "adjusted_eps": <float or "not found">,
  "adjusted_eps_note": "<source page/section or explanation>",
  "free_cashflow_bn": <float in billions of home currency or "not found">,
  "free_cashflow_currency": "<CHF, USD, EUR, GBP or 'not found'>",
  "free_cashflow_note": "<source page/section>",
  "revenue_bn": <float in billions or "not found">,
  "revenue_currency": "<CHF, USD, EUR, GBP or 'not found'>",
  "ebitda_margin_pct": <float or "not found">,
  "recurring_ebit_margin_pct": <float or "not found">,
  "net_debt_bn": <float or "not found">,
  "capex_bn": <float or "not found">,
  "dividend_per_share": <float or "not found">,
  "dividend_currency": "<CHF, USD, EUR, GBP or 'not found'>",
  "guidance_2026": "<exact quote from document or 'not found'>",
  "guidance_2027": "<exact quote from document or 'not found'>",
  "consensus_eps_2026": <float or "not found">,
  "consensus_eps_2027": <float or "not found">,
  "consensus_eps_2028": <float or "not found">,
  "consensus_revenue_2026_bn": <float or "not found">,
  "consensus_revenue_2027_bn": <float or "not found">,
  "consensus_revenue_2028_bn": <float or "not found">,
  "management_tone": "<optimistic, neutral, or cautious>",
  "key_statements": ["<direct quote [Page X]>", "<direct quote [Page X]>"],
  "pe_distortion_explanation": "<explanation if P/E distorted by spin-off or one-time item, else 'none'>",
  "ir_sources": [],
  "data_quality": "<high, medium, or low>",
  "yfinance_discrepancies": ["<description of any figure differing from yfinance by >10%>"]
}}\
"""

_EMPTY_IR: dict = {
    "adjusted_eps":              "not found",
    "adjusted_eps_note":         "not found",
    "free_cashflow_bn":          "not found",
    "free_cashflow_currency":    "not found",
    "free_cashflow_note":        "not found",
    "revenue_bn":                "not found",
    "revenue_currency":          "not found",
    "ebitda_margin_pct":         "not found",
    "recurring_ebit_margin_pct": "not found",
    "net_debt_bn":               "not found",
    "capex_bn":                  "not found",
    "dividend_per_share":        "not found",
    "dividend_currency":         "not found",
    "guidance_2026":             "not found",
    "guidance_2027":             "not found",
    "consensus_eps_2026":        "not found",
    "consensus_eps_2027":        "not found",
    "consensus_eps_2028":        "not found",
    "consensus_revenue_2026_bn": "not found",
    "consensus_revenue_2027_bn": "not found",
    "consensus_revenue_2028_bn": "not found",
    "management_tone":           "neutral",
    "key_statements":            [],
    "pe_distortion_explanation": "none",
    "ir_sources":                [],
    "data_quality":              "low",
    "yfinance_discrepancies":    [],
}


@tool
def get_ir_analysis(ticker: str) -> dict:
    """
    RAG-basierte Analyse von IR-Dokumenten (Geschäftsbericht, Consensus Estimates,
    Earnings Presentation). Extrahiert EPS, FCF, Guidance und Konsensdaten direkt
    aus den Quelldokumenten. Liefert strukturiertes JSON inkl. yfinance-Crosscheck.
    """
    # Get company name from yfinance
    company_name = ticker
    try:
        company_name = yf.Ticker(ticker).info.get("longName", ticker)
    except Exception:
        pass

    cache_dir = Path(CACHE_DIR) / ticker
    meta_file = cache_dir / "metadata.json"

    # ── Check whether a fresh cache already covers us ────────────────────────
    cache_fresh  = False
    source_urls: list[str] = []

    if meta_file.exists():
        try:
            meta  = json.loads(meta_file.read_text(encoding="utf-8"))
            age_h = (time.time() - meta["timestamp"]) / 3600
            if age_h < CACHE_MAX_AGE_HOURS:
                cache_fresh = True
                source_urls = meta.get("source_urls", [])
        except Exception:
            pass

    # ── Steps 1-4: find, download, process (skipped when cache is fresh) ─────
    all_chunks: list = []

    if not cache_fresh:
        # Step 1: Find IR URL
        ir_url = find_ir_url(ticker, company_name)
        if not ir_url:
            print(f"      IR-Seite fuer {ticker} nicht gefunden.")

        # Step 2: Find documents (PDFs, HTML, or SEC filings)
        pdfs = find_ir_pdfs(ir_url, ticker=ticker)
        if not pdfs:
            print(f"      Keine IR-Dokumente fuer {ticker} gefunden.")

        # Step 3 + 4: Load each document — route by format
        for doc_info in pdfs:
            fmt = doc_info.get("format", "pdf")

            if fmt == "html":
                # HTML documents: fetch + parse directly (no local download)
                print(f"      Lade HTML: {doc_info['url'][:70]}...")
                chunks = load_html_document(
                    doc_info["url"], doc_type=doc_info["type"], ticker=ticker
                )
                if chunks:
                    # Stamp source label so the LLM knows provenance
                    source_label = doc_info.get("source", "IR website HTML")
                    for chunk in chunks:
                        chunk.metadata["source"] = source_label
                    all_chunks.extend(chunks)
                    source_urls.append(doc_info["url"])
            else:
                # PDF documents: download then load (existing logic)
                save_path = str(cache_dir / doc_info["filename"])
                if download_pdf(doc_info["url"], save_path):
                    chunks = load_document(save_path, doc_type=doc_info["type"])
                    if chunks:
                        all_chunks.extend(chunks)
                        source_urls.append(doc_info["url"])

    if not all_chunks and not cache_fresh:
        result = {**_EMPTY_IR, "error": f"Keine IR-Dokumente für {ticker} gefunden."}
        result["ir_sources"] = source_urls
        return result

    # ── Step 5: Build / load vectorstore ────────────────────────────────────
    vs = build_vectorstore(ticker, all_chunks, source_urls)
    if vs is None:
        result = {**_EMPTY_IR, "error": "Vectorstore konnte nicht erstellt werden."}
        result["ir_sources"] = source_urls
        return result

    # ── Step 6: Query with STANDARD_QUERIES (top 4 chunks each) ─────────────
    context_parts: list[str] = []
    for query in STANDARD_QUERIES:
        try:
            docs = vs.similarity_search(query, k=4)
            if docs:
                context_parts.append(f"\n=== {query.upper()} ===")
                for doc in docs:
                    page = doc.metadata.get("page", "N/A")
                    src  = doc.metadata.get("source", "N/A")
                    context_parts.append(
                        f"[Page {page} | {src}] {doc.page_content[:400]}"
                    )
        except Exception:
            pass

    # Cap context to stay within reasonable token limits
    context = "\n".join(context_parts)[:12000]

    # yfinance cashflow for cross-check
    yf_data: dict = {}
    try:
        yf_data = get_cashflow_data.invoke(ticker)
    except Exception:
        pass

    # ── Step 7: Claude synthesises into structured dict ──────────────────────
    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYNTHESIS_SYSTEM),
        ("human",  _SYNTHESIS_HUMAN),
    ])

    try:
        raw_json: str = (prompt | _get_llm() | StrOutputParser()).invoke({
            "ticker":   ticker,
            "company":  company_name,
            "context":  context,
            "yf_data":  json.dumps(yf_data, ensure_ascii=False),
        })
        s = raw_json.find("{")
        e = raw_json.rfind("}") + 1
        result = json.loads(raw_json[s:e]) if s != -1 and e > 0 else {**_EMPTY_IR}
    except Exception as exc:
        result = {**_EMPTY_IR, "error": str(exc)}

    result["ir_sources"] = source_urls
    return result


# ── 7. Consensus estimates from IR ───────────────────────────────────────────

_DERIVE_SYSTEM = """\
Du bist ein erfahrener Buy-Side Analyst der Forward-Estimates erstellt.
Nutze IR-Guidance, historische Wachstumsraten, Management Tone und Sektordynamiken.
Sei konservativ und erkläre jede Annahme explizit mit ihrer Herleitung.
Antworte AUSSCHLIESSLICH mit validem JSON.\
"""

_GUIDANCE_DERIVE_HUMAN = """\
Unternehmen: {ticker} (Sektor: {sector})

MANAGEMENT GUIDANCE (aus IR-Dokument):
Guidance 2026: {guidance_2026}
Guidance 2027: {guidance_2027}

AKTUELLE KENNZAHLEN (letztes Geschäftsjahr):
Umsatz: {revenue_bn} Mrd. {currency}
EBITDA-Marge: {ebitda_margin_pct}%
EPS (bereinigt): {adjusted_eps}

HISTORISCHE DATEN:
{historical_data}

AUFGABE:
1. Parse den Guidance-Text und extrahiere konkrete Zielwerte für 2026E
2. Extrapoliere 2027E und 2028E mit historischem CAGR und Sektordurchschnitt
3. Sei konservativ — im Zweifelsfall niedrigere Wachstumsrate

Antworte NUR mit diesem JSON:
{{
  "estimates": {{
    "2026E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "Management Guidance"}},
    "2027E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "extrapoliert"}},
    "2028E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "extrapoliert"}}
  }},
  "key_assumptions": [
    "<Annahme 1: konkrete Guidance-Quelle und Herleitung>",
    "<Annahme 2: CAGR-Annahme für 2027E/2028E mit Begründung>"
  ]
}}\
"""

_DERIVE_HUMAN = """\
Erstelle 3-Jahres Forward-Estimates für {ticker} (Sektor: {sector}).

IR-ANALYSE:
{ir_output}

HISTORISCHE DATEN:
{historical_data}

Konfidenz-Regeln:
- hoch:    IR-Guidance vorhanden UND historische Daten vollständig
- mittel:  nur historische Daten ODER unvollständige Guidance
- niedrig: keine Guidance, nur Sektordurchschnitte als Basis

JSON-Format (kein erklärender Text):
{{
  "source": "LLM-Ableitung aus IR-Dokumenten und historischen Daten",
  "confidence": "hoch" | "mittel" | "niedrig",
  "estimates": {{
    "2026E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "derived"}},
    "2027E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "derived"}},
    "2028E": {{"revenue_bn": <Mrd.>, "ebitda_margin_pct": <Prozent>, "eps": <EPS>, "source": "derived"}}
  }},
  "key_assumptions": [
    "<Annahme 1: Herleitung + Quelle>",
    "<Annahme 2: Herleitung + Quelle>",
    "<Annahme 3: Herleitung + Quelle>"
  ],
  "disclaimer": "Diese Schätzungen stammen aus öffentlichen IR-Dokumenten / wurden vom LLM abgeleitet. Kein Ersatz für Bloomberg/FactSet Konsensdaten."
}}\
"""

_ESTIMATE_FALLBACK: dict = {
    "source":      "LLM-Ableitung — Analyse nicht verfügbar",
    "confidence":  "niedrig",
    "estimates": {
        "2026E": {"revenue_bn": "n/v", "ebitda_margin_pct": "n/v", "eps": "n/v", "source": "n/v"},
        "2027E": {"revenue_bn": "n/v", "ebitda_margin_pct": "n/v", "eps": "n/v", "source": "n/v"},
        "2028E": {"revenue_bn": "n/v", "ebitda_margin_pct": "n/v", "eps": "n/v", "source": "n/v"},
    },
    "key_assumptions": [],
    "disclaimer": (
        "Diese Schätzungen stammen aus öffentlichen IR-Dokumenten / wurden vom LLM abgeleitet. "
        "Kein Ersatz für Bloomberg/FactSet Konsensdaten."
    ),
}


def consensus_estimates_from_ir(
    ticker: str,
    ir_output: dict,
    historical_data: dict,
    sector: str = "",
) -> dict:
    """
    Returns 3-year forward estimates (2026E/2027E/2028E).
    NOT a @tool — called directly by fundamental_agent.

    Fast path: if the IR document already contains consensus_eps and
    consensus_revenue (e.g. Holcim publishes their own consensus sheet),
    those are returned directly without an LLM call.
    """
    def _is_found(v) -> bool:
        return v not in (None, "not found", "n/v", "")

    # ── Fast path: direct IR consensus figures ───────────────────────────────
    eps_2026 = ir_output.get("consensus_eps_2026")
    eps_2027 = ir_output.get("consensus_eps_2027")
    eps_2028 = ir_output.get("consensus_eps_2028")
    rev_2026 = ir_output.get("consensus_revenue_2026_bn")
    rev_2027 = ir_output.get("consensus_revenue_2027_bn")
    rev_2028 = ir_output.get("consensus_revenue_2028_bn")

    if all(_is_found(v) for v in [eps_2026, eps_2027, eps_2028,
                                   rev_2026, rev_2027, rev_2028]):
        return {
            "source":     "IR-Dokument (Consensus Estimates)",
            "confidence": "hoch",
            "estimates": {
                "2026E": {"revenue_bn": rev_2026, "ebitda_margin_pct": ir_output.get("ebitda_margin_pct", "n/v"), "eps": eps_2026, "source": "direct from IR"},
                "2027E": {"revenue_bn": rev_2027, "ebitda_margin_pct": "n/v",                                    "eps": eps_2027, "source": "direct from IR"},
                "2028E": {"revenue_bn": rev_2028, "ebitda_margin_pct": "n/v",                                    "eps": eps_2028, "source": "direct from IR"},
            },
            "key_assumptions": [
                f"Direkt aus IR-Consensus-Dokument entnommen ({', '.join(ir_output.get('ir_sources', ['IR']))}).",
                "Keine LLM-Ableitung — Zahlen stammen unverändert aus dem Unternehmensdokument.",
            ],
            "methodology": "Zahlen direkt aus dem vom Unternehmen publizierten Consensus Sheet übernommen.",
            "disclaimer": (
                "Keine Bloomberg/FactSet Konsensdaten. Quelle: IR Consensus Sheet (direkt vom Unternehmen). "
                "Kein Ersatz für professionelle Konsensdaten."
            ),
        }

    # ── Priority 2: Management Guidance from IR ───────────────────────────────
    guidance_2026 = ir_output.get("guidance_2026")
    guidance_2027 = ir_output.get("guidance_2027")
    revenue_bn    = ir_output.get("revenue_bn")
    ebitda_margin = ir_output.get("ebitda_margin_pct")

    if _is_found(guidance_2026) and _is_found(revenue_bn) and _is_found(ebitda_margin):
        guidance_prompt = ChatPromptTemplate.from_messages([
            ("system", _DERIVE_SYSTEM),
            ("human",  _GUIDANCE_DERIVE_HUMAN),
        ])
        try:
            raw_json: str = (guidance_prompt | _get_llm() | StrOutputParser()).invoke({
                "ticker":           ticker,
                "sector":           sector or "unbekannt",
                "guidance_2026":    guidance_2026,
                "guidance_2027":    guidance_2027 if _is_found(guidance_2027) else "nicht verfügbar",
                "revenue_bn":       revenue_bn,
                "currency":         ir_output.get("revenue_currency", ""),
                "ebitda_margin_pct": ebitda_margin,
                "adjusted_eps":     ir_output.get("adjusted_eps", "nicht verfügbar"),
                "historical_data":  json.dumps(historical_data, ensure_ascii=False),
            })
            s = raw_json.find("{")
            e = raw_json.rfind("}") + 1
            if s != -1 and e > 0:
                parsed = json.loads(raw_json[s:e])
                ir_sources = ir_output.get("ir_sources", ["IR-Dokument"])
                return {
                    "source":     "Management Guidance (IR-Dokument)",
                    "confidence": "mittel-hoch",
                    "estimates":  parsed["estimates"],
                    "key_assumptions": parsed.get("key_assumptions", [])
                        + [f"Guidance-Quelle: {', '.join(ir_sources)}"],
                    "methodology": (
                        "2026E direkt aus Management Guidance abgeleitet. "
                        "2027E/2028E via historischem CAGR extrapoliert."
                    ),
                    "disclaimer": (
                        f"Keine Bloomberg/FactSet Konsensdaten. Quelle: Management Guidance (IR-Dokument). "
                        "Kein Ersatz für professionelle Konsensdaten."
                    ),
                }
        except Exception:
            pass  # fall through to Priority 3

    # ── Priority 3: LLM derivation fallback ──────────────────────────────────
    prompt = ChatPromptTemplate.from_messages([
        ("system", _DERIVE_SYSTEM),
        ("human",  _DERIVE_HUMAN),
    ])

    try:
        raw_json: str = (prompt | _get_llm() | StrOutputParser()).invoke({
            "ticker":          ticker,
            "sector":          sector or "unbekannt",
            "ir_output":       json.dumps(ir_output,       ensure_ascii=False),
            "historical_data": json.dumps(historical_data, ensure_ascii=False),
        })
        s = raw_json.find("{")
        e = raw_json.rfind("}") + 1
        if s != -1 and e > 0:
            result = json.loads(raw_json[s:e])
            result.setdefault("methodology", "LLM-Ableitung aus IR-Dokumenten und historischen Daten.")
            result["disclaimer"] = (
                f"Keine Bloomberg/FactSet Konsensdaten. Quelle: LLM-Ableitung aus IR-Dokumenten. "
                "Kein Ersatz für professionelle Konsensdaten."
            )
            return result
    except Exception:
        pass

    return _ESTIMATE_FALLBACK.copy()


# ── Smoke test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    print("=== IR RAG Tool Test: HOLN.SW ===")
    result = get_ir_analysis.invoke("HOLN.SW")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
