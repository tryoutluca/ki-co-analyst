-- db/schema_postgres.sql — PostgreSQL-Schema für financial_data
-- (Railway-Managed-Postgres, extern per DBeaver/TablePlus zugänglich)
--
-- Abweichung vom SQLite-Schema (tools/financial_db.py):
--   quarter ist hier TEXT NOT NULL DEFAULT '' statt NULL. Zwei annual-Zeilen
--   mit quarter=NULL würden von Postgres' PRIMARY KEY nie als Duplikat erkannt
--   (NULL <> NULL in jedem Vergleich), SQLite dagegen erlaubt "quarter IS ?"
--   im Upsert-Pfad. '' steht hier für "annual" (kein Quartal). Die Python-
--   Schicht (tools/financial_db.py: _quarter_key/_denorm) normalisiert das
--   beim Schreiben/Lesen transparent, sodass Aufrufer immer None für annual
--   sehen — unabhängig vom Backend.
--
-- Idempotent: kann mehrfach ausgeführt werden (init_db() macht das bei jedem
-- Backend-Start).

CREATE TABLE IF NOT EXISTS financial_data (
    ticker              TEXT        NOT NULL,
    fiscal_year         INTEGER     NOT NULL,
    period_type         TEXT        NOT NULL CHECK (period_type IN ('annual', 'quarterly')),
    quarter             TEXT        NOT NULL DEFAULT '',
    period_end          TEXT,
    currency            TEXT,
    revenue_bn          DOUBLE PRECISION CHECK (revenue_bn IS NULL OR revenue_bn >= 0),
    gross_profit_bn     DOUBLE PRECISION,
    ebitda_bn           DOUBLE PRECISION,
    ebit_bn             DOUBLE PRECISION,
    net_income_bn       DOUBLE PRECISION,
    interest_bn         DOUBLE PRECISION,
    operating_cf_bn     DOUBLE PRECISION,
    capex_bn            DOUBLE PRECISION,
    fcf_bn              DOUBLE PRECISION,
    da_bn               DOUBLE PRECISION,
    total_debt_bn       DOUBLE PRECISION,
    total_cash_bn       DOUBLE PRECISION,
    net_debt_bn         DOUBLE PRECISION,
    total_equity_bn     DOUBLE PRECISION,
    total_assets_bn     DOUBLE PRECISION,
    invested_capital_bn DOUBLE PRECISION,
    eps_adj             DOUBLE PRECISION,
    dps                 DOUBLE PRECISION,
    shares_bn           DOUBLE PRECISION,
    ebitda_margin_pct   DOUBLE PRECISION,
    ebit_margin_pct     DOUBLE PRECISION,
    fcf_margin_pct      DOUBLE PRECISION,
    net_margin_pct      DOUBLE PRECISION,
    source              TEXT,
    quality_score       DOUBLE PRECISION DEFAULT 2,
    fetched_at          TIMESTAMPTZ,
    PRIMARY KEY (ticker, fiscal_year, period_type, quarter)
);

CREATE INDEX IF NOT EXISTS idx_fin_ticker_year
    ON financial_data (ticker, fiscal_year);

CREATE OR REPLACE VIEW qa_report AS
SELECT ticker,
       COUNT(*) FILTER (WHERE period_type='annual')             AS jahre,
       MAX(fiscal_year) FILTER (WHERE period_type='annual')     AS letztes_jahr,
       COUNT(*) FILTER (WHERE currency IS NULL OR currency='')  AS ohne_waehrung,
       COUNT(*) FILTER (WHERE revenue_bn IS NULL)               AS ohne_umsatz,
       MAX(fetched_at)                                          AS letztes_update
FROM financial_data
GROUP BY ticker;
