"""Modelo de dados persistente. Ver ARCHITECTURE.md (seção Persistência).

Convenções:
- Token é identificado por (chain_id, address). Ticker NUNCA é identidade.
- Par/pool é identificado por (chain_id, pair_address), separado do token.
- Timestamps em UTC. Em snapshots: `source_time` (horário informado pela fonte,
  quando existir), `received_at` (resposta recebida), `stored_at` (gravação).
- `None` significa "dado ausente/não informado" e nunca é tratado como zero.
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Guardamos apenas o SHA-256 do token; o token em si só existe no cookie.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class Token(Base):
    __tablename__ = "tokens"
    __table_args__ = (UniqueConstraint("chain_id", "address", name="uq_token_chain_address"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(String(128))
    symbol: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(256))
    # De onde o token entrou no universo monitorado: watchlist | dexscreener_profiles | dexscreener_boosts
    discovered_via: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Links públicos informados pela fonte (site, twitter, telegram). Não são validados.
    links: Mapped[list | None] = mapped_column(JSON)
    image_url: Mapped[str | None] = mapped_column(Text)
    primary_pair_id: Mapped[int | None] = mapped_column(
        ForeignKey("pairs.id", ondelete="SET NULL", use_alter=True)
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_risk_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Pair(Base):
    __tablename__ = "pairs"
    __table_args__ = (UniqueConstraint("chain_id", "pair_address", name="uq_pair_chain_address"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(32))
    pair_address: Mapped[str] = mapped_column(String(128))
    dex_id: Mapped[str | None] = mapped_column(String(64))
    labels: Mapped[list | None] = mapped_column(JSON)
    base_token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"), index=True)
    quote_address: Mapped[str | None] = mapped_column(String(128))
    quote_symbol: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(Text)
    pair_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PairSnapshot(Base):
    """Uma observação de mercado de um par num instante (Camada A)."""

    __tablename__ = "pair_snapshots"
    __table_args__ = (Index("ix_snap_pair_received", "pair_id", "received_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    source_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    stored_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    normalizer_version: Mapped[str] = mapped_column(String(16))
    payload_hash: Mapped[str] = mapped_column(String(64))

    price_usd: Mapped[float | None] = mapped_column(Float)
    price_native: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_base: Mapped[float | None] = mapped_column(Float)
    liquidity_quote: Mapped[float | None] = mapped_column(Float)
    fdv: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    volume_m5: Mapped[float | None] = mapped_column(Float)
    volume_h1: Mapped[float | None] = mapped_column(Float)
    volume_h6: Mapped[float | None] = mapped_column(Float)
    volume_h24: Mapped[float | None] = mapped_column(Float)
    buys_m5: Mapped[int | None] = mapped_column(Integer)
    sells_m5: Mapped[int | None] = mapped_column(Integer)
    buys_h1: Mapped[int | None] = mapped_column(Integer)
    sells_h1: Mapped[int | None] = mapped_column(Integer)
    buys_h6: Mapped[int | None] = mapped_column(Integer)
    sells_h6: Mapped[int | None] = mapped_column(Integer)
    buys_h24: Mapped[int | None] = mapped_column(Integer)
    sells_h24: Mapped[int | None] = mapped_column(Integer)
    price_change_m5: Mapped[float | None] = mapped_column(Float)
    price_change_h1: Mapped[float | None] = mapped_column(Float)
    price_change_h6: Mapped[float | None] = mapped_column(Float)
    price_change_h24: Mapped[float | None] = mapped_column(Float)
    # Lista de campos que vieram ausentes na resposta da fonte.
    missing_fields: Mapped[list | None] = mapped_column(JSON)
    # Payload bruto; apagado (NULL) pela retenção após RAW_PAYLOAD_RETENTION_DAYS.
    raw: Mapped[dict | None] = mapped_column(JSON)


class RiskCheck(Base):
    """Resultado de uma verificação específica (evidência antifraude)."""

    __tablename__ = "risk_checks"
    __table_args__ = (Index("ix_riskcheck_token_type_time", "token_id", "check_type", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"))
    check_type: Mapped[str] = mapped_column(String(64))
    # ok | flagged | unavailable | error | not_applicable
    status: Mapped[str] = mapped_column(String(16))
    result: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(16))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Analysis(Base):
    """Resultado do motor (risco + oportunidade) para um token num instante."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analysis_token_time", "token_id", "computed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"))
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pairs.id", ondelete="SET NULL"))
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("pair_snapshots.id", ondelete="SET NULL"))
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    engine_version: Mapped[str] = mapped_column(String(32))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    risk_confidence: Mapped[float] = mapped_column(Float)
    opportunity_score: Mapped[float] = mapped_column(Float)
    opportunity_confidence: Mapped[float] = mapped_column(Float)
    # Lista de fatores explicáveis, cada um com id, categoria, pontos, evidência.
    risk_factors: Mapped[list] = mapped_column(JSON)
    opportunity_factors: Mapped[list] = mapped_column(JSON)
    checks_not_performed: Mapped[list] = mapped_column(JSON)
    data_quality: Mapped[dict] = mapped_column(JSON)
    features: Mapped[dict] = mapped_column(JSON)
    invalidation_conditions: Mapped[list] = mapped_column(JSON)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_status_detected", "status", "detected_at"),
        Index("ix_alert_dedup", "dedup_key", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"), index=True)
    pair_id: Mapped[int | None] = mapped_column(ForeignKey("pairs.id", ondelete="SET NULL"))
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    alert_type: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))  # risk | opportunity | system
    severity: Mapped[str] = mapped_column(String(16))  # info | low | medium | high | critical
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | acknowledged | resolved
    title: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float)
    rule_id: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(16))
    event_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    dedup_key: Mapped[str] = mapped_column(String(256))
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    last_occurrence_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status_changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        Index("ix_pred_status_resolve", "status", "resolve_at"),
        Index("ix_pred_token_created", "token_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"))
    pair_id: Mapped[int] = mapped_column(ForeignKey("pairs.id", ondelete="CASCADE"))
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    model_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(64))
    horizon_seconds: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Float)
    reference_price_usd: Mapped[float] = mapped_column(Float)
    reference_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("pair_snapshots.id", ondelete="SET NULL")
    )
    probability: Mapped[float] = mapped_column(Float)
    calibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_probability: Mapped[float | None] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSON)
    resolve_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | evaluated | unevaluable
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[bool | None] = mapped_column(Boolean)
    observed_max_return: Mapped[float | None] = mapped_column(Float)
    observed_min_return: Mapped[float | None] = mapped_column(Float)
    observed_end_return: Mapped[float | None] = mapped_column(Float)
    observations_count: Mapped[int | None] = mapped_column(Integer)
    outcome_detail: Mapped[str | None] = mapped_column(Text)


class CollectorRun(Base):
    """Uma execução de coleta. Base para estado das fontes e latência."""

    __tablename__ = "collector_runs"
    __table_args__ = (Index("ix_run_source_started", "source", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    job: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | partial | error
    requests: Mapped[int] = mapped_column(Integer, default=0)
    items_received: Mapped[int] = mapped_column(Integer, default=0)
    items_stored: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    rate_limited: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms_avg: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
