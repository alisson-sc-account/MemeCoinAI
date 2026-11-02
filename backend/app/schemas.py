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
class WorkerStatusOut(Out):
    """Derivado da última coleta concluída (o worker não expõe porta própria)."""

    status: Literal["running", "stopped", "unknown"]
    last_cycle_at: UTCdt | None
    age_seconds: float | None
    expected_interval_seconds: int
    last_cycle_duration_seconds: float | None = None


class LiveServiceOut(Out):
    status: Literal["running", "stopped", "unknown"]
    last_tick_at: UTCdt | None
    age_seconds: float | None
    interval_seconds: int
    watched: int
    quoted: int
    last_error: str | None
    source: str


class AgentStatusOut(Out):
    name: str
    category: str
    label: str
    source: str
    process: str
    status: Literal["running", "stopped", "unknown"]
    last_tick_at: UTCdt | None
    age_seconds: float | None
    interval_seconds: int | None
    items: int
    last_duration_ms: float | None
    last_error: str | None


class HealthOut(Out):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    version: str
    time: UTCdt
    worker: WorkerStatusOut
    live: LiveServiceOut | None = None


class SourceRegistryOut(Out):
    key: str
    name: str
    role: str
    access_class: Literal["A", "B", "C", "D"]
    access_label: str
    enabled: bool
    integration: str
    needs_key: bool | None
    verified_on: str | None
    verification: str
    limits: str
    fallback: str


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


class HorizonEstimateOut(Out):
    """Distribuição empírica de retornos de análises passadas semelhantes.

    basis: `similar` (mesma faixa de oportunidade/risco), `general` (todas as
    amostras) ou `insufficient` (menos de `needed` amostras; campos numéricos nulos).
    Retornos são frações (0.12 = +12%) e brutos (sem taxas/slippage).
    """

    horizon: Literal["15m", "1h", "6h"]
    horizon_seconds: int
    basis: Literal["similar", "general", "insufficient"]
    n: int
    needed: int | None = None
    end_p25: float | None = None
    end_median: float | None = None
    end_p75: float | None = None
    max_median: float | None = None
    p_up_10: float | None = None
    p_up_20: float | None = None
    p_up_50: float | None = None
    p_down_20: float | None = None
    p_end_positive: float | None = None
    method_version: str


SignalAction = Literal["buy", "sell", "avoid", "hold"]


class AllocationOut(Out):
    """Quanto do saldo do usuário usar numa compra (regra `size-1`)."""

    percent_of_balance: float
    amount: float
    currency: Literal["BRL", "USD"]
    max_trade_percent: float
    rule: str


class AccountSettings(BaseModel):
    balance_amount: float | None = Field(None, ge=0, le=1e12, description="Saldo para simulação; null = não informado")
    balance_currency: Literal["BRL", "USD"] = "BRL"
    max_trade_percent: float = Field(10.0, gt=0, le=100, description="Teto por operação, em % do saldo")


class SignalOut(Out):
    id: int
    allocation: AllocationOut | None = None
    token: TokenRef
    action: SignalAction
    strength: Literal["strong", "moderate", "none"]
    status: Literal["active", "superseded"]
    headline: str
    reasons: list[str]
    risk_score: float
    risk_level: RiskLevel
    opportunity_score: float
    reference_price_usd: float | None
    estimates: list[HorizonEstimateOut]
    created_at: UTCdt
    last_confirmed_at: UTCdt
    rules_version: str
    link: str


class SignalPerformanceOut(Out):
    action: Literal["buy", "sell"]
    strength: str
    horizon: str
    n: int
    hit_rate: float
    big_move_rate: float
    median_end_return: float
    definition: str


class PositionIn(BaseModel):
    quantity: float = Field(gt=0, description="Quantidade de tokens")
    entry_price_usd: float | None = Field(None, gt=0)


