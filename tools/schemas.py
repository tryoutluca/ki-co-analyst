from pydantic import BaseModel, Field
from typing import Literal, Optional

# ── News Agent ──────────────────────────────────────────────────────────────

class MacroIndicator(BaseModel):
    indicator: str
    value: str
    trend: Literal["improving", "stable", "deteriorating"]
    impact_on_company: Literal["tailwind", "neutral", "headwind"]
    mechanism: str = Field(
        description=(
            "How this indicator affects the company. E.g. "
            "'Rising SNB rates → higher mortgage costs → reduced "
            "construction activity → lower cement demand → headwind for Holcim'"
        )
    )
    source: str

class IndustryFactor(BaseModel):
    topic: str
    direction: Literal["tailwind", "neutral", "headwind"]
    mechanism: str
    source: str
    headline: str

class NewsItem(BaseModel):
    headline: str = Field(description="Exakte Headline des Artikels")
    source: str = Field(description="Quellenname z.B. Reuters, cash.ch, Yahoo Finance")
    url: str = Field(description="Exakte URL des Artikels oder 'nicht verfügbar'")
    published: str = Field(description="Publikationsdatum")
    credibility: Literal["sehr hoch", "hoch", "mittel", "niedrig"] = Field(
        description="Glaubwürdigkeit der Quelle"
    )
    affected_segment: str = Field(
        description="Betroffene Revenue Line z.B. [Services], [iPhone/Hardware], [Mac], [Wearables], [alle Segmente]"
    )
    summary: str = Field(description="2-3 Sätze Zusammenfassung der News")
    sentiment_impact: Literal["sehr positiv", "positiv", "neutral", "negativ", "sehr negativ"] = Field(
        description="Sentiment-Auswirkung dieser spezifischen News"
    )

class NewsRisk(BaseModel):
    description: str = Field(description="Konkretes Risiko aus den News")
    affected_segment: str = Field(description="Betroffene Revenue Line")
    time_horizon: Literal["kurzfristig", "mittelfristig", "strukturell"]
    source_headline: str = Field(description="Headline der Quelle die dieses Risiko belegt")
    source_url: str = Field(description="URL der Quelle")

class ForwardYearProjection(BaseModel):
    """Eine projizierte Forward-Jahr-Zeile mit begründeter Wachstumsannahme."""
    year: str = Field(description="z.B. '2026E'")
    revenue_growth_pct: float = Field(
        description="Projizierte Umsatzwachstumsrate YoY in % (kann negativ sein)"
    )
    revenue_bn: float = Field(description="Resultierender Umsatz (Vorjahr × (1+Wachstum))")
    ebitda_margin_pct: float = Field(description="Projizierte EBITDA-Marge in %")
    ebitda_bn: float = Field(description="Resultierendes EBITDA")
    eps: float = Field(description="Projiziertes EPS")
    growth_rationale: str = Field(
        description=(
            "Begründung der Wachstumsrate für DIESES Jahr: welche Treiber "
            "(Sektor-Nachfrage, Thematic, Makro, Unternehmensposition, Zyklus) "
            "in welcher Stärke einfliessen. Konkret und quantifiziert."
        )
    )
    margin_rationale: str = Field(
        description="Begründung der Margenannahme (Skaleneffekte, Kostendruck, Mix)"
    )
    consensus_revenue_growth_pct: float | str = Field(
        default="n/v",
        description="Konsens-Wachstum für dieses Jahr (Fussnote/Abgleich), 'n/v' wenn fehlt"
    )
    deviation_from_consensus: str = Field(
        default="",
        description=(
            "Falls eigene Projektion vom Konsens abweicht: Richtung + Begründung. "
            "z.B. 'Aggressiver als Konsens (+45% vs +18%), weil KI-Capex-Zyklus "
            "in Konsens noch nicht eingepreist'. Leer wenn kein Konsens vorliegt."
        )
    )
    plausibility_flag: str = Field(
        default="",
        description=(
            "Automatische Plausibilitätswarnung, wird vom System gesetzt "
            "(z.B. bei >80% YoY-Wachstum). Vom LLM leer lassen."
        )
    )


