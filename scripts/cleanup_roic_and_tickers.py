"""
scripts/cleanup_roic_and_tickers.py — Einmaliger Cleanup nach den Fixes vom Sept. 2026

1. ROIC-Reset (--reset-roic): yfinance-ROIC wurde bis Sept. 2026 mit Yahoos
   "Invested Capital" berechnet, das z.T. nur das Eigenkapital ist (Nestlé: ROIC
   ~29 % statt ~13 %). Upserts füllen nur NULL-Felder, falsche Altwerte bleiben
   also stehen. Setzt roic_pct und invested_capital_bn aller Jahreszeilen auf
   NULL — der yfinance-Gap-Fill (höchstens 1x/Tag je Ticker) füllt sie beim
   nächsten Analyse-Lauf mit der korrigierten Formel (EK + Nettoverschuldung) neu.

2. Ticker-Reset (--ticker, mehrfach): löscht alle Zeilen eines Tickers, z.B.
   RIEN.SW (Halbjahresbericht als Jahresbericht eingestuft → falsche/fehlende
   IR-Werte). Der nächste Lauf baut ihn aus yfinance + IR komplett neu auf.

Aufruf (lokal: SQLite; auf Railway: Postgres über DATABASE_URL):
    python scripts/cleanup_roic_and_tickers.py --reset-roic --ticker RIEN.SW --dry-run
    python scripts/cleanup_roic_and_tickers.py --reset-roic --ticker RIEN.SW
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="ROIC-Reset und Ticker-Reset in financial_data.")
    parser.add_argument("--reset-roic", action="store_true",
                        help="roic_pct/invested_capital_bn aller Jahreszeilen auf NULL setzen")
    parser.add_argument("--ticker", action="append", default=[],
                        help="Alle Zeilen dieses Tickers löschen (mehrfach möglich)")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nichts ändern")
    args = parser.parse_args()
    if not args.reset_roic and not args.ticker:
        parser.error("--reset-roic und/oder --ticker angeben")

    from tools.financial_db import _BACKEND, _conn, _sql, delete_ticker, init_db, _masked_dsn

    init_db()
    print(f"Backend: {_BACKEND}" + (f" ({_masked_dsn()})" if _BACKEND == "postgres" else ""))
    mode = "DRY-RUN" if args.dry_run else "wird geändert"

    for t in (x.upper() for x in args.ticker):
        with _conn() as conn:
            n = conn.execute(_sql("SELECT COUNT(*) AS n FROM financial_data WHERE ticker=?"), (t,)).fetchone()
        n = dict(n)["n"]
        print(f"  {t}: {n} Zeilen ({mode})")
        if not args.dry_run:
            print(f"    gelöscht: {delete_ticker(t)}")

    if args.reset_roic:
        where = ("WHERE period_type='annual' "
                 "AND (roic_pct IS NOT NULL OR invested_capital_bn IS NOT NULL)")
        with _conn() as conn:
            rows = [dict(r) for r in conn.execute(_sql(
                f"SELECT ticker, COUNT(*) AS n FROM financial_data {where} GROUP BY ticker ORDER BY ticker"))]
            print(f"  ROIC-Reset: {sum(r['n'] for r in rows)} Jahreszeilen in {len(rows)} Tickern ({mode})")
            for r in rows:
                print(f"    {r['ticker']}: {r['n']}")
            if not args.dry_run:
                cur = conn.execute(_sql(
                    f"UPDATE financial_data SET roic_pct = NULL, invested_capital_bn = NULL {where}"))
                conn.commit()
                print(f"    zurückgesetzt: {cur.rowcount}")

    if args.dry_run:
        print("Dry-Run — nichts geändert. Ohne --dry-run erneut ausführen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
