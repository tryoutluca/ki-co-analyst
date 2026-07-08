"""
tools/financial_db.py — Financial data store (SQLite lokal / Postgres via DATABASE_URL)

Persistent store for annual and quarterly financial data.
Sources (in priority order): sec_xbrl, ir_pdf, yfinance

Backend-Auswahl:
  - DATABASE_URL gesetzt (Railway-Managed-Postgres) → psycopg (v3) + psycopg_pool.
  - sonst → lokales SQLite (DATA_DIR/financials.db oder ./financials.db).

Postgres-Besonderheit (siehe db/schema_postgres.sql): quarter ist dort
NOT NULL DEFAULT '' statt NULL (Primary-Key-Constraints behandeln zwei NULLs
nie als gleich, SQLite dagegen erlaubt "quarter IS ?" für den NULL-Vergleich).
Der Sentinel wird intern beim Schreiben gesetzt (_quarter_key) und beim Lesen
wieder zu None normalisiert (_denorm) — nach aussen ist das Verhalten für
beide Backends identisch.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_BACKEND = "postgres" if _DATABASE_URL else "sqlite"

_DB_PATH: Path | None = None
_CONN: sqlite3.Connection | None = None      # SQLite-Pfad: eine langlebige Verbindung
_POOL = None                                  # Postgres-Pfad: psycopg_pool.ConnectionPool

# Nur im SQLite-Pfad nötig: eine einzelne Verbindung wird über Background-
# Threads geteilt. Im Postgres-Pfad regelt der Connection-Pool die
# Nebenläufigkeit selbst (jeder Aufruf leiht sich eine eigene Verbindung).
_WRITE_LOCK = threading.Lock()

DB_STALENESS_DAYS = int(os.environ.get("DB_STALENESS_DAYS", "30"))

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

_CREATE_TABLE_SQLITE = """
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

# Vergleichsoperator für den quarter-Spalten-Match: SQLite muss "IS" nutzen
# (quarter ist bei annual-Zeilen echtes NULL), Postgres nutzt den '' Sentinel
# und kann daher ganz normal auf Gleichheit vergleichen.
_QUARTER_CMP = "IS ?" if _BACKEND == "sqlite" else "= ?"


def _sql(query: str) -> str:
    """Übersetzt das '?'-Platzhalter-Schema (SQLite) nach '%s' (Postgres)."""
    return query.replace("?", "%s") if _BACKEND == "postgres" else query


def _quarter_key(quarter: Any) -> Any:
    """Normalisiert quarter fürs Schreiben: Postgres-Sentinel '' statt NULL."""
    if _BACKEND == "postgres":
        return quarter if quarter else ""
    return quarter


def _denorm(row: dict | None) -> dict | None:
    """Kehrt _quarter_key() beim Lesen um — Aufrufer sehen immer None für annual."""
    if row is None:
        return None
    if _BACKEND == "postgres" and row.get("quarter") == "":
        row["quarter"] = None
    return row


