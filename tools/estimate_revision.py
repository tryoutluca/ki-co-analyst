"""
Estimate Revision Engine — Phase 2

Wendet die vom News-Agent identifizierten Makro-/Sektor-Treiber
(estimate_adjustments) DETERMINISTISCH auf die Forward-Estimates des
Fundamental-Agenten an. Kein LLM-Call — reine, nachvollziehbare
Python-Berechnung.

Designprinzipien:
  1. Konservativ: Jeder Effekt wird mit einem Confidence-Multiplikator
     gedämpft (hoch=1.0, mittel=0.6, niedrig=0.3) und zusätzlich mit der
     Selbst-Confidence des News-Agenten skaliert.
  2. Begrenzt: Einzeleffekte werden auf ±10pp geclamped, der kumulierte
     Gesamteffekt auf ±20%. Makro-Adjustments sollen Estimates VERFEINERN,
     nicht ersetzen.
  3. Transparent: Jedes angewendete Adjustment wird mit angewendetem Delta,
     Dämpfungsfaktor und Transmission-Chain protokolliert — der Supervisor
     und der Mensch sehen exakt, was warum verändert wurde.
"""

from __future__ import annotations

import copy

# Dämpfungsfaktoren nach Adjustment-Confidence
_CONFIDENCE_MULTIPLIER = {
    "hoch":    1.0,
    "mittel":  0.6,
    "niedrig": 0.3,
}

# Sicherheitsgrenzen
_MAX_SINGLE_DELTA_PP = 10.0   # Einzel-Adjustment max ±10pp
_MAX_TOTAL_DELTA_PCT = 20.0   # Kumulierter Effekt max ±20%


