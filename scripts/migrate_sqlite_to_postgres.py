"""
scripts/migrate_sqlite_to_postgres.py — Einmalige Migration financials.db → Postgres

Liest alle Zeilen aus der lokalen/Volume-SQLite (financials.db) und schreibt sie
per Upsert (tools.financial_db.upsert_financials — identische Prioritäts- und
COALESCE-Fill-Logik wie im Live-Betrieb) nach Postgres. Idempotent: mehrfaches
Ausführen überschreibt nur, was laut Quellen-Priorität überschrieben werden darf.

Voraussetzung: DATABASE_URL zeigt auf die Ziel-Postgres-Instanz (Railway).
Die Quelle wird unabhängig davon direkt per sqlite3 gelesen (SQLITE_SOURCE_PATH
oder DATA_DIR/financials.db als Default), damit die Backend-Umschaltung in
tools/financial_db.py nicht kollidiert.

Aufruf:
    DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py
    DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py --source /pfad/financials.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_BATCH_SIZE = 200


def _default_sqlite_path() -> Path:
    data_dir = os.environ.get("DATA_DIR", "")
    if data_dir:
        return Path(data_dir) / "financials.db"
    return ROOT / "financials.db"


def _read_sqlite_rows(sqlite_path: Path) -> list[dict]:
    """Liest alle Zeilen direkt aus der SQLite-Quelle (bypass tools.financial_db)."""
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM financial_data")
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migriert financials.db (SQLite) nach Postgres.")
    parser.add_argument("--source", type=str, default=None,
                         help="Pfad zur SQLite-Quelldatei (Default: DATA_DIR/financials.db)")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL", "").strip():
        print("❌ DATABASE_URL ist nicht gesetzt — Zielsystem (Postgres) unbekannt. Abbruch.")
        return 1

    sqlite_path = Path(args.source) if args.source else _default_sqlite_path()
    if not sqlite_path.exists():
        print(f"❌ SQLite-Quelle nicht gefunden: {sqlite_path}")
        return 1

    print(f"Quelle:  {sqlite_path}")
    print(f"Ziel:    Postgres (DATABASE_URL gesetzt)")
    print("Lese Zeilen aus SQLite...")
    rows = _read_sqlite_rows(sqlite_path)
    print(f"  {len(rows)} Zeilen gelesen.\n")

    # Import erst NACH dem DATABASE_URL-Check, damit tools.financial_db das
    # Postgres-Backend wählt (Backend-Wahl passiert beim Modul-Import).
    from tools.financial_db import init_db, upsert_financials

    print("Initialisiere Postgres-Schema...")
    init_db()

    written  = 0
    read     = len(rows)
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i:i + _BATCH_SIZE]
        n = upsert_financials(batch)
        written += n
        print(f"  Batch {i // _BATCH_SIZE + 1}: "
              f"{i + len(batch)}/{read} gelesen, {written} bisher geschrieben")

    skipped = read - written

    print("\n" + "=" * 60)
    print("MIGRATION ABGESCHLOSSEN")
    print(f"  Zeilen gelesen:      {read}")
    print(f"  Zeilen geschrieben:  {written}  (Insert oder tatsächliche Änderung)")
    print(f"  Zeilen übersprungen: {skipped}  (niedrigere Quellen-Priorität / keine Änderung)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
