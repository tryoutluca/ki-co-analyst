from pydantic import BaseModel, Field
from typing import Literal

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
    recommendation: Literal["KAUFEN", "HALTEN", "VERKAUFEN"]
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
    original_recommendation: Literal["KAUFEN", "HALTEN", "VERKAUFEN"]
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
    final_recommendation: Literal["KAUFEN", "HALTEN", "VERKAUFEN"]
    conviction_level: Literal["hoch", "mittel", "niedrig"]
    price_target: float
    current_price: float
    upside_downside_pct: float
    currency: str

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
    investment_case: list[str] = Field(
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

    # ── Footer ────────────────────────────────────────────────
    final_reasoning: str = Field(
        description=(
            "Senior analyst final synthesis: why this recommendation despite the "
            "counter-arguments. Format: 'Fundamental: [X] | Makro: [Y] | Risk: [Z] | "
            "Gewichtetes Fazit: [W]'"
        )
    )
    sources: list[str]