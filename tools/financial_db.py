"""
tools/financial_db.py — SQLite financial data store

Persistent store for annual and quarterly financial data.
Sources (in priority order): yfinance, sec_xbrl, ir_pdf
DB location: DATA_DIR/financials.db (Railway volume) or ./financials.db locally.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH: Path | None = None
_CONN: sqlite3.Connection | None = None

_FINANCIAL_COLS = [
    "revenue_bn", "gross_profit_bn", "ebitda_bn", "ebit_bn",
    "net_income_bn", "interest_bn",
    "operating_cf_bn", "capex_bn", "fcf_bn", "da_bn",
    "total_debt_bn", "total_cash_bn", "net_debt_bn",
    "total_equity_bn", "total_assets_bn", "invested_capital_bn",
    "eps_adj", "dps", "shares_bn",
    "ebitda_margin_pct", "ebit_margin_pct", "fcf_margin_pct", "net_margin_pct",
]

_SOURCE_PRIORITY = {"sec_xbrl": 3, "ir_pdf": 2.5, "yfinance": 2}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS financial_data (
    ticker            TEXT    NOT NULL,
    fiscal_year       INTEGER NOT NULL,
    period_type       TEXT    NOT NULL,
    quarter           TEXT    DEFAULT NULL,
    period_end        TEXT,
    currency          TEXT,
    revenue_bn        REAL, gross_profit_bn  REAL, ebitda_bn       REAL,
    ebit_bn           REAL, net_income_bn    REAL, interest_bn     REAL,
    operating_cf_bn   REAL, capex_bn         REAL, fcf_bn          REAL,
    da_bn             REAL, total_debt_bn    REAL, total_cash_bn   REAL,
    net_debt_bn       REAL, total_equity_bn  REAL, total_assets_bn REAL,
    invested_capital_bn REAL, eps_adj        REAL, dps             REAL,
    shares_bn         REAL, ebitda_margin_pct REAL, ebit_margin_pct REAL,
    fcf_margin_pct    REAL, net_margin_pct   REAL,
    source            TEXT,
    quality_score     INTEGER DEFAULT 2,
    fetched_at        TEXT,
    PRIMARY KEY (ticker, fiscal_year, period_type, quarter)
);
CREATE INDEX IF NOT EXISTS idx_fin_ticker_year
    ON financial_data(ticker, fiscal_year);
"""


