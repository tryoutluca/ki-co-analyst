"""
scripts/cleanup_ytd_quarters.py — Einmaliger Cleanup fehlerhafter Quartals-/Periodenzeilen

Zwei Bereinigungs-Durchgänge:

1. YTD-Kontamination (Phase 7.2): vor dem Perioden-Dauer-Filter in
   tools/xbrl_fetcher.py konnten kumulierte 6M-/9M-YTD-Fakten aus SEC-XBRL-
   10-Q-Filings fälschlich als einzelnes Quartal in financial_data
   (period_type='quarterly', source='sec_xbrl') landen. Heuristik: eine
   Quartalszeile ist verdächtig, wenn ihr revenue_bn mehr als --threshold
   (Default 60%) des Jahresumsatzes (annual, gleicher Ticker, gleiches
   fiscal_year) ausmacht.

2. Label-Duplikate (Phase 7.3): vor der zentralen Fiskal-Label-Zuordnung
   (assign_fiscal_label) konnten ir_pdf und sec_xbrl für dieselbe
   Berichtsperiode (identisches period_end, gleicher ticker/period_type)
   unterschiedliche (fiscal_year, quarter)-Labels vergeben und so als zwei
   separate Zeilen landen. Von jeder solchen Gruppe wird die Zeile mit der
   niedrigeren Quellen-Priorität gelöscht, die mit der höchsten bleibt.

Beide Durchgänge löschen nur — der nächste Analyse-Lauf schreibt die
betroffenen Perioden mit den reparierten Extraktionspfaden sauber neu.

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


def _find_period_end_duplicates(ticker: str) -> list[dict]:
    """
    Findet Zeilengruppen mit identischem (ticker, period_type, period_end)
    aber unterschiedlichem (fiscal_year, quarter)-Label. Gibt pro Duplikat
    {"period_type", "winner", "loser"} zurück — winner behält die höhere
    Quellen-Priorität, loser wird gelöscht.
    """
    from tools.financial_db import get_annual_history, get_quarterly_history, source_priority

    dupes = []
    for period_type, rows in (
        ("annual", get_annual_history(ticker, n_years=100)),
        ("quarterly", get_quarterly_history(ticker, n_quarters=1000)),
    ):
        by_period_end: dict[str, list[dict]] = {}
        for r in rows:
            pe = r.get("period_end")
            if not pe:
                continue
            by_period_end.setdefault(pe, []).append(r)

        for pe, group in by_period_end.items():
            labels = {(r["fiscal_year"], r.get("quarter")) for r in group}
            if len(labels) <= 1:
                continue  # keine Divergenz — nichts zu tun
            ranked = sorted(group, key=lambda r: source_priority(r.get("source")), reverse=True)
            winner = ranked[0]
            for loser in ranked[1:]:
                if (loser["fiscal_year"], loser.get("quarter")) == (winner["fiscal_year"], winner.get("quarter")):
                    continue  # gleiches Label wie winner, kein echtes Duplikat
                dupes.append({"period_type": period_type, "winner": winner, "loser": loser})
    return dupes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Löscht YTD-kontaminierte Quartalszeilen (7.2) und Label-Duplikate (7.3)."
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
    print(f"Verdächtige Quartalszeilen (YTD-Kontamination) gefunden: {found}")
    if args.dry_run:
        print("Dry-Run — nichts gelöscht.")
    else:
        print(f"Gelöscht: {deleted}")
    print("=" * 60)

    print("\nSuche Label-Duplikate (identisches period_end, abweichendes Label)...")
    dup_found = 0
    dup_deleted = 0
    for ticker in tickers:
        for dupe in _find_period_end_duplicates(ticker):
            winner, loser, period_type = dupe["winner"], dupe["loser"], dupe["period_type"]
            dup_found += 1
            w_label = f"{winner['fiscal_year']}" + (f"/{winner['quarter']}" if winner.get("quarter") else "")
            l_label = f"{loser['fiscal_year']}" + (f"/{loser['quarter']}" if loser.get("quarter") else "")
            print(f"  {ticker} {loser['period_end']}: behalte {winner['source']} {w_label}, "
                  f"lösche {loser['source']} {l_label} "
                  f"({'DRY-RUN' if args.dry_run else 'wird gelöscht'})")
            if not args.dry_run:
                dup_deleted += delete_period(ticker, loser["fiscal_year"], period_type, loser.get("quarter"))

    print("=" * 60)
    print(f"Label-Duplikate gefunden: {dup_found}")
    if args.dry_run:
        print("Dry-Run — nichts gelöscht. Ohne --dry-run erneut ausführen zum Löschen.")
    else:
        print(f"Gelöscht: {dup_deleted}")
        print("Nächster Analyse-Lauf schreibt diese Perioden mit den reparierten Extraktionspfaden neu.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
