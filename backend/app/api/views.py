"""Montagem das respostas a partir do banco (consultas de leitura)."""
import threading
import time
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.engine.signals import allocation
from app.ingest.service import source_status
from app.models import Alert, Analysis, Pair, PairSnapshot, Position, Prediction, Signal, Token
from app.schemas import (
    AlertOut,
    Freshness,
    MarketOut,
    PairOut,
    PositionOut,
    PredictionOut,
    ScoresOut,
    SignalOut,
    TokenListItem,
    TokenRef,
)
from app.sources import dexscreener

TARGET_DESCRIPTIONS = {
    "up_20pct_6h": "Preço máximo observado ≥ +20% do preço de referência em até 6 h",
    "down_30pct_6h": "Preço mínimo observado ≤ −30% do preço de referência em até 6 h",
}


def token_link(t: Token) -> str:
    return f"/tokens/{t.chain_id}/{t.address}"


def token_ref(t: Token) -> TokenRef:
    return TokenRef(chain_id=t.chain_id, address=t.address, symbol=t.symbol, name=t.name, image_url=t.image_url)


def freshness(observed_at: datetime | None, source_state: str) -> Freshness:
    s = get_settings()
    if observed_at is None:
        return Freshness(observed_at=None, age_seconds=None, status="no_data", source=dexscreener.SOURCE_NAME, source_status=source_state)
    age = (utcnow() - observed_at).total_seconds()
    status = "fresh" if age <= s.fresh_max_age_seconds else "delayed" if age <= s.delayed_max_age_seconds else "stale"
    if source_state == "down" and status == "fresh":
        status = "delayed"
    return Freshness(observed_at=observed_at, age_seconds=round(age, 1), status=status, source=dexscreener.SOURCE_NAME, source_status=source_state)


_list_cache: tuple[float, list] | None = None
_list_lock = threading.Lock()


def tracked_list_items(db: Session) -> list:
    """Todos os monitorados, calculados no máximo a cada `list_cache_seconds`: com 10 mil tokens a
    conta é pesada, e várias telas pedem a mesma lista."""
    global _list_cache
    ttl = get_settings().list_cache_seconds
    with _list_lock:
        if ttl > 0 and _list_cache and time.monotonic() - _list_cache[0] < ttl:
            return _list_cache[1]
        tokens = list(db.scalars(select(Token).where(Token.is_tracked.is_(True))))
        items = build_list_items(db, tokens, source_status(db, dexscreener.SOURCE_NAME)["status"])
        _list_cache = (time.monotonic(), items)
        return items


def latest_snapshots(db: Session, pair_ids: list[int]) -> dict[int, PairSnapshot]:
    if not pair_ids:
        return {}
    sub = (
        select(PairSnapshot.pair_id, func.max(PairSnapshot.received_at).label("mx"))
        .where(PairSnapshot.pair_id.in_(pair_ids))
        .group_by(PairSnapshot.pair_id)
        .subquery()
    )
    rows = db.scalars(
        select(PairSnapshot).join(sub, (PairSnapshot.pair_id == sub.c.pair_id) & (PairSnapshot.received_at == sub.c.mx))
    ).all()
    return {r.pair_id: r for r in rows}


def latest_analyses(db: Session, token_ids: list[int]) -> dict[int, Analysis]:
    if not token_ids:
        return {}
    sub = (
        select(Analysis.token_id, func.max(Analysis.computed_at).label("mx"))
        .where(Analysis.token_id.in_(token_ids))
        .group_by(Analysis.token_id)
        .subquery()
    )
    rows = db.scalars(
        select(Analysis).join(sub, (Analysis.token_id == sub.c.token_id) & (Analysis.computed_at == sub.c.mx))
    ).all()
    return {r.token_id: r for r in rows}


def open_alert_counts(db: Session, token_ids: list[int]) -> dict[int, int]:
    if not token_ids:
        return {}
    rows = db.execute(
        select(Alert.token_id, func.count())
        .where(Alert.token_id.in_(token_ids), Alert.status.in_(("open", "acknowledged")))
        .group_by(Alert.token_id)
    ).all()
    return dict(rows)


def market_out(s: PairSnapshot | None) -> MarketOut | None:
    if s is None:
        return None
    return MarketOut.model_validate(s, from_attributes=True)


def scores_out(a: Analysis | None) -> ScoresOut | None:
    if a is None:
        return None
    return ScoresOut(
        computed_at=a.computed_at, engine_version=a.engine_version, risk_score=a.risk_score, risk_level=a.risk_level,
        risk_confidence=a.risk_confidence, insufficient_data=bool((a.data_quality or {}).get("insufficient_data")),
        opportunity_score=a.opportunity_score, opportunity_confidence=a.opportunity_confidence,
    )


def _checked_at(snap: PairSnapshot | None, token: Token) -> datetime | None:
    """Última conferência na fonte. Resposta igual à anterior não vira snapshot, mas o dado foi conferido."""
    if snap is None:
        return None
    return max(snap.received_at, token.last_refreshed_at) if token.last_refreshed_at else snap.received_at