class ForwardEstimateOutput(BaseModel):
    """Output des Forward-Estimate-Agenten — das Herzstück der Projektion."""
    ticker: str
    base_year: str = Field(description="Letztes Ist-Jahr, von dem projiziert wird")
    base_revenue_bn: float = Field(description="Umsatz des Basisjahrs")
    base_year_is_normalized: bool = Field(
        default=False,
        description=(
            "True wenn das Basisjahr um Sondereffekte bereinigt wurde "
            "(z.B. Veräußerungsgewinn herausgerechnet)"
        )
    )
    projections: list[ForwardYearProjection] = Field(
        description="Projektionen für die Forward-Jahre (typisch 3 Jahre)"
    )
    key_growth_drivers: list[str] = Field(
        description=(
            "3-5 zentrale Wachstumstreiber, die die Projektion tragen, "
            "in absteigender Wichtigkeit"
        )
    )
    overall_thesis: str = Field(
        description=(
            "2-3 Sätze: Die übergreifende Wachstums-These. Wie entwickelt sich "
            "das Unternehmen über den Projektionszeitraum und warum?"
        )
    )
    self_confidence: float = Field(
        default=0.65, ge=0.0, le=1.0,
        description="Selbsteinschätzung der Projektionssicherheit (0.0–1.0)"
    )
    confidence_rationale: str = Field(default="")


class ThematicTrend(BaseModel):
    """Ein struktureller Megatrend mit Bezug zum Unternehmen."""
    trend: str = Field(
        description=(
            "Name des Megatrends, z.B. 'KI-Rechenzentren-Capex', "
            "'Energiewende/Elektrifizierung', 'Quantum-Computing-Adoption', "
            "'Reshoring/Deglobalisierung', 'Demografie/Healthcare', "
            "'Verteidigungs-Aufrüstung'"
        )
    )
    relevance: Literal["kern", "moderat", "peripher"] = Field(
        description=(
            "kern: Trend ist zentral für die These des Unternehmens. "
            "moderat: spürbarer Einfluss. peripher: am Rande relevant."
        )
    )
    time_horizon: Literal["kurzfristig", "mittelfristig", "langfristig"] = Field(
        description="kurzfristig <2J, mittelfristig 2-5J, langfristig >5J"
    )
    adoption_stage: Literal[
        "früh", "beschleunigung", "reife", "saettigung"
    ] = Field(
        description=(
            "Position auf der Adoptionskurve. 'beschleunigung' ist die Phase "
            "mit dem stärksten Wachstumsbeitrag (S-Kurve steilster Punkt)."
        )
    )
    tam_impact: str = Field(
        description=(
            "Wirkung auf den adressierbaren Markt (TAM) des Unternehmens, "
            "quantifiziert wenn möglich, z.B. 'TAM-Wachstum +35% p.a. bis 2028' "
            "oder 'verdoppelt den Servicemarkt bis 2030'"
        )
    )
    company_positioning: str = Field(
        description=(
            "Wie gut ist DIESES Unternehmen positioniert, um vom Trend zu "
            "profitieren? Marktanteil, Produkte, Pipeline, Wettbewerbsvorteil."
        )
    )
    growth_contribution: str = Field(
        description=(
            "Geschätzter Beitrag zum Umsatzwachstum, der DIREKT in die "
            "Forward-Estimates einfliessen soll, z.B. '+15-25pp zusätzliches "
            "Umsatzwachstum FY26-27' oder 'stützt Marge durch Premium-Mix'"
        )
    )
    evidence: str = Field(
        description="Beleg/Quelle für den Trend und seine Stärke, 'nicht verfügbar' wenn fehlt"
    )


