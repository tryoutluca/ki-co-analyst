"""
backend/pdf_generator.py — Investment Memo PDF Generator

Erzeugt ein professionelles Research-PDF aus dem SupervisorOutput-Dict.
Verwendet reportlab Platypus (keine externen System-Abhängigkeiten).
"""

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    Paragraph,
)

# ── Design-Farben ─────────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0a1628")
NAVY_LIGHT = colors.HexColor("#1a2d4a")
GOLD       = colors.HexColor("#c9a84c")
GREEN      = colors.HexColor("#1e7c45")
RED        = colors.HexColor("#dc2626")
AMBER      = colors.HexColor("#d97706")
SLATE_50   = colors.HexColor("#f8fafc")
SLATE_100  = colors.HexColor("#f1f5f9")
SLATE_200  = colors.HexColor("#e2e8f0")
SLATE_400  = colors.HexColor("#94a3b8")
SLATE_700  = colors.HexColor("#334155")
BLUE_50    = colors.HexColor("#eff6ff")
BLUE_400   = colors.HexColor("#60a5fa")
WHITE      = colors.white


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _s(text: Any) -> str:
    """Konvertiert zu String, ersetzt Nicht-Latin-1-Zeichen (Emoji etc.)."""
    t = str(text) if text is not None else ""
    return "".join(c if ord(c) < 256 else "?" for c in t)


def _num(v: Any, decimals: int = 2) -> str:
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return _s(v) if v else "-"


def _upside(v: Any) -> str:
    try:
        f = float(v)
        return f"+{abs(f):.1f}%" if f > 0 else f"{f:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _rec_color(rec: str) -> colors.Color:
    r = rec.upper()
    if "KAUF" in r or "UEBER" in r or "ÜBER" in r:
        return GREEN
    if "VERK" in r or "UNTER" in r:
        return RED
    return AMBER


def _style(**kw) -> ParagraphStyle:
    defaults = {
        "fontName": "Helvetica",
        "fontSize": 9,
        "textColor": SLATE_700,
        "leading": 13,
        "spaceAfter": 0,
        "spaceBefore": 0,
    }
    defaults.update(kw)
    return ParagraphStyle("_", **defaults)


def _section_head(title: str) -> list:
    """Gibt Abschnittstitel + Trennlinie zurück."""
    return [
        Spacer(1, 8),
        Paragraph(title.upper(), _style(
            fontName="Helvetica-Bold", fontSize=7,
            textColor=SLATE_400, spaceAfter=3,
        )),
        HRFlowable(width="100%", thickness=0.5, color=SLATE_200, spaceAfter=5),
    ]


# ── PDF-Erzeugung ─────────────────────────────────────────────────────────────