def build_list_items(db: Session, tokens: list[Token], source_state: str) -> list[TokenListItem]:
    pair_ids = [t.primary_pair_id for t in tokens if t.primary_pair_id]
    pairs = {p.id: p for p in db.scalars(select(Pair).where(Pair.id.in_(pair_ids)))} if pair_ids else {}
    snaps = latest_snapshots(db, pair_ids)
    analyses = latest_analyses(db, [t.id for t in tokens])
    counts = open_alert_counts(db, [t.id for t in tokens])
    now = utcnow()
    items = []
    for t in tokens:
        p = pairs.get(t.primary_pair_id) if t.primary_pair_id else None
        s = snaps.get(p.id) if p else None
        items.append(TokenListItem(
            token=token_ref(t), discovered_via=t.discovered_via, first_seen_at=t.first_seen_at, is_tracked=t.is_tracked,
            pair=PairOut.model_validate(p) if p else None,
            pair_age_hours=round((now - p.pair_created_at).total_seconds() / 3600, 3) if p and p.pair_created_at else None,
            market=market_out(s), freshness=freshness(_checked_at(s, t), source_state),
            scores=scores_out(analyses.get(t.id)), open_alerts=counts.get(t.id, 0),
        ))
    return items


def alert_out(a: Alert, token: Token | None, pair: Pair | None) -> AlertOut:
    return AlertOut(
        id=a.id, alert_type=a.alert_type, category=a.category, severity=a.severity, status=a.status, title=a.title,
        reason=a.reason, evidence=a.evidence or {}, confidence=a.confidence, rule_id=a.rule_id, rule_version=a.rule_version,
        event_at=a.event_at, detected_at=a.detected_at, last_occurrence_at=a.last_occurrence_at, occurrences=a.occurrences,
        status_changed_at=a.status_changed_at, token=token_ref(token) if token else None,
        pair_address=pair.pair_address if pair else None,
        link=f"/tokens/{token.chain_id}/{token.address}" if token else "/system",
    )


def alerts_out(db: Session, alerts: list[Alert]) -> list[AlertOut]:
    tids = {a.token_id for a in alerts if a.token_id}
    pids = {a.pair_id for a in alerts if a.pair_id}
    toks = {t.id: t for t in db.scalars(select(Token).where(Token.id.in_(tids)))} if tids else {}
    prs = {p.id: p for p in db.scalars(select(Pair).where(Pair.id.in_(pids)))} if pids else {}
    return [alert_out(a, toks.get(a.token_id), prs.get(a.pair_id)) for a in alerts]


def position_out(db: Session, p: Position, token: Token) -> PositionOut:
    snap = latest_snapshots(db, [token.primary_pair_id]).get(token.primary_pair_id) if token.primary_pair_id else None
    price = snap.price_usd if snap else None
    return PositionOut(
        token=token_ref(token), quantity=p.quantity, entry_price_usd=p.entry_price_usd, current_price_usd=price,
        value_usd=round(p.quantity * price, 2) if price else None,
        pnl=round(price / p.entry_price_usd - 1, 4) if price and p.entry_price_usd else None,
        updated_at=p.updated_at, link=token_link(token),
    )


def signal_out(s: Signal, token: Token, user=None) -> SignalOut:
    alloc = None
    if user is not None:
        alloc = allocation(s.action, s.strength, s.risk_score, user.balance_amount, user.balance_currency, user.max_trade_percent)
    return SignalOut(
        id=s.id, allocation=alloc, token=token_ref(token), action=s.action, strength=s.strength, status=s.status, headline=s.headline,
        reasons=s.reasons or [], risk_score=s.risk_score, risk_level=s.risk_level, opportunity_score=s.opportunity_score,
        reference_price_usd=s.reference_price_usd, estimates=s.estimates or [], created_at=s.created_at,
        last_confirmed_at=s.last_confirmed_at, rules_version=s.rules_version, link=token_link(token),
    )


def signals_out(db: Session, rows: list[Signal], user=None) -> list[SignalOut]:
    tids = {s.token_id for s in rows}
    toks = {t.id: t for t in db.scalars(select(Token).where(Token.id.in_(tids)))} if tids else {}
    return [signal_out(s, toks[s.token_id], user) for s in rows if s.token_id in toks]


def prediction_out(p: Prediction, token: Token) -> PredictionOut:
    return PredictionOut(
        id=p.id, token=token_ref(token), target=p.target, target_description=TARGET_DESCRIPTIONS.get(p.target, p.target),
        horizon_seconds=p.horizon_seconds, threshold=p.threshold, created_at=p.created_at, resolve_at=p.resolve_at,
        probability=p.probability, calibrated=p.calibrated, baseline_probability=p.baseline_probability,
        model_id=p.model_id, model_version=p.model_version, reference_price_usd=p.reference_price_usd,
        status=p.status, outcome=p.outcome, observed_max_return=p.observed_max_return,
        observed_min_return=p.observed_min_return, observed_end_return=p.observed_end_return,
        observations_count=p.observations_count, outcome_detail=p.outcome_detail, evaluated_at=p.evaluated_at,
    )


def predictions_out(db: Session, preds: list[Prediction]) -> list[PredictionOut]:
    tids = {p.token_id for p in preds}
    toks = {t.id: t for t in db.scalars(select(Token).where(Token.id.in_(tids)))} if tids else {}
    return [prediction_out(p, toks[p.token_id]) for p in preds if p.token_id in toks]