class ThematicAgentOutput(BaseModel):
    """Output des Thematic-Agenten (4. Junior, Phase 3)."""
    ticker: str
    company: str
    trends: list[ThematicTrend] = Field(
        description=(
            "1-4 relevante Megatrends, absteigend nach Relevanz. Leere Liste "
            "ist valide, wenn das Unternehmen nicht trend-getrieben ist "
            "(z.B. defensiver Versorger)."
        )
    )
    net_thematic_assessment: Literal[
        "starker rückenwind", "rückenwind", "neutral", "gegenwind", "starker gegenwind"
    ] = Field(
        description="Netto-Einschätzung aller Trends zusammen für das Unternehmen"
    )
    thematic_thesis: str = Field(
        description=(
            "2-3 Sätze: Die thematische These. Wie verändern strukturelle "
            "Trends die Wachstums- und Margenaussichten über 3-5 Jahre?"
        )
    )
    growth_rate_implication: str = Field(
        description=(
            "Konkrete Implikation für die Forward-Wachstumsraten, die der "
            "Forward-Estimate-Agent nutzen soll. z.B. 'Thematic stützt "
            "Umsatzwachstum von 40-55% in FY26, abklingend auf 20% FY28'"
        )
    )
    summary: str = Field(
        description=(
            "Kompakte Zusammenfassung für den Forward-Estimate-Agent "
            "(wird als thematic_context.summary übergeben). Enthält die "
            "wichtigsten Trends + ihre quantifizierten Wachstumsbeiträge."
        )
    )
    self_confidence: float = Field(
        default=0.60, ge=0.0, le=1.0,
        description="Selbsteinschätzung (Trends sind inhärent unsicherer als Fundamentals)"
    )
    confidence_rationale: str = Field(default="")


class OptionalityScenarioPath(BaseModel):
    """Ein möglicher Zukunftspfad für ein Optionality-Play."""
    name: str = Field(description="z.B. 'Kommerzialisierung gelingt früh', 'Verwässerungs-Spirale'")
    probability_pct: float = Field(description="Eintrittswahrscheinlichkeit in %")
    value_per_share: float = Field(description="Wert je Aktie in diesem Pfad")
    key_milestone: str = Field(description="Das entscheidende Ereignis, das diesen Pfad auslöst")


class OptionalityOutput(BaseModel):
    """
    Output des Optionality-Sub-Agenten (Phase 4).
    Bewertet Pre-Revenue/Deep-Tech-Unternehmen über Real-Options-Logik
    statt DCF: TAM × Adoption-Probability × Marktanteil + Cash-Runway.
    """
    ticker: str
    company: str

    # ── Cash-Runway-Analyse ───────────────────────────────────
    cash_position_mn: float | str = Field(
        default="n/v", description="Liquide Mittel in Mio."
    )
    annual_burn_mn: float | str = Field(
        default="n/v", description="Jährlicher Cash-Burn in Mio. (negativer FCF)"
    )
    runway_months: float | str = Field(
        default="n/v",
        description="Wie viele Monate reicht die Liquidität beim aktuellen Burn?"
    )
    dilution_risk: Literal["niedrig", "mittel", "hoch", "akut"] = Field(
        default="mittel",
        description="Verwässerungsrisiko. 'akut' wenn Runway < 12 Monate."
    )
    runway_assessment: str = Field(
        default="",
        description="1-2 Sätze: Wie kritisch ist die Liquiditätslage?"
    )

    # ── TAM × Adoption Bewertung ──────────────────────────────
    tam_estimate_bn: float | str = Field(
        default="n/v",
        description="Geschätzter adressierbarer Gesamtmarkt (TAM) in Mrd. zum Zielhorizont"
    )
    tam_horizon_year: str = Field(
        default="",
        description="Jahr, für das der TAM geschätzt wird (z.B. '2032')"
    )
    adoption_probability_pct: float | str = Field(
        default="n/v",
        description="Wahrscheinlichkeit, dass sich die Technologie kommerziell durchsetzt (%)"
    )
    expected_market_share_pct: float | str = Field(
        default="n/v",
        description="Erwarteter Marktanteil des Unternehmens bei erfolgreicher Adoption (%)"
    )

    # ── Real-Options-Bewertung ────────────────────────────────
    scenario_paths: list[OptionalityScenarioPath] = Field(
        default_factory=list,
        description="3-4 Zukunftspfade (Erfolg/Teilerfolg/Misserfolg/Total-Loss) mit Wahrscheinlichkeiten"
    )
    probability_weighted_value: float | str = Field(
        default="n/v",
        description="Wahrscheinlichkeits-gewichteter Wert je Aktie = Σ(prob × value)"
    )
    current_price: float | str = Field(default="n/v")
    upside_downside_pct: float | str = Field(default="n/v")

    # ── Gesamteinschätzung ────────────────────────────────────
    optionality_thesis: str = Field(
        description="2-3 Sätze: Die Optionality-These. Worauf wettet der Investor?"
    )
    binary_risk_warning: str = Field(
        default="",
        description="Warnung zum binären Charakter (hohe Verlustwahrscheinlichkeit)"
    )
    self_confidence: float = Field(
        default=0.45, ge=0.0, le=1.0,
        description="Optionality-Bewertung ist inhärent unsicher — Default niedrig"
    )
    confidence_rationale: str = Field(default="")


