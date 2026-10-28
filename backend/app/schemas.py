"""Schemas públicos da API (fonte da verdade do contrato; ver API_CONTRACT.md).

Todos os datetimes são serializados em ISO 8601 UTC (ex.: 2026-10-28T22:39:41.123456Z).
Campos `None` significam "não disponível", nunca zero.
"""
from datetime import UTC, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


UTCdt = Annotated[datetime, PlainSerializer(_iso, return_type=str, when_used="json")]

Severity = Literal["info", "low", "medium", "high", "critical"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
RiskLevel = Literal["low", "moderate", "high", "critical"]
FreshnessStatus = Literal["fresh", "delayed", "stale", "no_data"]
SourceState = Literal["ok", "degraded", "down", "unknown"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Page(Out, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---------------- Auth ----------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class UserOut(Out):
    id: int
    username: str
    must_change_password: bool


class LoginResponse(Out):
    user: UserOut
    expires_at: UTCdt


# ---------------- Sistema ----------------
class HealthOut(Out):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str
    time: UTCdt


class SourceStatusOut(Out):
    source: str
    status: SourceState
    last_success_at: UTCdt | None
    last_error_at: UTCdt | None
    last_error: str | None
    consecutive_failures: int
    latency_ms_avg: float | None
    rate_limited_recent: int


class CollectorRunOut(Out):
    id: int
    source: str
    job: str
    started_at: UTCdt
    finished_at: UTCdt | None
    status: str
    requests: int
    items_received: int
    items_stored: int
    duplicates: int
    errors: int
    rate_limited: int
    latency_ms_avg: float | None
    error_message: str | None


class SystemSourcesOut(Out):
    sources: list[SourceStatusOut]
    recent_runs: list[CollectorRunOut]


# ---------------- Tokens ----------------
class TokenRef(Out):
    chain_id: str
    address: str
    symbol: str | None
    name: str | None
    image_url: str | None


class Freshness(Out):
    observed_at: UTCdt | None
    age_seconds: float | None
    status: FreshnessStatus
    source: str
    source_status: SourceState


class PairOut(Out):
    chain_id: str
    pair_address: str
    dex_id: str | None
    labels: list[str] | None
    quote_symbol: str | None
    quote_address: str | None
    url: str | None
    pair_created_at: UTCdt | None


class MarketOut(Out):
    price_usd: float | None
    price_native: float | None
    price_change_m5: float | None
    price_change_h1: float | None
    price_change_h6: float | None
    price_change_h24: float | None
    liquidity_usd: float | None
    market_cap: float | None
    fdv: float | None
    volume_m5: float | None
    volume_h1: float | None
    volume_h6: float | None
    volume_h24: float | None
    buys_h1: int | None
    sells_h1: int | None
    buys_h24: int | None
    sells_h24: int | None


class ScoresOut(Out):
    computed_at: UTCdt
    engine_version: str
    risk_score: float
    risk_level: RiskLevel
    risk_confidence: float
    insufficient_data: bool
    opportunity_score: float
    opportunity_confidence: float


class TokenListItem(Out):
    token: TokenRef
    discovered_via: str
    first_seen_at: UTCdt
    is_tracked: bool
    pair: PairOut | None
    pair_age_hours: float | None
    market: MarketOut | None
    freshness: Freshness
    scores: ScoresOut | None
    open_alerts: int


class FactorOut(Out):
    id: str
    category: str
    label: str
    points: float
    severity: str
    confidence: float
    evidence: dict


class AnalysisOut(ScoresOut):
    id: int
    risk_factors: list[FactorOut]
    opportunity_factors: list[FactorOut]
    checks_not_performed: list[dict]
    data_quality: dict
    invalidation_conditions: list[str]
    features: dict
    horizon_note: str = "Scores descrevem o estado atual (janelas de 5 min a 24 h); não são probabilidade de lucro."


class CheckOut(Out):
    check_type: str
    status: Literal["ok", "flagged", "unavailable", "error", "not_applicable"]
    checked_at: UTCdt
    source: str
    method_version: str
    result: dict | None


class TechnicalChecksOut(Out):
    supported: bool
    note: str
    mint: CheckOut | None
    holders: CheckOut | None


class AlertOut(Out):
    id: int
    alert_type: str
    category: Literal["risk", "opportunity", "system"]
    severity: Severity
    status: AlertStatus
    title: str
    reason: str
    evidence: dict
    confidence: float
    rule_id: str
    rule_version: str
    event_at: UTCdt | None
    detected_at: UTCdt
    last_occurrence_at: UTCdt
    occurrences: int
    status_changed_at: UTCdt | None
    token: TokenRef | None
    pair_address: str | None
    link: str | None


class AlertStatusUpdate(BaseModel):
    status: AlertStatus


class PredictionOut(Out):
    id: int
    token: TokenRef
    target: str
    target_description: str
    horizon_seconds: int
    threshold: float
    created_at: UTCdt
    resolve_at: UTCdt
    probability: float
    calibrated: bool
    baseline_probability: float | None
    model_id: str
    model_version: str
    reference_price_usd: float
    status: Literal["pending", "evaluated", "unevaluable"]
    outcome: bool | None
    observed_max_return: float | None
    observed_min_return: float | None
    observed_end_return: float | None
    observations_count: int | None
    outcome_detail: str | None
    evaluated_at: UTCdt | None


class ExitScenario(Out):
    position_usd: float
    tokens_sold: float
    price_impact: float
    estimated_avg_price_usd: float
    estimated_received_usd: float
    share_of_pool_base: float


class ExitEstimateOut(Out):
    available: bool
    reason: str | None
    method_version: str
    pool_model: Literal["constant_product", "concentrated", "bonding_curve", "unsupported", "unknown"]
    pool_model_note: str
    spot_price_usd: float | None
    liquidity_usd: float | None
    fees_included: bool
    unknown_costs: list[str]
    scenarios: list[ExitScenario]
    freshness: Freshness
    disclaimer: str = (
        "Estimativa informativa baseada no último snapshot. Não é recomendação de investimento "
        "e não garante execução a esse preço."
    )


class TokenDetail(TokenListItem):
    links: list[dict] | None
    pairs: list[PairOut]
    analysis: AnalysisOut | None
    technical_checks: TechnicalChecksOut
    recent_alerts: list[AlertOut]
    recent_predictions: list[PredictionOut]
    exit_estimate: ExitEstimateOut | None
    wallet_intelligence: dict
    social: dict


class HistoryPoint(Out):
    t: UTCdt
    price_usd: float | None
    liquidity_usd: float | None
    market_cap: float | None
    volume_h1: float | None
    buys_h1: int | None
    sells_h1: int | None


class HistoryOut(Out):
    token: TokenRef
    pair_address: str | None
    range: Literal["1h", "6h", "24h", "7d"]
    points: list[HistoryPoint]
    downsampled: bool
    source: str
    note: str = "Pontos são snapshots coletados por este sistema (não candles OHLC da fonte)."


class TrackRequest(BaseModel):
    chain_id: str = Field(min_length=1, max_length=32)
    address: str = Field(min_length=20, max_length=128)


# ---------------- Previsões ----------------
class PredictionMetricsOut(Out):
    target: str
    model_id: str
    model_version: str
    calibrated: bool
    total: int
    pending: int
    evaluated: int
    unevaluable: int
    observed_rate: float | None
    brier_model: float | None
    brier_model_where_baseline: float | None
    brier_baseline: float | None
    baseline_samples: int
    thresholds: list[dict]
    calibration_bins: list[dict]
    by_liquidity: list[dict]
    sufficient_sample: bool
    notes: list[str]


# ---------------- Dashboard ----------------
class RankedToken(Out):
    token: TokenRef
    risk_score: float
    risk_level: RiskLevel
    opportunity_score: float
    liquidity_usd: float | None
    freshness_status: FreshnessStatus
    link: str


class DashboardSummary(Out):
    generated_at: UTCdt
    tokens_tracked: int
    tokens_with_fresh_data: int
    alerts_open_total: int
    alerts_open_by_severity: dict[str, int]
    critical_risk_tokens: int
    opportunity_candidates: int
    aggregate_liquidity_usd: float | None
    aggregate_volume_h24_usd: float | None
    predictions: dict[str, int]
    last_refresh_at: UTCdt | None
    sources: list[SourceStatusOut]
    top_opportunities: list[RankedToken]
    top_risks: list[RankedToken]


class MetaOut(Out):
    chains: list[str]
    alert_types: dict[str, str]
    severities: list[str]
    risk_levels: list[str]
    token_sort_fields: list[str]
    prediction_targets: dict[str, str]
    engine_version: str
    freshness_thresholds_seconds: dict[str, int]
