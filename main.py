import sys
import os
import json
import subprocess
from dotenv import load_dotenv
import yfinance as yf

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from graph.graph import run_analysis

# ── Bekannte Ticker mit Exchange-Suffix ─────────────────────────────────────

KNOWN_SWISS_TICKERS = [
    "HOLN", "NESN", "NOVN", "ROG", "UBSG",
    "CSGN", "ABBN", "ZURN", "SREN", "GIVN",
    "LONN", "SLHN", "SCMN", "BALN", "GEBN",
    "KARN", "LISN", "BUCN", "CLAB", "TEMN"
]

KNOWN_GERMAN_TICKERS = [
    "SAP", "SIE", "BMW", "MBG", "BAS",
    "BAYN", "ALV", "DTE", "DBK", "MUV2"
]

KNOWN_LONDON_TICKERS = [
    "SHEL", "AZN", "HSBA", "BP", "GSK",
    "ULVR", "RIO", "BHP", "VOD", "LLOY"
]

# ── Ticker Validierung ───────────────────────────────────────────────────────

def validate_ticker(ticker: str) -> str:
    """
    Validiert und korrigiert Ticker-Symbole automatisch.
    Fügt Exchange-Suffix hinzu wenn nötig.
    """
    ticker = ticker.upper().strip()

    # Bereits mit Suffix → direkt zurückgeben
    if "." in ticker:
        print(f"  ✓ Ticker: {ticker}")
        return ticker

    # Bekannte Schweizer Ticker
    if ticker in KNOWN_SWISS_TICKERS:
        corrected = f"{ticker}.SW"
        print(f"  ✓ Schweizer Aktie erkannt → {corrected}")
        return corrected

    # Bekannte Deutsche Ticker
    if ticker in KNOWN_GERMAN_TICKERS:
        corrected = f"{ticker}.DE"
        print(f"  ✓ Deutsche Aktie erkannt → {corrected}")
        return corrected

    # Bekannte Londoner Ticker
    if ticker in KNOWN_LONDON_TICKERS:
        corrected = f"{ticker}.L"
        print(f"  ✓ Londoner Aktie erkannt → {corrected}")
        return corrected

    # Automatische Validierung via yfinance
    print(f"  Validiere Ticker {ticker}...")

    # US Ticker direkt prüfen
    stock = yf.Ticker(ticker)
    info = stock.info
    if info.get("currentPrice") or info.get("regularMarketPrice"):
        print(f"  ✓ US Ticker bestätigt: {ticker}")
        return ticker

    # Schweizer Suffix versuchen
    stock_sw = yf.Ticker(f"{ticker}.SW")
    info_sw = stock_sw.info
    if info_sw.get("currentPrice") or info_sw.get("regularMarketPrice"):
        corrected = f"{ticker}.SW"
        print(f"  ✓ Ticker korrigiert: {ticker} → {corrected}")
        return corrected

    # Deutsche Suffix versuchen
    stock_de = yf.Ticker(f"{ticker}.DE")
    info_de = stock_de.info
    if info_de.get("currentPrice") or info_de.get("regularMarketPrice"):
        corrected = f"{ticker}.DE"
        print(f"  ✓ Ticker korrigiert: {ticker} → {corrected}")
        return corrected

    # Nicht gefunden — original zurückgeben mit Warnung
    print(f"  ⚠ Ticker {ticker} nicht verifiziert.")
    print(f"    Tipp: Füge Exchange-Suffix manuell hinzu:")
    print(f"    Schweiz → {ticker}.SW")
    print(f"    Deutschland → {ticker}.DE")
    print(f"    London → {ticker}.L")
    print(f"    Euronext Paris → {ticker}.PA")
    return ticker


# ── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("  KI-Co-Analyst")
    print("  Berner Fachhochschule — Bachelor Thesis 2025/26")
    print("="*60)

    # Ticker Eingabe
    print("\nBitte geben Sie den Aktien-Ticker ein.")
    print("Beispiele: AAPL, MSFT, HOLN, NESN, SAP, HOLN.SW\n")
    ticker_input = input("Ticker: ").strip()

    if not ticker_input:
        print("Fehler: Kein Ticker eingegeben.")
        sys.exit(1)

    # Ticker validieren
    ticker = validate_ticker(ticker_input)

    # Bestätigung
    print(f"\nAnalyse wird gestartet für: {ticker}")
    print("Dies dauert ca. 60-90 Sekunden...\n")
    confirm = input("Weiter? (Enter zum Bestätigen, 'q' zum Abbrechen): ").strip()
    if confirm.lower() == 'q':
        print("Abgebrochen.")
        sys.exit(0)

    # Pipeline ausführen
    try:
        result = run_analysis(ticker)

        # JSON speichern
        safe_ticker = ticker.replace(".", "_")
        output_json = f"output_memo_{safe_ticker}.json"
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n✓ JSON gespeichert: {output_json}")

        # Word-Export via export_memo.js
        if not os.path.exists("export_memo.js"):
            print("⚠ export_memo.js nicht gefunden — Word-Export übersprungen.")
        else:
            output_docx = f"investment_memo_{safe_ticker}.docx"
            print(f"\nStarte Word-Export → {output_docx} ...")
            node_result = subprocess.run(
                ["node", "export_memo.js", output_json, output_docx],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if node_result.returncode == 0:
                print(f"✓ Word-Memo erstellt: {output_docx}")
                # Datei direkt öffnen
                os.startfile(os.path.abspath(output_docx))
            else:
                print(f"⚠ Word-Export Fehler:\n{node_result.stderr}")

    except Exception as e:
        print(f"\n❌ Fehler während der Analyse: {str(e)}")
        print("Bitte prüfen Sie:")
        print("  1. Ist der Ticker korrekt?")
        print("  2. Sind alle API Keys in der .env Datei?")
        print("  3. Ist die virtuelle Umgebung aktiv (venv)?")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()