class EstimateAdjustment(BaseModel):
    """
    Phase 2: Strukturierter Makro-/Sektor-Treiber mit quantifiziertem
    Effekt auf die Forward-Estimates. Wird vom News-Agent generiert und
    von der Estimate-Revision-Engine deterministisch angewendet.
    """
    driver: str = Field(
        description=(
            "Der konkrete Makro-/Sektor-Treiber, z.B. 'SNB-Leitzinssenkung -50bp', "
            "'EUR/CHF-Abwertung -4% YTD', 'US-Zölle auf Stahlimporte +25%', "
            "'AI-Capex-Zyklus der Hyperscaler +40% YoY', 'Ölpreis -18% seit Q1'"
        )
    )
    driver_category: Literal[
        "zinsen", "waehrung", "rohstoffe", "regulierung",
        "sektor_nachfrage", "konjunktur", "geopolitik", "technologie_adoption"
    ] = Field(description="Kategorie des Treibers")
    affected_metric: Literal["revenue_growth", "ebitda_margin", "eps"] = Field(
        description="Welche Forward-Kennzahl betroffen ist"
    )
    delta_pct_low: float = Field(
        description="Untere Grenze des geschätzten Effekts in Prozentpunkten (z.B. +1.5 oder -3.0)"
    )
    delta_pct_high: float = Field(
        description="Obere Grenze des geschätzten Effekts in Prozentpunkten"
    )
    confidence: Literal["hoch", "mittel", "niedrig"] = Field(
        description=(
            "hoch: Transmission empirisch belegt + Treiber bereits eingetreten. "
            "mittel: plausible Transmission, Treiber wahrscheinlich. "
            "niedrig: spekulative Verknüpfung."
        )
    )
    transmission_chain: str = Field(
        description=(
            "Explizite Wirkungskette vom Treiber zur Kennzahl, z.B. "
            "'SNB -50bp → Hypothekarzinsen sinken → Baubewilligungen +8% (BFS) → "
            "Zementnachfrage CH +5% → Holcim CH-Segment-Umsatz +2-3%'"
        )
    )
    evidence_source: str = Field(
        description="Quelle/Beleg für den Treiber (URL oder Publikation), 'nicht verfügbar' wenn fehlend"
    )