def get_db_path() -> Path:
    """SQLite-Dateipfad (nur relevant im SQLite-Backend)."""
    data_dir = os.environ.get("DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "financials.db"
    return Path(__file__).resolve().parent.parent / "financials.db"


def _masked_dsn() -> str:
    """Postgres-DSN mit maskiertem Passwort (für /db/stats-Ausgabe)."""
    return re.sub(r"://([^:/]+):([^@]+)@", r"://\1:***@", _DATABASE_URL)


def _get_conn() -> sqlite3.Connection:
    """Liefert die persistente SQLite-Verbindung (nur SQLite-Backend)."""
    global _CONN, _DB_PATH
    path = get_db_path()
    if _CONN is None or _DB_PATH != path:
        _DB_PATH = path
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _CONN.execute("PRAGMA busy_timeout=5000;")
    return _CONN


def _get_pool():
    """Liefert den psycopg-Connection-Pool (nur Postgres-Backend), lazy erstellt."""
    global _POOL
    if _POOL is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        _POOL = ConnectionPool(
            _DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _POOL


@contextmanager
def _conn():
    """
    Liefert eine DB-API-Verbindung für das aktive Backend.
    SQLite: die eine langlebige Verbindung (kein Teardown).
    Postgres: eine aus dem Pool geliehene Verbindung (wird beim Verlassen des
    with-Blocks automatisch committed/zurückgegeben — siehe psycopg_pool docs).
    """
    if _BACKEND == "postgres":
        with _get_pool().connection() as conn:
            yield conn
    else:
        yield _get_conn()


def init_db(db_path: Path | None = None) -> None:
    """Erstellt das Schema falls nicht vorhanden. Idempotent. Backend nach DATABASE_URL."""
    if _BACKEND == "postgres":
        schema_file = Path(__file__).resolve().parent.parent / "db" / "schema_postgres.sql"
        ddl = schema_file.read_text(encoding="utf-8")
        with _conn() as conn:
            for stmt in ddl.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()
        print(f"      DB (Postgres): Schema initialisiert ({_masked_dsn()})")
        return

    global _CONN, _DB_PATH
    if db_path:
        _DB_PATH = db_path
        _CONN = None
    conn = _get_conn()
    conn.executescript(_CREATE_TABLE_SQLITE)
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


def _upsert_one(conn, row: dict) -> int:
    """Upsert-Logik für eine einzelne Zeile — von upsert_financials() pro Zeile aufgerufen."""
    ticker      = row.get("ticker", "")
    fiscal_year = row.get("fiscal_year")
    period_type = row.get("period_type", "annual")
    quarter     = _quarter_key(row.get("quarter"))
    source      = row.get("source", "yfinance")
    new_prio    = _SOURCE_PRIORITY.get(source, 2)

    if not ticker or not fiscal_year:
        return 0

    margins = _compute_margins(row)

    cur = conn.execute(_sql(
        "SELECT source, quality_score FROM financial_data "
        f"WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter {_QUARTER_CMP}"),
        (ticker, fiscal_year, period_type, quarter),
    )
    existing = cur.fetchone()
    existing = dict(existing) if existing else None

    if existing:
        existing_prio = _SOURCE_PRIORITY.get(existing["source"] or "yfinance", 2)
        if source == "ir_pdf":
            # ir_pdf only fills NULLs
            updates = []
            params  = []
            for col in _FINANCIAL_COLS:
                val = _safe_real(row.get(col))
                if val is None:
                    val = margins.get(col)
                if val is not None:
                    updates.append(f"{col} = COALESCE({col}, ?)")
                    params.append(val)
            if not updates:
                return 0
            updates.append("fetched_at = ?")
            params.append(_now_iso())
            params += [ticker, fiscal_year, period_type, quarter]
            conn.execute(_sql(
                f"UPDATE financial_data SET {', '.join(updates)} "
                f"WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter {_QUARTER_CMP}"),
                params,
            )
            return 1
        elif new_prio >= existing_prio:
            # Higher or equal priority → full overwrite of financial cols
            sets = {}
            for col in _FINANCIAL_COLS:
                val = _safe_real(row.get(col))
                if val is None:
                    val = margins.get(col)
                if val is not None:
                    sets[col] = val
            sets["source"]        = source
            sets["quality_score"] = row.get("quality_score", 2)
            sets["fetched_at"]    = _now_iso()
            if row.get("period_end"):
                sets["period_end"] = row["period_end"]
            if row.get("currency"):
                sets["currency"] = row["currency"]
            if not sets:
                return 0
            cols   = ", ".join(f"{k}=?" for k in sets)
            params = list(sets.values()) + [ticker, fiscal_year, period_type, quarter]
            conn.execute(_sql(
                f"UPDATE financial_data SET {cols} "
                f"WHERE ticker=? AND fiscal_year=? AND period_type=? AND quarter {_QUARTER_CMP}"),
                params,
            )
            return 1
        return 0
    else:
        # Insert new row
        all_cols  = ["ticker", "fiscal_year", "period_type", "quarter",
                     "period_end", "currency", "source", "quality_score", "fetched_at"]
        all_vals  = [ticker, fiscal_year, period_type, quarter,
                     row.get("period_end"), row.get("currency"),
                     source, row.get("quality_score", 2), _now_iso()]

        for col in _FINANCIAL_COLS:
            val = _safe_real(row.get(col))
            if val is None:
                val = margins.get(col)
            all_cols.append(col)
            all_vals.append(val)

        placeholders = ", ".join("?" * len(all_cols))
        insert_sql = f"INSERT INTO financial_data ({', '.join(all_cols)}) VALUES ({placeholders})"
        if _BACKEND == "postgres":
            # Sicherheitsnetz für parallele Pool-Verbindungen, die zwischen
            # obigem SELECT und diesem INSERT denselben Key anlegen könnten.
            # SQLite serialisiert stattdessen über _WRITE_LOCK und braucht das nicht.
            insert_sql += " ON CONFLICT (ticker, fiscal_year, period_type, quarter) DO NOTHING"
        conn.execute(_sql(insert_sql), all_vals)
        return 1


def upsert_financials(rows: list[dict]) -> int:
    """
    Bulk-upsert rows into financial_data.

    Priority logic:
    - sec_xbrl (priority 3) overwrites yfinance/ir_pdf for years older than current
    - yfinance (priority 2) always valid; doesn't overwrite existing sec_xbrl for same year
    - ir_pdf fills NULLs only (doesn't overwrite existing non-null values)

    Returns number of rows upserted. Backend (SQLite/Postgres) via DATABASE_URL.
    """
    if not rows:
        return 0

    upserted = 0
    with _conn() as conn:
        if _BACKEND == "sqlite":
            with _WRITE_LOCK:
                for row in rows:
                    upserted += _upsert_one(conn, row)
                conn.commit()
        else:
            for row in rows:
                upserted += _upsert_one(conn, row)
            conn.commit()
    return upserted


def get_annual_history(ticker: str, n_years: int = 10) -> list[dict]:
    """Return up to n_years annual rows, newest first."""
    with _conn() as conn:
        cur = conn.execute(_sql(
            "SELECT * FROM financial_data "
            "WHERE ticker=? AND period_type='annual' "
            "ORDER BY fiscal_year DESC LIMIT ?"),
            (ticker, n_years),
        )
        return [_denorm(dict(r)) for r in cur.fetchall()]


def get_annual_years_present(ticker: str) -> set[int]:
    """Fiscal years for which *ticker* already has an annual row with revenue."""
    with _conn() as conn:
        cur = conn.execute(_sql(
            "SELECT fiscal_year FROM financial_data "
            "WHERE ticker=? AND period_type='annual' AND revenue_bn IS NOT NULL"),
            (ticker,),
        )
        return {dict(r)["fiscal_year"] for r in cur.fetchall()}


def get_quarterly_history(ticker: str, n_quarters: int = 12) -> list[dict]:
    """Return up to n_quarters quarterly rows, newest first."""
    with _conn() as conn:
        cur = conn.execute(_sql(
            "SELECT * FROM financial_data "
            "WHERE ticker=? AND period_type='quarterly' "
            "ORDER BY fiscal_year DESC, quarter DESC LIMIT ?"),
            (ticker, n_quarters),
        )
        return [_denorm(dict(r)) for r in cur.fetchall()]


def has_sufficient_data(ticker: str, min_annual_years: int = 4) -> bool:
    """True if DB has at least min_annual_years of annual data for ticker."""
    with _conn() as conn:
        cur = conn.execute(_sql(
            "SELECT COUNT(*) AS n FROM financial_data "
            "WHERE ticker=? AND period_type='annual' AND revenue_bn IS NOT NULL"),
            (ticker,),
        )
        row = cur.fetchone()
        count = dict(row)["n"] if row else 0
        return count >= min_annual_years


def get_newest_annual_row(ticker: str) -> dict | None:
    """Most recent annual row (by fiscal_year) for ticker, or None."""
    with _conn() as conn:
        cur = conn.execute(_sql(
            "SELECT * FROM financial_data "
            "WHERE ticker=? AND period_type='annual' AND revenue_bn IS NOT NULL "
            "ORDER BY fiscal_year DESC LIMIT 1"),
            (ticker,),
        )
        row = cur.fetchone()
        return _denorm(dict(row)) if row else None


def is_cache_fresh(ticker: str, min_annual_years: int = 4, staleness_days: int | None = None) -> bool:
    """
    True if the DB cache has enough annual history AND is not stale.

    Freshness holds if either the newest fiscal year is plausibly current
    (last or current calendar year) or the newest row's fetched_at is within
    staleness_days. Otherwise the caller should re-fetch and merge.
    """
    if not has_sufficient_data(ticker, min_annual_years=min_annual_years):
        return False

    newest = get_newest_annual_row(ticker)
    if newest is None:
        return False

    fiscal_year = newest.get("fiscal_year")
    current_year = datetime.now(timezone.utc).year
    if fiscal_year is not None and fiscal_year >= current_year - 1:
        return True

    fetched_at = newest.get("fetched_at")
    if not fetched_at:
        return False
    try:
        fetched_dt = datetime.fromisoformat(str(fetched_at))
        if fetched_dt.tzinfo is None:
            fetched_dt = fetched_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False

    if staleness_days is None:
        staleness_days = DB_STALENESS_DAYS
    age_days = (datetime.now(timezone.utc) - fetched_dt).days
    return age_days <= staleness_days


def get_db_stats() -> dict:
    """Summary stats for /db/stats API endpoint."""
    with _conn() as conn:
        total     = dict(conn.execute("SELECT COUNT(*) AS n FROM financial_data").fetchone())["n"]
        tickers   = dict(conn.execute("SELECT COUNT(DISTINCT ticker) AS n FROM financial_data").fetchone())["n"]
        annual    = dict(conn.execute("SELECT COUNT(*) AS n FROM financial_data WHERE period_type='annual'").fetchone())["n"]
        quarterly = dict(conn.execute("SELECT COUNT(*) AS n FROM financial_data WHERE period_type='quarterly'").fetchone())["n"]
        latest = conn.execute(
            "SELECT ticker, MAX(fetched_at) as last_update "
            "FROM financial_data GROUP BY ticker ORDER BY last_update DESC LIMIT 10"
        ).fetchall()
        latest = [dict(r) for r in latest]

    return {
        "total_rows":       total,
        "distinct_tickers": tickers,
        "annual_rows":      annual,
        "quarterly_rows":   quarterly,
        "backend":          _BACKEND,
        "db_path":          str(get_db_path()) if _BACKEND == "sqlite" else _masked_dsn(),
        "recent_tickers": [{"ticker": r["ticker"], "last_update": r["last_update"]}
                           for r in latest],
    }


def get_ticker_overview() -> list[dict]:
    """Per-ticker summary: row count, year span, annual rows, sources, last fetch."""
    agg = "STRING_AGG(DISTINCT source, ',')" if _BACKEND == "postgres" else "GROUP_CONCAT(DISTINCT source)"
    with _conn() as conn:
        cur = conn.execute(
            "SELECT ticker, "
            "COUNT(*) AS row_count, "
            "SUM(CASE WHEN period_type='annual' THEN 1 ELSE 0 END) AS annual_rows, "
            "SUM(CASE WHEN period_type='quarterly' THEN 1 ELSE 0 END) AS quarterly_rows, "
            "MIN(CASE WHEN period_type='annual' THEN fiscal_year END) AS first_year, "
            "MAX(CASE WHEN period_type='annual' THEN fiscal_year END) AS last_year, "
            f"{agg} AS sources, "
            "MAX(fetched_at) AS last_fetched_at "
            "FROM financial_data "
            "GROUP BY ticker "
            "ORDER BY ticker"
        )
        rows = [dict(r) for r in cur.fetchall()]

    for d in rows:
        d["sources"] = sorted(set((d.get("sources") or "").split(","))) if d.get("sources") else []
    return rows


def get_ticker_data(ticker: str) -> dict:
    """All rows for a ticker, split into annual/quarterly, newest first."""
    return {
        "ticker":    ticker,
        "annual":    get_annual_history(ticker, n_years=100),
        "quarterly": get_quarterly_history(ticker, n_quarters=1000),
    }


def delete_ticker(ticker: str) -> int:
    """Delete all rows for a ticker. Returns the number of deleted rows."""
    with _conn() as conn:
        if _BACKEND == "sqlite":
            with _WRITE_LOCK:
                cur = conn.execute(_sql("DELETE FROM financial_data WHERE ticker=?"), (ticker,))
                conn.commit()
                return cur.rowcount
        cur = conn.execute(_sql("DELETE FROM financial_data WHERE ticker=?"), (ticker,))
        conn.commit()
        return cur.rowcount