def get_db_path() -> Path:
    data_dir = os.environ.get("DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "financials.db"
    return Path(__file__).resolve().parent.parent / "financials.db"


def _get_conn() -> sqlite3.Connection:
    global _CONN, _DB_PATH
    path = get_db_path()
    if _CONN is None or _DB_PATH != path:
        _DB_PATH = path
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
    return _CONN


def init_db(db_path: Path | None = None) -> None:
    """Create tables if they don't exist. Idempotent."""
    global _CONN, _DB_PATH
    if db_path:
        _DB_PATH = db_path
        _CONN = None
    conn = _get_conn()
    conn.executescript(_CREATE_TABLE)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_real(v: Any) -> float | None:
    """Convert value to float or None."""
    if v is None or v == "not found" or v == "n/v" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _compute_margins(row: dict) -> dict:
    """Compute derived margin fields where possible."""
    out: dict = {}
    rev = _safe_real(row.get("revenue_bn"))
    ni  = _safe_real(row.get("net_income_bn"))
    eb  = _safe_real(row.get("ebitda_bn"))
    ebit = _safe_real(row.get("ebit_bn"))
    fcf  = _safe_real(row.get("fcf_bn"))

    if rev and rev > 0:
        if eb  is not None: out["ebitda_margin_pct"] = round(eb  / rev * 100, 2)
        if ebit is not None: out["ebit_margin_pct"]  = round(ebit / rev * 100, 2)
        if ni  is not None: out["net_margin_pct"]   = round(ni  / rev * 100, 2)
        if fcf is not None: out["fcf_margin_pct"]   = round(fcf / rev * 100, 2)
    return out


def upsert_financials(rows: list[dict]) -> int:
    """
    Bulk-upsert rows into financial_data.

    Priority logic:
    - sec_xbrl (priority 3) overwrites yfinance/ir_pdf for years older than current
    - yfinance (priority 2) always valid; doesn't overwrite existing sec_xbrl for same year
    - ir_pdf fills NULLs only (doesn't overwrite existing non-null values)

    Returns number of rows upserted.
    """
    if not rows:
        return 0

    conn = _get_conn()
    upserted = 0

    for row in rows:
        ticker      = row.get("ticker", "")
        fiscal_year = row.get("fiscal_year")
        period_type = row.get("period_type", "annual")
        quarter     = row.get("quarter")  # None for annual
        source      = row.get("source", "yfinance")
        new_prio    = _SOURCE_PRIORITY.get(source, 2)

        if not ticker or not fiscal_year:
            continue

        # Compute missing margins
        margins = _compute_margins(row)

        # Check existing row
        cur = conn.execute(
            "SELECT source, quality_score FROM financial_data "
            "WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter IS ?",
            (ticker, fiscal_year, period_type, quarter),
        )
        existing = cur.fetchone()

        if existing:
            existing_prio = _SOURCE_PRIORITY.get(existing["source"] or "yfinance", 2)
            if source == "ir_pdf":
                # ir_pdf only fills NULLs
                updates = []
                params  = []
                for col in _FINANCIAL_COLS:
                    val = _safe_real(row.get(col)) or margins.get(col)
                    if val is not None:
                        updates.append(f"{col} = COALESCE({col}, ?)")
                        params.append(val)
                if updates:
                    params += [ticker, fiscal_year, period_type, quarter]
                    conn.execute(
                        f"UPDATE financial_data SET {', '.join(updates)} "
                        "WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter IS ?",
                        params,
                    )
                    upserted += 1
            elif new_prio >= existing_prio:
                # Higher or equal priority → full overwrite of financial cols
                sets = {}
                for col in _FINANCIAL_COLS:
                    val = _safe_real(row.get(col)) or margins.get(col)
                    if val is not None:
                        sets[col] = val
                sets["source"]        = source
                sets["quality_score"] = row.get("quality_score", 2)
                sets["fetched_at"]    = _now_iso()
                if row.get("period_end"):
                    sets["period_end"] = row["period_end"]
                if row.get("currency"):
                    sets["currency"] = row["currency"]
                if sets:
                    cols   = ", ".join(f"{k}=?" for k in sets)
                    params = list(sets.values()) + [ticker, fiscal_year, period_type, quarter]
                    conn.execute(
                        f"UPDATE financial_data SET {cols} "
                        "WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter IS ?",
                        params,
                    )
                    upserted += 1
        else:
            # Insert new row
            all_cols  = ["ticker", "fiscal_year", "period_type", "quarter",
                         "period_end", "currency", "source", "quality_score", "fetched_at"]
            all_vals  = [ticker, fiscal_year, period_type, quarter,
                         row.get("period_end"), row.get("currency"),
                         source, row.get("quality_score", 2), _now_iso()]

            for col in _FINANCIAL_COLS:
                val = _safe_real(row.get(col)) or margins.get(col)
                all_cols.append(col)
                all_vals.append(val)

            placeholders = ", ".join("?" * len(all_cols))
            conn.execute(
                f"INSERT INTO financial_data ({', '.join(all_cols)}) VALUES ({placeholders})",
                all_vals,
            )
            upserted += 1

    conn.commit()
    return upserted


def get_annual_history(ticker: str, n_years: int = 10) -> list[dict]:
    """Return up to n_years annual rows, newest first."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM financial_data "
        "WHERE ticker=? AND period_type='annual' "
        "ORDER BY fiscal_year DESC LIMIT ?",
        (ticker, n_years),
    )
    return [dict(r) for r in cur.fetchall()]


def get_annual_years_present(ticker: str) -> set[int]:
    """Fiscal years for which *ticker* already has an annual row with revenue."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT fiscal_year FROM financial_data "
        "WHERE ticker=? AND period_type='annual' AND revenue_bn IS NOT NULL",
        (ticker,),
    )
    return {r[0] for r in cur.fetchall()}


def get_quarterly_history(ticker: str, n_quarters: int = 12) -> list[dict]:
    """Return up to n_quarters quarterly rows, newest first."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM financial_data "
        "WHERE ticker=? AND period_type='quarterly' "
        "ORDER BY fiscal_year DESC, quarter DESC LIMIT ?",
        (ticker, n_quarters),
    )
    return [dict(r) for r in cur.fetchall()]


def has_sufficient_data(ticker: str, min_annual_years: int = 4) -> bool:
    """True if DB has at least min_annual_years of annual data for ticker."""
    conn = _get_conn()
    cur = conn.execute(
        "SELECT COUNT(*) FROM financial_data "
        "WHERE ticker=? AND period_type='annual' AND revenue_bn IS NOT NULL",
        (ticker,),
    )
    count = cur.fetchone()[0]
    return count >= min_annual_years


def get_db_stats() -> dict:
    """Summary stats for /db/stats API endpoint."""
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM financial_data").fetchone()[0]
    tickers = conn.execute(
        "SELECT COUNT(DISTINCT ticker) FROM financial_data"
    ).fetchone()[0]
    annual = conn.execute(
        "SELECT COUNT(*) FROM financial_data WHERE period_type='annual'"
    ).fetchone()[0]
    quarterly = conn.execute(
        "SELECT COUNT(*) FROM financial_data WHERE period_type='quarterly'"
    ).fetchone()[0]
    latest = conn.execute(
        "SELECT ticker, MAX(fetched_at) as last_update "
        "FROM financial_data GROUP BY ticker ORDER BY last_update DESC LIMIT 10"
    ).fetchall()
    return {
        "total_rows":     total,
        "distinct_tickers": tickers,
        "annual_rows":    annual,
        "quarterly_rows": quarterly,
        "db_path":        str(get_db_path()),
        "recent_tickers": [{"ticker": r["ticker"], "last_update": r["last_update"]}
                           for r in latest],
    }