class NewsAgentOutput(BaseModel):
    ticker: str
    company: str
    overall_sentiment_score: int = Field(
        ge=1, le=10,
        description="Gesamt-Sentiment 1-10 (1=sehr bearish, 10=sehr bullish)"
    )
    short_term_outlook: Literal["positiv", "neutral", "negativ"] = Field(
        description="Kurzfristiger Ausblick 1-3 Monate"
    )
    long_term_outlook: Literal["positiv", "neutral", "negativ"] = Field(
        description="Langfristiger Ausblick 6-12 Monate"
    )
    sentiment_vs_fundamentals: Literal["übereinstimmend", "Diskrepanz-Chance", "Diskrepanz-Warnsignal"]
    sentiment_vs_fundamentals_reasoning: str = Field(
        description="Begründung in 2-3 Sätzen"
    )
    news_items: list[NewsItem] = Field(description="Liste der analysierten News")
    risks: list[NewsRisk] = Field(description="2-3 konkrete Risiken aus den News")
    macro_indicators: list[MacroIndicator] = Field(
        description="3-5 makroökonomische Indikatoren mit Auswirkung auf das Unternehmen"
    )
    industry_factors: list[IndustryFactor] = Field(
        description="3-5 industriespezifische Faktoren mit Richtung und Mechanismus"
    )
    overall_macro_direction: Literal["tailwind", "neutral", "headwind"] = Field(
        description="Gesamtbewertung des makroökonomischen Umfelds für dieses Unternehmen"
    )
    overall_industry_direction: Literal["tailwind", "neutral", "headwind"] = Field(
        description="Gesamtbewertung der industriespezifischen Dynamiken"
    )
    macro_summary: str = Field(
        description=(
            "2-3 Sätze: Wie beeinflusst das aktuelle Makro- und Industrieumfeld "
            "dieses spezifische Unternehmen?"
        )
    )
    # ── Phase 2: Quantifizierte Makro-Estimate-Adjustments ─────────────────
    estimate_adjustments: list[EstimateAdjustment] = Field(
        default_factory=list,
        description=(
            "0-4 quantifizierte Makro-/Sektor-Treiber mit Transmission-Chain, "
            "die in den Konsens-Forward-Estimates noch NICHT eingepreist sind. "
            "NUR aufnehmen wenn: (1) der Treiber konkret belegbar ist, "
            "(2) die Transmission zum Unternehmen explizit herleitbar ist, "
            "(3) der Effekt quantifizierbar ist. Leere Liste ist ein "
            "valides und oft korrektes Ergebnis."
        )
    )
    # ── Phase 1: Selbst-Confidence des Agenten ─────────────────────────────
    self_confidence: float = Field(
        default=0.70,
        ge=0.0, le=1.0,
        description=(
            "Selbsteinschätzung der News/Makro-Analyse (0.0–1.0). "
            "Hoch bei klarem Makro-Bild und vielen relevanten Tier-1-Quellen. "
            "Niedrig bei dünner Nachrichtenlage oder widersprüchlichen Signalen."
        )
    )
    confidence_rationale: str = Field(
        default="",
        description="Kurzbegründung (1-2 Sätze) für self_confidence."
    )


# ── Fundamental Agent ────────────────────────────────────────────────────────

class FundamentalStrength(BaseModel):
    point: str = Field(description="Konkreter Investment-Case Punkt mit Zahlen")
    source: str = Field(description="Datenquelle z.B. 'yfinance'")

class FundamentalRisk(BaseModel):
    point: str = Field(description="Konkretes Risiko wo die Analyse falsch liegen könnte")
    source: str

class CashflowMetrics(BaseModel):
    operating_cashflow: float | str
    capital_expenditure: float | str
    free_cashflow: float | str
    fcf_yield_pct: float | str
    fcf_conversion_pct: float | str
    capex_to_revenue_pct: float | str
    net_debt_to_ebitda: float | str
    ev_to_fcf: float | str
    source: str = "yfinance"
    ir_verification_recommended: bool = Field(
        description=(
            "True if FCF deviates significantly from reported net income "
            "(conversion < 70% or > 130%)"
        )
    )

class FundamentalAgentOutput(BaseModel):
    ticker: str
    company: str
    sector: str
    recommendation: Literal["KAUFEN", "ÜBERGEWICHTEN", "HALTEN", "UNTERGEWICHTEN", "VERKAUFEN"]
    fair_value_estimate: float = Field(description="Geschätzter fairer Wert in USD/CHF")
    current_price: float
    upside_downside_pct: float = Field(description="Upside/Downside in % zum fairen Wert")
    valuation_assessment: Literal["unterbewertet", "fair bewertet", "überbewertet"]
    company_description: str = Field(description="Max. 3 Sätze Unternehmensbeschreibung")
    investment_case: list[FundamentalStrength] = Field(
        description="3-5 Punkte Investment Case"
    )
    risks: list[FundamentalRisk] = Field(description="2-3 Risiken")
    key_metrics: dict = Field(description="Wichtigste Kennzahlen als Key-Value Paare")
    cashflow_metrics: CashflowMetrics = Field(
        description="Detaillierte Cashflow- und Kapitaleffizienzkennzahlen"
    )
    # ── Phase 1: Selbst-Confidence des Agenten ─────────────────────────────
    self_confidence: float = Field(
        default=0.70,
        ge=0.0, le=1.0,
        description=(
            "Selbsteinschätzung der Analyse-Qualität (0.0–1.0). "
            "Hoch bei stabilen Fundamentals + reichhaltigen IR-Daten + "
            "DCF anwendbar. Niedrig bei Pre-Revenue, fehlenden IR-Daten, "
            "stark verzerrten Multiples oder anderen Datenlücken."
        )
    )
    confidence_rationale: str = Field(
        default="",
        description=(
            "Kurzbegründung (1-2 Sätze) für den self_confidence-Score. "
            "Welche Daten sind solide, wo bestehen Unsicherheiten?"
        )
    )
    sub_agent_errors: list[str] = Field(
        default_factory=list,
        description=(
            "Namen der Sub-Agenten (quality/growth/valuation/capital_allocation), "
            "deren Output nicht geparst werden konnte. Wird deterministisch vom "
            "Orchestrator gesetzt, nicht vom LLM."
        )
    )