def _num(val):
    """Konvertiert zu float, None bei nicht-numerischen Werten ('n/v' etc.)."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace(",", "."))
        except (ValueError, AttributeError):
            return None
    return None


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def detect_oneoff_effects(full_financials: list) -> list:
    """
    Erkennt Sondereffekt-verdächtige Actual-Jahre.

    Heuristik: Ein EPS-Sprung ist verdächtig, wenn EPS stark steigt, während
    die operative Ertragskraft (EBITDA) im selben Jahr fällt oder stagniert —
    das deutet auf nicht-operative Gewinne hin (Veräußerungsgewinne,
    Steuereffekte, Einmaleffekte), die nicht in die Forward-Estimates
    fortgeschrieben werden dürfen.

    Returns:
        Liste von Flags: [{year, type, detail, severity}]
    """
    flags = []
    actuals = []
    for row in full_financials or []:
        r = row if isinstance(row, dict) else (
            row.model_dump() if hasattr(row, "model_dump") else {})
        if r.get("type") == "A":
            actuals.append(r)

    for i in range(1, len(actuals)):
        prev, cur = actuals[i - 1], actuals[i]
        eps_prev, eps_cur = _num(prev.get("eps_adj")), _num(cur.get("eps_adj"))
        eb_prev, eb_cur = _num(prev.get("ebitda_bn")), _num(cur.get("ebitda_bn"))

        if None in (eps_prev, eps_cur, eb_prev, eb_cur):
            continue
        if eps_prev <= 0 or eb_prev <= 0:
            continue

        eps_growth = (eps_cur - eps_prev) / abs(eps_prev) * 100.0
        ebitda_growth = (eb_cur - eb_prev) / abs(eb_prev) * 100.0

        # Verdächtig: EPS +>50% während EBITDA fällt/stagniert (<+5%)
        if eps_growth > 50.0 and ebitda_growth < 5.0:
            severity = "hoch" if eps_growth > 150.0 else "mittel"
            flags.append({
                "year": cur.get("year", "?"),
                "type": "eps_sprung_ohne_operative_deckung",
                "detail": (
                    f"EPS {eps_growth:+.0f}% ggü. Vorjahr, aber EBITDA nur "
                    f"{ebitda_growth:+.0f}% — wahrscheinlicher Sondereffekt "
                    f"(z.B. Veräußerungsgewinn). EPS dieses Jahres NICHT als "
                    f"Basis für Forward-Estimates verwenden."
                ),
                "severity": severity,
            })

    return flags


def apply_estimate_adjustments(
    fundamental_output: dict,
    adjustments: list,
    news_agent_confidence: float = 0.70,
) -> dict:
    """
    Wendet Makro-Adjustments auf die Forward-Estimates an.

    Args:
        fundamental_output: Output des Fundamental-Agenten (dict),
            erwartet "_full_financials" (Liste von Jahres-Zeilen) und
            "fair_value_estimate".
        adjustments: Liste von EstimateAdjustment-dicts aus dem News-Agent.
        news_agent_confidence: self_confidence des News-Agenten (0-1),
            dämpft alle Effekte zusätzlich.

    Returns:
        dict mit:
          adjustments_applied:  Liste angewendeter Adjustments inkl. Faktoren
          adjustments_skipped:  Liste übersprungener (mit Grund)
          revenue_delta_pct:    kumulierter Netto-Effekt auf Forward-Umsatz
          margin_delta_pp:      kumulierter Netto-Effekt auf EBITDA-Marge (pp)
          eps_delta_pct:        kumulierter Netto-Effekt auf Forward-EPS
          revised_forward_rows: revidierte Estimate-Zeilen (nur type=="E")
          indicative_fair_value_adjusted: indikativ angepasster Fair Value
          summary:              menschenlesbare Zusammenfassung
    """
    # News-Agent-Confidence als sekundärer Dämpfer:
    # bei Conf 1.0 → Faktor 1.0, bei Conf 0.0 → Faktor 0.5
    news_damper = 0.5 + 0.5 * max(0.0, min(1.0, float(news_agent_confidence)))

    applied, skipped = [], []
    revenue_delta = 0.0   # in % auf Forward-Umsatzniveau
    margin_delta = 0.0    # in Prozentpunkten auf EBITDA-Marge
    eps_direct_delta = 0.0  # in % auf Forward-EPS (direkte EPS-Adjustments)

    for adj in adjustments or []:
        if not isinstance(adj, dict):
            adj = adj.model_dump() if hasattr(adj, "model_dump") else dict(adj)

        metric = adj.get("affected_metric")
        low = _num(adj.get("delta_pct_low"))
        high = _num(adj.get("delta_pct_high"))
        conf = str(adj.get("confidence", "niedrig")).lower()

        if metric not in ("revenue_growth", "ebitda_margin", "eps"):
            skipped.append({**adj, "skip_reason": f"Unbekannte Metrik: {metric}"})
            continue
        if low is None or high is None:
            skipped.append({**adj, "skip_reason": "Delta nicht numerisch"})
            continue

        midpoint = (low + high) / 2.0
        conf_mult = _CONFIDENCE_MULTIPLIER.get(conf, 0.3)
        applied_delta = _clamp(midpoint * conf_mult * news_damper, _MAX_SINGLE_DELTA_PP)

        if metric == "revenue_growth":
            revenue_delta += applied_delta
        elif metric == "ebitda_margin":
            margin_delta += applied_delta
        else:  # eps
            eps_direct_delta += applied_delta

        applied.append({
            "driver": adj.get("driver", "?"),
            "driver_category": adj.get("driver_category", "?"),
            "affected_metric": metric,
            "delta_range_pct": [low, high],
            "midpoint_pct": round(midpoint, 2),
            "confidence": conf,
            "dampening_factor": round(conf_mult * news_damper, 3),
            "applied_delta_pct": round(applied_delta, 2),
            "transmission_chain": adj.get("transmission_chain", ""),
            "evidence_source": adj.get("evidence_source", "nicht verfügbar"),
        })

    # Kumulierte Grenzen
    revenue_delta = _clamp(revenue_delta, _MAX_TOTAL_DELTA_PCT)
    margin_delta = _clamp(margin_delta, _MAX_TOTAL_DELTA_PCT)
    eps_direct_delta = _clamp(eps_direct_delta, _MAX_TOTAL_DELTA_PCT)

    # ── EPS-Gesamteffekt herleiten ─────────────────────────────────────────
    # Umsatz-Delta fliesst konservativ 1:1 ins EPS (kein Operating Leverage
    # unterstellt — bewusst vorsichtig). Margen-Delta wird relativ zur
    # Basis-Marge in einen EPS-Effekt übersetzt, falls die Basis-Marge
    # numerisch bekannt ist.
    full_fin = fundamental_output.get("_full_financials") or \
               fundamental_output.get("full_financials") or []

    # Sondereffekt-Erkennung (vor der Fortschreibung — warnt vor verzerrter Basis)
    oneoff_flags = detect_oneoff_effects(full_fin)
    base_margin = None
    for row in full_fin:
        r = row if isinstance(row, dict) else (
            row.model_dump() if hasattr(row, "model_dump") else {})
        if r.get("type") == "E":
            base_margin = _num(r.get("ebitda_margin_pct"))
            if base_margin:
                break

    margin_eps_effect = 0.0
    if margin_delta and base_margin and base_margin > 1.0:
        margin_eps_effect = _clamp(
            margin_delta / base_margin * 100.0, _MAX_TOTAL_DELTA_PCT
        )

    eps_delta = _clamp(
        eps_direct_delta + revenue_delta + margin_eps_effect,
        _MAX_TOTAL_DELTA_PCT,
    )

    # ── Referenz-Ratios aus 3-Jahres-Median der Actuals ────────────────────
    # Median statt "letztes Ist" glättet Sondereffekte (z.B. Veräußerungs-
    # gewinne, die EPS/ROIC eines einzelnen Jahres verzerren). Bei <3
    # Actual-Jahren wird genommen, was verfügbar ist.
    actual_rows = []
    for row in full_fin:
        r = row if isinstance(row, dict) else (
            row.model_dump() if hasattr(row, "model_dump") else {})
        if r.get("type") == "A":
            actual_rows.append(r)

    # Letzte Actual-Zeile (für Net-Debt-Level, Aktienzahl-Ableitung)
    last_actual = actual_rows[-1] if actual_rows else None

    # Die jüngsten bis zu 3 Actual-Jahre für die Median-Bildung
    recent_actuals = actual_rows[-3:] if actual_rows else []

    def _median(vals):
        vals = sorted(v for v in vals if isinstance(v, (int, float)))
        if not vals:
            return None
        n = len(vals)
        mid = n // 2
        return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0

    def _median_ratio(key, transform=None):
        out = []
        for r in recent_actuals:
            v = _num(r.get(key))
            if v is None:
                continue
            if transform:
                v = transform(r, v)
                if v is None:
                    continue
            out.append(v)
        return _median(out)

    # FCF-Marge und Capex-Marge brauchen Umsatz-Bezug → transform
    def _to_margin(r, v):
        rev = _num(r.get("revenue_bn"))
        return (v / rev) if (rev and rev > 0) else None

    ref_fcf_margin = _median_ratio("fcf_bn", _to_margin)
    ref_capex_margin = _median_ratio("capex_bn", _to_margin)
    ref_ebit_margin = _median_ratio("ebit_margin_pct")
    ref_nd_ebitda = _median_ratio("nd_ebitda")
    ref_roic = _median_ratio("roic_pct")
    # DPS: jüngster Wert (Dividenden sind sticky, kein Median nötig)
    ref_dps = _num(last_actual.get("dps")) if last_actual else None

    _ratio_basis = (
        f"3-Jahres-Median ({recent_actuals[0].get('year','?')}–"
        f"{recent_actuals[-1].get('year','?')})"
        if len(recent_actuals) >= 2 else "letztes Ist"
    )

    # ── Revidierte Forward-Zeilen bauen (ALLE Kennzahlen befüllen) ──────────
    revised_rows = []
    for row in full_fin:
        r = row if isinstance(row, dict) else (
            row.model_dump() if hasattr(row, "model_dump") else {})
        if r.get("type") != "E":
            continue
        new_row = copy.deepcopy(r)
        derived_notes = []

        # 1) Umsatz (Makro-revidiert)
        rev = _num(r.get("revenue_bn"))
        if rev is not None and revenue_delta:
            rev = round(rev * (1 + revenue_delta / 100.0), 4)
            new_row["revenue_bn"] = rev
        elif rev is None and last_actual is not None:
            rev = _num(last_actual.get("revenue_bn"))

        # 2) EBITDA-Marge (Makro-revidiert)
        m = _num(r.get("ebitda_margin_pct"))
        if m is not None and margin_delta:
            m = round(m + margin_delta, 2)
            new_row["ebitda_margin_pct"] = m

        # 3) EBITDA aus revidiertem Umsatz × Marge
        if rev is not None and m is not None:
            new_row["ebitda_bn"] = round(rev * m / 100.0, 4)
        ebitda_val = _num(new_row.get("ebitda_bn"))

        # 4) EPS (Makro-revidiert)
        eps = _num(r.get("eps_adj"))
        if eps is not None and eps_delta:
            new_row["eps_adj"] = round(eps * (1 + eps_delta / 100.0), 3)

        # 5) EBIT-Marge: vorhanden lassen, sonst aus Referenz fortschreiben
        if _num(new_row.get("ebit_margin_pct")) is None and ref_ebit_margin is not None:
            new_row["ebit_margin_pct"] = round(ref_ebit_margin, 2)
            derived_notes.append(f"EBIT-%≈{_ratio_basis}")
        # EBIT absolut aus Umsatz × EBIT-Marge
        ebit_m = _num(new_row.get("ebit_margin_pct"))
        if rev is not None and ebit_m is not None and _num(new_row.get("ebit_bn")) is None:
            new_row["ebit_bn"] = round(rev * ebit_m / 100.0, 4)

        # 6) FCF: aus FCF-Marge des letzten Ist-Jahres × revidiertem Umsatz
        if _num(new_row.get("fcf_bn")) is None and ref_fcf_margin is not None and rev is not None:
            new_row["fcf_bn"] = round(rev * ref_fcf_margin, 4)
            derived_notes.append(f"FCF≈FCF-Marge {_ratio_basis}")

        # 7) Capex analog
        if _num(new_row.get("capex_bn")) is None and ref_capex_margin is not None and rev is not None:
            new_row["capex_bn"] = round(rev * ref_capex_margin, 4)

        # 8) DPS: konstant fortschreiben (konservativ, kein Wachstum unterstellt)
        if _num(new_row.get("dps")) is None and ref_dps is not None:
            new_row["dps"] = ref_dps
            derived_notes.append("DPS≈letztes Ist")

        # 9) ND/EBITDA: Net Debt konstant halten, durch revidiertes EBITDA teilen
        if _num(new_row.get("nd_ebitda")) is None:
            la_nd = _num(last_actual.get("net_debt_bn")) if last_actual else None
            if la_nd is not None and ebitda_val and ebitda_val > 0:
                new_row["net_debt_bn"] = la_nd
                new_row["nd_ebitda"] = round(la_nd / ebitda_val, 2)
                derived_notes.append("ND/EBITDA≈Net Debt konstant")
            elif ref_nd_ebitda is not None:
                new_row["nd_ebitda"] = round(ref_nd_ebitda, 2)
                derived_notes.append(f"ND/EBITDA≈{_ratio_basis}")

        # 10) ROIC: aus letztem Ist fortschreiben (konservativ)
        if _num(new_row.get("roic_pct")) is None and ref_roic is not None:
            new_row["roic_pct"] = round(ref_roic, 2)
            derived_notes.append(f"ROIC≈{_ratio_basis}")

        # 11) Net Income aus EPS ableiten falls möglich (Shares ≈ NI/EPS aus Ist)
        if _num(new_row.get("net_income_bn")) is None and last_actual is not None:
            la_ni = _num(last_actual.get("net_income_bn"))
            la_eps = _num(last_actual.get("eps_adj"))
            new_eps = _num(new_row.get("eps_adj"))
            if la_ni and la_eps and la_eps != 0 and new_eps is not None:
                implied_shares = la_ni / la_eps
                new_row["net_income_bn"] = round(implied_shares * new_eps, 4)
                derived_notes.append("NI≈implizite Aktienzahl")

        # Quelle + Methoden-Transparenz
        base_src = str(r.get("source", ""))
        macro_tag = " | Makro-revidiert (Phase 2)" if (revenue_delta or margin_delta or eps_delta) else ""
        derived_tag = (" | abgeleitet: " + ", ".join(derived_notes)) if derived_notes else ""
        new_row["source"] = base_src + macro_tag + derived_tag

        revised_rows.append(new_row)

    # ── Indikativ angepasster Fair Value ───────────────────────────────────
    # Lineares Scaling über den EPS-Effekt — als Cross-Check für den
    # Supervisor, NICHT als automatisches Override. Gilt nur für
    # Multiples-/DCF-verankerte Bewertungen (Supervisor entscheidet).
    fair_value = _num(fundamental_output.get("fair_value_estimate"))
    indicative_fv = None
    if fair_value is not None and fair_value > 0 and eps_delta:
        indicative_fv = round(fair_value * (1 + eps_delta / 100.0), 2)

    # ── Zusammenfassung ────────────────────────────────────────────────────
    if applied:
        drivers = "; ".join(
            f"{a['driver']} ({a['applied_delta_pct']:+.1f}pp auf {a['affected_metric']})"
            for a in applied
        )
        summary = (
            f"{len(applied)} Makro-Adjustment(s) angewendet (gedämpft mit "
            f"Confidence-Faktoren, News-Conf {news_agent_confidence:.2f}): {drivers}. "
            f"Netto: Umsatz {revenue_delta:+.2f}%, Marge {margin_delta:+.2f}pp, "
            f"EPS {eps_delta:+.2f}%."
        )
    else:
        summary = "Keine anwendbaren Makro-Adjustments."

    return {
        "adjustments_applied": applied,
        "adjustments_skipped": skipped,
        "revenue_delta_pct": round(revenue_delta, 2),
        "margin_delta_pp": round(margin_delta, 2),
        "eps_delta_pct": round(eps_delta, 2),
        "revised_forward_rows": revised_rows,
        "indicative_fair_value_adjusted": indicative_fv,
        "oneoff_flags": oneoff_flags,
        "summary": summary,
    }