def generate_memo_pdf(data: dict) -> bytes:
    """Erzeugt ein Investment-Memo als PDF-Bytes aus dem Analyse-Dict."""

    buf = io.BytesIO()

    ticker  = _s(data.get("ticker", ""))
    company = _s(data.get("company", ""))
    rec     = _s(data.get("final_recommendation", "HALTEN"))
    date    = _s(data.get("date", datetime.now().strftime("%Y-%m-%d")))
    sector  = _s(data.get("sector", ""))
    conv    = _s(data.get("conviction_level", "-"))
    ccy     = _s(data.get("currency", ""))
    score   = data.get("data_consistency_score")

    price      = data.get("current_price")
    pt         = data.get("price_target")
    upside     = data.get("upside_downside_pct")
    mc_bn      = data.get("market_cap_bn")
    mktcap_str = f"{float(mc_bn):.1f} Mrd." if isinstance(mc_bn, (int, float)) else "n/v"

    bottom_line  = _s(data.get("summary_bottom_line", ""))
    exec_summary = _s(data.get("executive_summary", ""))
    company_desc = _s(data.get("company_description", ""))

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title=f"Investment Memo - {ticker}",
        author="KI-Co-Analyst",
    )

    W = A4[0] - 36 * mm  # Nutzbreite
    story: list = []

    # ── 1. HEADER ─────────────────────────────────────────────────────────────
    rec_clr = _rec_color(rec)
    header = Table(
        [[
            Paragraph(f"<font color='white'><b>{company}</b></font>",
                      _style(fontName="Helvetica-Bold", fontSize=18, textColor=WHITE, leading=22)),
            Paragraph(f"<font color='#{rec_clr.hexval()[1:]}'><b>{rec}</b></font>",
                      _style(fontName="Helvetica-Bold", fontSize=15, textColor=rec_clr,
                             alignment=TA_RIGHT)),
        ]],
        colWidths=[W * 0.68, W * 0.32],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("PADDING",    (0, 0), (-1, -1), 14),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header)

    sub = Table(
        [[
            Paragraph(f"<font color='#94a3b8'>{ticker}  |  {sector}  |  {date}</font>",
                      _style(fontSize=8, textColor=SLATE_400)),
            Paragraph(
                f"<font color='#94a3b8'>Conviction: {conv}  |  "
                f"Konsistenz: {score if score else '-'}/10</font>",
                _style(fontSize=8, textColor=SLATE_400, alignment=TA_RIGHT),
            ),
        ]],
        colWidths=[W * 0.6, W * 0.4],
    )
    sub.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",     (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 10),
        ("LEFTPADDING",    (0, 0), (-1, -1), 14),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 14),
    ]))
    story.append(sub)
    story.append(Spacer(1, 8))

    # ── 2. KPI-ZEILE ──────────────────────────────────────────────────────────
    upside_str = _upside(upside)
    try:
        up_f = float(upside)
        upside_clr = GREEN if up_f > 0 else RED
    except (TypeError, ValueError):
        upside_clr = SLATE_700

    kpi_labels = ["KURS", f"KURSZIEL (12M)", "UPSIDE / DW", "MARKTKAPITAL."]
    kpi_values = [
        f"{ccy} {_num(price)}",
        f"{ccy} {_num(pt)}",
        upside_str,
        mktcap_str,
    ]

    kpi_tbl = Table(
        [kpi_labels, kpi_values],
        colWidths=[W / 4] * 4,
    )
    kpi_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SLATE_100),
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("FONT",       (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("FONT",       (0, 1), (-1, 1), "Helvetica-Bold", 10),
        ("TEXTCOLOR",  (0, 0), (-1, 0), SLATE_400),
        ("TEXTCOLOR",  (0, 1), (-1, 1), SLATE_700),
        ("TEXTCOLOR",  (2, 1), (2, 1), upside_clr),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("GRID",  (0, 0), (-1, -1), 0.5, SLATE_200),
        ("BOX",   (0, 0), (-1, -1), 0.5, SLATE_200),
    ])
    kpi_tbl.setStyle(kpi_style)
    story.append(kpi_tbl)
    story.append(Spacer(1, 8))

    # ── 3. ZUSAMMENFASSUNG ────────────────────────────────────────────────────
    if bottom_line or exec_summary:
        content = []
        if bottom_line:
            content.append(Paragraph(
                f"<b>{bottom_line}</b>",
                _style(fontName="Helvetica-Bold", fontSize=9,
                       textColor=colors.HexColor("#1e40af"), spaceAfter=4),
            ))
        if exec_summary:
            content.append(Paragraph(exec_summary, _style(fontSize=9, leading=13)))

        box = Table([[content]], colWidths=[W])
        box.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, -1), BLUE_50),
            ("LINEBEFORE",  (0, 0), (0, -1), 3, BLUE_400),
            ("PADDING",     (0, 0), (-1, -1), 10),
        ]))
        story.append(box)
        story.append(Spacer(1, 6))

    # ── 4. UNTERNEHMENSBESCHREIBUNG ───────────────────────────────────────────
    if company_desc:
        story.extend(_section_head("Unternehmensbeschreibung"))
        story.append(Paragraph(company_desc, _style()))
        story.append(Spacer(1, 4))

    # ── 5. INVESTMENT CASE ────────────────────────────────────────────────────
    inv_case = data.get("investment_case", [])
    if inv_case:
        story.extend(_section_head("Investment Case"))
        for item in inv_case:
            if isinstance(item, dict):
                point  = _s(item.get("point", ""))
                source = _s(item.get("source", ""))
                story.append(Paragraph(
                    f"- {point}",
                    _style(leftIndent=8, spaceAfter=2),
                ))
                if source:
                    story.append(Paragraph(
                        f"<font size='7' color='#94a3b8'>   Quelle: {source}</font>",
                        _style(fontSize=7, leftIndent=16, spaceAfter=3),
                    ))
            elif isinstance(item, str):
                story.append(Paragraph(f"- {_s(item)}", _style(leftIndent=8, spaceAfter=3)))
        story.append(Spacer(1, 4))

    # ── 6. BEWERTUNGS-MULTIPLES ───────────────────────────────────────────────
    vt = data.get("valuation_table", [])
    if vt:
        story.extend(_section_head("Bewertungs-Multiples"))
        th = ["Kennzahl", "Aktuell", "Peer-Ø", "Hist.-Ø", "Einschaetzung"]
        rows = [th]
        for r in vt:
            if not isinstance(r, dict):
                continue
            rows.append([
                _s(r.get("metric",             "")),
                _s(r.get("current_value",       "-")),
                _s(r.get("peer_average",        "-")),
                _s(r.get("historical_average",  "-")),
                _s(r.get("assessment",          "FAIR")),
            ])

        col_w = [W * x for x in (0.30, 0.15, 0.15, 0.15, 0.25)]
        vt_tbl = Table(rows, colWidths=col_w)
        vt_style = [
            ("BACKGROUND",    (0, 0), (-1, 0), SLATE_100),
            ("FONT",          (0, 0), (-1, 0), "Helvetica-Bold", 7),
            ("FONT",          (0, 1), (-1, -1), "Helvetica", 8),
            ("TEXTCOLOR",     (0, 0), (-1, 0), SLATE_400),
            ("TEXTCOLOR",     (0, 1), (-1, -1), SLATE_700),
            ("GRID",          (0, 0), (-1, -1), 0.5, SLATE_200),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ]
        for i, row in enumerate(rows[1:], 1):
            a = row[4] if len(row) > 4 else "FAIR"
            if a == "DISCOUNT":
                vt_style.append(("TEXTCOLOR", (4, i), (4, i), GREEN))
                vt_style.append(("FONT", (4, i), (4, i), "Helvetica-Bold", 8))
            elif a == "ELEVATED":
                vt_style.append(("TEXTCOLOR", (4, i), (4, i), RED))
                vt_style.append(("FONT", (4, i), (4, i), "Helvetica-Bold", 8))
            if i % 2 == 0:
                vt_style.append(("BACKGROUND", (0, i), (-1, i), SLATE_50))
        vt_tbl.setStyle(TableStyle(vt_style))
        story.append(vt_tbl)
        story.append(Spacer(1, 4))

    # ── 7. SZENARIEN ─────────────────────────────────────────────────────────
    scenarios = data.get("scenarios", [])
    if scenarios:
        story.extend(_section_head("Szenarien"))
        sc_rows = [["Szenario", "Wahrsch.", "Kursziel", "Schluesselannahme"]]
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            sc_rows.append([
                _s(sc.get("name", "")),
                f"{sc.get('probability_pct', '-')}%",
                f"{ccy} {_num(sc.get('price_target'))}",
                _s(sc.get("key_assumption", ""))[:90],
            ])

        col_w2 = [W * x for x in (0.18, 0.10, 0.14, 0.58)]
        sc_tbl = Table(sc_rows, colWidths=col_w2)
        sc_style = [
            ("BACKGROUND",    (0, 0), (-1, 0), SLATE_100),
            ("FONT",          (0, 0), (-1, 0), "Helvetica-Bold", 7),
            ("FONT",          (0, 1), (-1, -1), "Helvetica", 8),
            ("TEXTCOLOR",     (0, 0), (-1, 0), SLATE_400),
            ("TEXTCOLOR",     (0, 1), (-1, -1), SLATE_700),
            ("GRID",          (0, 0), (-1, -1), 0.5, SLATE_200),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ]
        for i, row in enumerate(sc_rows[1:], 1):
            name = row[0]
            if "Bear" in name:
                sc_style.append(("TEXTCOLOR", (0, i), (0, i), RED))
                sc_style.append(("FONT", (0, i), (0, i), "Helvetica-Bold", 8))
            elif "Bull" in name:
                sc_style.append(("TEXTCOLOR", (0, i), (0, i), GREEN))
                sc_style.append(("FONT", (0, i), (0, i), "Helvetica-Bold", 8))
        sc_tbl.setStyle(TableStyle(sc_style))
        story.append(sc_tbl)
        story.append(Spacer(1, 4))

    # ── 8. RISIKEN ────────────────────────────────────────────────────────────
    risks = data.get("key_risks", data.get("risks", []))
    if risks:
        story.extend(_section_head("Risiken"))
        for r in risks:
            text = ""
            if isinstance(r, dict):
                text = _s(r.get("point", r.get("argument", "")))
            elif isinstance(r, str):
                text = _s(r)
            if text:
                story.append(Paragraph(
                    f"[!] {text}",
                    _style(leftIndent=8, spaceAfter=3, textColor=colors.HexColor("#b91c1c")),
                ))
        story.append(Spacer(1, 4))

    # ── 9. DISCLAIMER ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=0.5, color=SLATE_200, spaceAfter=5))
    story.append(Paragraph(
        "Dieses Dokument wurde von KI-Co-Analyst automatisch generiert und dient ausschliesslich "
        "zu Informationszwecken. Es stellt keine Anlageberatung oder Aufforderung zum Kauf oder "
        "Verkauf von Wertpapieren dar. Investoren sollten ihre eigene Due Diligence durchfuehren.",
        _style(fontSize=7, textColor=SLATE_400, leading=10),
    ))
    story.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  KI-Co-Analyst",
        _style(fontSize=7, textColor=SLATE_400, alignment=TA_RIGHT, spaceBefore=3),
    ))

    doc.build(story)
    return buf.getvalue()