# ── Risk Agent ───────────────────────────────────────────────────────────────

class RiskArgument(BaseModel):
    category: Literal[
        "Bewertungsrisiko",
        "Makro/Zinsrisiko",
        "Operatives Risiko",
        "Regulierungsrisiko",
        "Sentiment-Risiko",
    ]
    argument: str = Field(description="Konkretes Gegenargument mit Zahlen")
    quantification: str = Field(
        description=(
            "Quantified impact where possible. E.g. "
            "'SNB rate +100bps → construction volume -5% → "
            "Holcim revenue -3%'. Use 'not quantifiable' if impossible."
        )
    )
    references_original_point: str = Field(
        description="Welcher Punkt aus der Originalanalyse wird hinterfragt"
    )
    confirmation_bias_detected: bool = Field(
        description=(
            "True if the original analysis selectively used data to support "
            "its conclusion. E.g. using Forward P/E instead of Trailing P/E "
            "because it looks cheaper."
        )
    )
    confirmation_bias_explanation: str

class CriticalQuestion(BaseModel):
    question: str = Field(description="Kritische Rückfrage an den Analysten")
    context: str = Field(description="Warum ist diese Frage relevant")

class Scenario(BaseModel):
    name: Literal["Bear Case", "Base Case", "Bull Case"]
    probability_pct: int = Field(
        description="Estimated probability in %. Bear+Base+Bull must sum to 100."
    )
    price_target: float
    key_assumption: str = Field(
        description="The single most important assumption for this scenario"
    )
    trigger: str = Field(
        description="What event or data point would confirm this scenario"
    )

class ConvictionKiller(BaseModel):
    description: str = Field(
        description=(
            "The single point that would immediately invalidate "
            "the original recommendation"
        )
    )
    monitoring_indicator: str = Field(
        description=(
            "Which specific metric or event to monitor. "
            "E.g. 'Watch Q3 Services revenue margin — if below 28% the "
            "bull case collapses'"
        )
    )

class RiskAgentOutput(BaseModel):
    ticker: str
    company: str
    original_recommendation: Literal["KAUFEN", "ÜBERGEWICHTEN", "HALTEN", "UNTERGEWICHTEN", "VERKAUFEN"]
    counter_position: str = Field(description="1-2 Sätze Gegenposition")
    risk_arguments: list[RiskArgument] = Field(
        description="5 critical arguments, one per category"
    )
    macro_risks_ignored: list[str] = Field(
        description=(
            "List of macro/industry factors from news analysis that the "
            "fundamental analysis underweighted or ignored. "
            "E.g. 'Rising SNB rates not reflected in DCF discount rate'"
        )
    )
    challenged_assumptions: dict = Field(
        description="Hinterfragte Annahmen: growth, valuation, sentiment"
    )
    critical_questions: list[CriticalQuestion] = Field(
        description="3 kritische Rückfragen an den Analysten"
    )
    scenarios: list[Scenario] = Field(
        description="Exactly 3 scenarios: Bear, Base, Bull. Probabilities must sum to 100."
    )
    conviction_killers: list[ConvictionKiller] = Field(
        description=(
            "1-2 absolute dealbreakers that would immediately "
            "invalidate the recommendation"
        )
    )
    condition_for_original_recommendation: str = Field(
        description="Unter welcher Bedingung wäre die ursprüngliche Empfehlung gerechtfertigt"
    )
    # ── Phase 1: Selbst-Confidence des Agenten ─────────────────────────────
    self_confidence: float = Field(
        default=0.70,
        ge=0.0, le=1.0,
        description=(
            "Selbsteinschätzung der Risk-Analyse (0.0–1.0). "
            "Hoch bei klar identifizierbaren Conviction Killers + "
            "guter Datenbasis. Niedrig wenn Risiken spekulativ bleiben."
        )
    )
    confidence_rationale: str = Field(
        default="",
        description="Kurzbegründung (1-2 Sätze) für self_confidence."
    )


