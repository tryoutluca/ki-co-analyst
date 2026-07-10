"""
scripts/cleanup_ytd_quarters.py — Einmaliger Cleanup YTD-kontaminierter Quartalszeilen

Vor Phase 7.2 (Perioden-Dauer-Filter in tools/xbrl_fetcher.py) konnten kumulierte
6M-/9M-YTD-Fakten aus SEC-XBRL-10-Q-Filings fälschlich als einzelnes Quartal in
financial_data (period_type='quarterly', source='sec_xbrl') gelandet sein.

Heuristik: eine Quartalszeile ist verdächtig, wenn ihr revenue_bn mehr als
--threshold (Default 60%) des Jahresumsatzes (annual, gleicher Ticker, gleiches
fiscal_year) ausmacht — ein echtes Einzelquartal liegt für die allermeisten
Geschäftsmodelle deutlich darunter.

Verdächtige Zeilen werden gelöscht, damit der nächste fetch_xbrl_quarterly()-Lauf
sie mit dem neuen Dauer-Filter sauber neu schreibt.

Aufruf:
    python scripts/cleanup_ytd_quarters.py --dry-run
    python scripts/cleanup_ytd_quarters.py --ticker NVDA
    python scripts/cleanup_ytd_quarters.py --threshold 0.55
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _find_suspects(ticker: str, threshold: float) -> list[dict]:
    from tools.financial_db import get_annual_history, get_quarterly_history

    annual_by_year = {r["fiscal_year"]: r for r in get_annual_history(ticker, n_years=100)}
    quarters = get_quarterly_history(ticker, n_quarters=1000)

    suspects = []
    for q in quarters:
        if q.get("source") != "sec_xbrl":
            continue
        rev = q.get("revenue_bn")
        if rev is None:
            continue
        annual_row = annual_by_year.get(q.get("fiscal_year"))
        if annual_row is None:
            continue
        annual_rev = annual_row.get("revenue_bn")
        if not annual_rev or annual_rev <= 0:
            continue
        if rev > threshold * annual_rev:
            suspects.append(q)
    return suspects


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Löscht YTD-kontaminierte SEC-XBRL-Quartalszeilen (vor Phase 7.2)."
    )
    parser.add_argument("--ticker", type=str, default=None,
                         help="Nur diesen Ticker prüfen (Default: alle Ticker in der DB)")
    parser.add_argument("--threshold", type=float, default=0.6,
                         help="Schwelle Quartalsumsatz/Jahresumsatz, ab der eine Zeile verdächtig ist (Default 0.6)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Nur anzeigen, nichts löschen")
    args = parser.parse_args()

    from tools.financial_db import init_db, get_ticker_overview, delete_period

    init_db()
    tickers = [args.ticker] if args.ticker else [t["ticker"] for t in get_ticker_overview()]

    found = 0
    deleted = 0
    for ticker in tickers:
        suspects = _find_suspects(ticker, args.threshold)
        for q in suspects:
            found += 1
            print(f"  {ticker} FY{q['fiscal_year']} {q['quarter']}: "
                  f"revenue_bn={q['revenue_bn']} "
                  f"({'DRY-RUN' if args.dry_run else 'wird gelöscht'})")
            if not args.dry_run:
                deleted += delete_period(ticker, q["fiscal_year"], "quarterly", q["quarter"])

    print("=" * 60)
    print(f"Verdächtige Quartalszeilen gefunden: {found}")
    if args.dry_run:
        print("Dry-Run — nichts gelöscht. Ohne --dry-run erneut ausführen zum Löschen.")
    else:
        print(f"Gelöscht: {deleted}")
        print("Nächster Analyse-Lauf schreibt diese Quartale mit dem Dauer-Filter neu.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