class PositionOut(Out):
    token: TokenRef
    quantity: float
    entry_price_usd: float | None
    current_price_usd: float | None
    value_usd: float | None
    pnl: float | None
    updated_at: UTCdt
    link: str


class AdviceOut(Out):
    version: str
    has_position: bool
    action: Literal["buy", "sell", "hold", "none"]
    summary: str
    reasons: list[str]
    sell_percent: int | None = None
    keep_percent: int | None = None
    buy_percent_of_plan: int | None = None
    buy_percent_of_balance: float | None = None
    buy_amount: float | None = None
    currency: Literal["BRL", "USD"] | None = None
    position_value_usd: float | None = None
    pnl: float | None = None
    slippage_note: str | None = None
    disclaimer: str


class BuySimulationOut(Out):
    """Último sinal de compra da moeda: início automático da simulação no gráfico."""

    signal_id: int
    signal_at: UTCdt
    entry_price_usd: float
    strength: str


class SecurityCheckOut(Out):
    key: str
    label: str
    status: Literal["ok", "warn", "danger", "unknown"]
    detail: str


class SecurityHolderOut(Out):
    owner: str
    pct: float
    insider: bool = False
    fresh: bool | None = None
    age_hours: float | None = None
    funder: str | None = None
    cluster: int | None = None


class SecurityOut(Out):
    verdict: Literal["danger", "caution", "clear", "unknown"]
    label: str
    checked_at: UTCdt | None
    rugged_at: UTCdt | None
    rug_reason: str | None
    checks: list[SecurityCheckOut]
    holders: list[SecurityHolderOut]
    total_holders: int | None
    service_running: bool
    limitations: list[str]
    rules_version: str


class SmartWalletsOut(Out):
    available: bool
    wallets: int
    usd: float
    known_smart: int
    minutes: int


class PhoneOut(Out):
    enabled: bool
    url: str | None


class TokenDetail(TokenListItem):
    smart_wallets: SmartWalletsOut | None = None
    buy_simulation: BuySimulationOut | None = None
    signal: SignalOut | None
    estimates: list[HorizonEstimateOut]
    position: PositionOut | None
    advice: AdviceOut
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


class OpportunityOut(Out):
    token: TokenRef
    link: str
    tier: Literal["priority_buy", "possible_buy", "watch", "avoid"]
    tier_label: str
    decision_quality: Literal["ok", "partial", "no_reliable_signal"]
    decision_quality_reason: str
    score: float | None
    score_previous: float | None
    score_change: float | None
    confidence: float | None
    coverage: float | None
    risk_score: float | None
    risk_level: RiskLevel | None
    critical_blocks: list[str]
    reasons_for: list[str]
    reasons_against: list[str]
    missing_data: list[str]
    price_usd: float | None
    price_change_h1: float | None
    price_change_h24: float | None
    liquidity_usd: float | None
    volume_h24: float | None
    pair_age_hours: float | None
    dex_id: str | None
    freshness: Freshness
    signal_headline: str | None
    signal_since: UTCdt | None
    security_verdict: str = "unknown"
    signal_id: int | None = None
    allocation: AllocationOut | None
    computed_at: UTCdt | None
    ranking_version: str