# ── Full Financial Overview ──────────────────────────────────────────────────

class FullFinancialYear(BaseModel):
    year: str                              # z.B. "2023A", "2026E"
    type: Literal["A", "E"]               # A=Actual, E=Estimate
    revenue_bn: float | str
    ebitda_bn: float | str
    ebitda_margin_pct: float | str
    ebit_bn: float | str
    ebit_margin_pct: float | str
    net_income_bn: float | str
    eps_adj: float | str
    dps: float | str                       # Dividende pro Aktie
    fcf_bn: float | str
    net_debt_bn: float | str
    nd_ebitda: float | str                 # Net Debt / EBITDA
    roic_pct: float | str
    capex_bn: float | str
    source: str                            # Datenquelle pro Jahr


class PeerCompanyData(BaseModel):
    company: str
    ticker: str
    country: str
    ev_ebitda: float | str
    ev_sales: float | str = "-"
    forward_pe: float | str
    p_b: float | str = "-"
    ebit_margin_pct: float | str
    nd_ebitda: float | str
    dividend_yield_pct: float | str
    revenue_growth_pct: float | str
    roic_pct: float | str
    fcf_yield_pct: float | str = "-"


class PeerComparisonTable(BaseModel):
    sector: str
    sector_relevant_multiples: list[str]   # LLM-bestimmt pro Sektor
    peers: list[PeerCompanyData]
    sector_averages: PeerCompanyData       # Durchschnitt aller Peers
    subject_company: PeerCompanyData       # Das analysierte Unternehmen
    subject_vs_avg: dict                   # Abweichung in % je Kennzahl
    methodology: str


# ── Supervisor / Final Memo ──────────────────────────────────────────────────

class ConsensusEstimateYear(BaseModel):
    year: str
    type: Literal["A", "E"] = Field(description="A=Actual, E=Estimate")
    revenue_bn: float | str
    ebitda_margin_pct: float | str
    eps: float | str
    ev_ebitda: float | str
    pe_ratio: float | str
    number_of_analysts: int | str

class ValuationTableRow(BaseModel):
    metric: str
    current_value: str
    peer_average: str
    historical_average: str
    assessment: Literal["DISCOUNT", "FAIR", "ELEVATED"]
    source: str

class ScenarioTable(BaseModel):
    name: Literal["Bear Case", "Base Case", "Bull Case"]
    probability_pct: int
    price_target: float
    key_assumption: str
    trigger: str

class MacroAmpel(BaseModel):
    category: Literal["Makro", "Branche", "Unternehmen", "Konkurrenz"]
    signal: Literal["positiv", "neutral", "negativ"]
    key_point: str

class QualityCheck(BaseModel):
    check: str = Field(description="What was verified")
    result: Literal["bestanden", "Warnung", "fehlgeschlagen"]
    comment: str