class OpportunityPage(Out):
    items: list[OpportunityOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    generated_at: UTCdt
    ranking_version: str
    disclaimer: str = ("Classificação informativa gerada por regras sobre dados públicos. "
                       "Não é garantia de resultado nem recomendação financeira; o sistema não executa ordens.")


# ---------------- Acertos (acc-1) ----------------
class AccuracyCounts(Out):
    hits: int
    misses: int
    evaluated: int
    pending: int
    unevaluable: int
    hit_rate: float | None


class HorizonResult(Out):
    status: Literal["hit", "miss", "pending", "unevaluable"]
    resolves_at: UTCdt
    end_return: float | None = None
    max_return: float | None = None
    min_return: float | None = None
    end_price_usd: float | None = None


class AccuracyItem(Out):
    signal_id: int
    token: TokenRef
    link: str
    action: Literal["buy", "sell", "hold"]
    tier: Literal["priority_buy", "possible_buy", "watch", "sell"]
    tier_label: str
    prediction: str
    strength: str
    headline: str
    created_at: UTCdt
    reference_price_usd: float | None
    results: dict[str, HorizonResult]


class AccuracyPage(Out):
    horizon: Literal["15m", "1h", "6h"]
    summary: dict[str, dict[str, AccuracyCounts]]
    items: list[AccuracyItem]
    total: int
    page: int
    page_size: int
    rules_version: str
    definition: str = ("COMPRAR = previsão de subida: acerta se o preço ao fim do horizonte ficou acima do preço do sinal. "
                       "VENDER = previsão de queda: acerta se ficou abaixo. Só conta depois do horizonte; sem coleta "
                       "contínua na janela fica 'inavaliável'. Observar não é previsão: aparece como referência "
                       "(quantas vezes subiu mesmo sem sinal). Retornos brutos, sem taxas.")


# ---------------- Plano de venda (exit-1) ----------------
class TakeProfitOut(Out):
    label: str
    price_usd: float
    change_from_reference: float
    change_from_now: float
    sell_percent: int
    reached: bool


class StopOut(Out):
    price_usd: float
    change_from_reference: float
    change_from_now: float
    sell_percent: int
    reached: bool


class LiveFeedOut(Out):
    """Atualização rápida (`app.live`) do preço usado no plano de venda."""

    status: Literal["live", "waiting", "unavailable", "off"]
    source: str
    interval_seconds: int
    observed_at: UTCdt | None
    age_seconds: float | None
    price_usd: float | None
    liquidity_usd: float | None  # liquidez agregada da fonte rápida (não é a do par)
    note: str
    rules_version: str


class FlowOut(Out):
    """Compras e vendas dos últimos 30 s (só pump.fun e PumpSwap)."""

    buy_usd: float
    sell_usd: float
    buys: int
    sells: int


class ExitPlanOut(Out):
    version: str
    urgency: Literal["sell_now", "reduce", "hold", "no_data"]
    headline: str
    sell_percent_now: int | None
    keep_percent: int | None
    reference_price_usd: float | None
    reference_kind: str | None
    current_price_usd: float | None = None
    change_from_reference: float | None = None
    take_profits: list[TakeProfitOut]
    stop: StopOut | None
    triggers: list[str]
    reasons: list[str]
    has_position: bool
    freshness: Freshness
    live: LiveFeedOut
    flow: FlowOut | None = None
    generated_at: UTCdt
    disclaimer: str


class FavoriteCreate(BaseModel):
    chain_id: str
    address: str
    signal_id: int | None = None


class FavoriteOut(Out):
    id: int
    token: TokenRef
    link: str
    signal_id: int | None
    action: str | None
    strength: str | None
    tier_label: str
    prediction: str
    headline: str | None
    reasons: list[str]
    signal_at: UTCdt
    favorited_at: UTCdt
    seconds_signal_to_favorite: float
    reference_price_usd: float | None
    price_at_favorite: float | None
    gain_at_favorite: float | None
    max_gain_until_favorite: float | None
    min_gain_until_favorite: float | None
    value_of_100_usd_at_favorite: float | None
    liquidity_at_favorite: float | None
    specs: dict


class FavoriteSummary(Out):
    count: int
    with_gain: int
    positive: int
    negative: int
    avg_gain_at_favorite: float | None
    best_gain: float | None
    best_symbol: str | None
    worst_gain: float | None
    worst_symbol: str | None


class FavoritePage(Out):
    items: list[FavoriteOut]
    summary: FavoriteSummary
    generated_at: UTCdt
    rules_version: str
    disclaimer: str


class FavoriteReport(Out):
    text: str
    count: int
    generated_at: UTCdt