class SupervisorOutput(BaseModel):
    # ── Header ────────────────────────────────────────────────
    ticker: str
    company: str
    sector: str
    date: str
    final_recommendation: Literal["KAUFEN", "ÜBERGEWICHTEN", "HALTEN", "UNTERGEWICHTEN", "VERKAUFEN"]
    conviction_level: Literal["hoch", "mittel", "niedrig"]
    price_target: float
    current_price: float
    upside_downside_pct: float
    currency: str

    # ── Datenvollständigkeit ────────────────────────────────
    analysis_incomplete: bool = Field(
        default=False,
        description=(
            "True, wenn ein Kern-Agent (z.B. Fundamental) nach allen Retries "
            "keinen validen Output geliefert hat. Wird deterministisch gesetzt, "
            "nicht vom LLM."
        )
    )
    missing_components: list[str] = Field(
        default_factory=list,
        description="Namen der Agenten/Komponenten, deren Output fehlt oder fehlerhaft ist."
    )

    # ── Executive Summary (laientauglich, kein Fachjargon) ────
    executive_summary: str = Field(
        default="",
        description=(
            "3-5 Sätze in EINFACHER Sprache für Nicht-Experten. KEIN Fachjargon "
            "(kein 'EV/EBITDA', 'DCF', 'Multiple'). Erklärt in Alltagssprache: "
            "Was macht die Firma? Ist die Aktie aktuell teuer oder günstig? "
            "Was ist die Empfehlung und der EINE wichtigste Grund dafür? "
            "Was ist das grösste Risiko? Ein interessierter Laie ohne "
            "Finanzausbildung muss es verstehen können."
        )
    )
    summary_bottom_line: str = Field(
        default="",
        description=(
            "EIN einziger Satz (max. 25 Wörter) in einfacher Sprache: die "
            "Kernaussage. z.B. 'Solides Unternehmen, aber die Aktie ist aktuell "
            "fair bewertet — abwarten lohnt sich.'"
        )
    )

    # ── Qualitätsprüfung ──────────────────────────────────────
    quality_checks: list[QualityCheck] = Field(
        description="Senior Analyst quality checks on junior outputs"
    )
    data_consistency_score: int = Field(
        ge=1, le=10,
        description="How consistent are the three agent outputs? 10=fully consistent, 1=major contradictions"
    )
    consistency_notes: str = Field(
        description="Explanation of any inconsistencies found between the three junior analyst outputs"
    )

    # ── Seite 1 ───────────────────────────────────────────────
    company_description: str = Field(
        description="Max. 3 precise sentences: business model, market position, key revenue drivers"
    )
    investment_case: list[FundamentalStrength] = Field(
        description=(
            "3-5 bullet points. Each must contain: concrete number + peer or historical "
            "comparison + source. E.g. 'EV/EBITDA 8x vs peer avg 10x and 5y avg 12x "
            "(Quelle: yfinance) → 20% discount to peers justifies BUY'"
        )
    )
    valuation_table: list[ValuationTableRow] = Field(
        description="Key multiples vs peers vs history"
    )
    consensus_estimates: list[ConsensusEstimateYear] = Field(
        description="2 historical years (A) + 3 forward years (E). Format: 2023A, 2024A, 2025E, 2026E, 2027E"
    )

    # ── Seite 2 ───────────────────────────────────────────────
    scenarios: list[ScenarioTable] = Field(
        description="Exactly 3 scenarios. Probabilities must sum to 100."
    )
    key_risks: list[str] = Field(
        description=(
            "2-3 specific quantified risks with time horizon. "
            "E.g. 'SNB +100bps → construction -5% → Holcim revenue -3% (mittelfristig)'"
        )
    )
    macro_ampel: list[MacroAmpel] = Field(
        description="Traffic light for Makro, Branche, Unternehmen, Konkurrenz"
    )
    conviction_killers: list[ConvictionKiller] = Field(
        description="1-2 absolute dealbreakers to monitor"
    )
    advocatus_diaboli_summary: str = Field(
        description="3 sentences max: strongest counter-arguments from Risk Agent"
    )
    monitoring_checklist: list[str] = Field(
        description=(
            "3-5 specific indicators/events the PM must monitor. "
            "E.g. 'Q3 Services Marge: Zielwert >28% — darunter kippt Bull Case'"
        )
    )

    # ── Erweiterte Finanzdaten ────────────────────────────────
    full_financials: list[FullFinancialYear] = Field(
        default_factory=list,
        description=(
            "Vollständige P&L-Übersicht: 3 historische Jahre (A) "
            "und 3 Forward-Jahre (E). Historisch aus IR-Dokument, "
            "Forward aus Consensus/Guidance/LLM-Ableitung."
        )
    )
    peer_comparison: Optional[PeerComparisonTable] = Field(
        default=None,
        description="Peer-Vergleich mit sektorspezifischen Kennzahlen"
    )

    # ── Footer ────────────────────────────────────────────────
    final_reasoning: str = Field(
        description=(
            "Senior analyst final synthesis: why this recommendation despite the "
            "counter-arguments. Format: 'Fundamental: [X] | Makro: [Y] | Risk: [Z] | "
            "Gewichtetes Fazit: [W]'"
        )
    )
    sources: list[str]