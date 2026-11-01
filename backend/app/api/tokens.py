from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import board
from app.api.deps import api_error, current_user
from app.api.views import (
    alerts_out,
    build_list_items,
    freshness,
    latest_snapshots,
    position_out,
    predictions_out,
    signal_out,
    token_ref,
    tracked_list_items,
)
from app.db import get_db, utcnow
from app.engine import checks, exit_plan, outcomes
from app.engine.pipeline import analyze_token
from app.engine.signals import advise
from app.engine.slippage import DEFAULT_POSITIONS_USD, estimate_exit
from app.ingest.normalize import normalize_address
from app.ingest.service import source_status, track_token
from app.live import service as live
from app.safety import service as security
from app.models import Alert, Analysis, Pair, PairSnapshot, Position, Prediction, SecurityReport, Signal, Token, User
from app.schemas import (
    BuySimulationOut,
    SecurityOut,
    ExitPlanOut,
    AnalysisOut,
    CheckOut,
    ExitEstimateOut,
    FactorOut,
    HistoryOut,
    HistoryPoint,
    Page,
    PairOut,
    TechnicalChecksOut,
    TokenDetail,
    TokenListItem,
    TrackRequest,
)
from app.sources import dexscreener

router = APIRouter(prefix="/tokens", tags=["tokens"], dependencies=[Depends(current_user)])

SORT_FIELDS = {
    "opportunity_score": lambda i: i.scores.opportunity_score if i.scores else None,
    "risk_score": lambda i: i.scores.risk_score if i.scores else None,
    "liquidity_usd": lambda i: i.market.liquidity_usd if i.market else None,
    "volume_h24": lambda i: i.market.volume_h24 if i.market else None,
    "volume_h1": lambda i: i.market.volume_h1 if i.market else None,
    "price_change_h1": lambda i: i.market.price_change_h1 if i.market else None,
    "price_change_h24": lambda i: i.market.price_change_h24 if i.market else None,
    "market_cap": lambda i: i.market.market_cap if i.market else None,
    "pair_age_hours": lambda i: i.pair_age_hours,
    "first_seen_at": lambda i: i.first_seen_at,
    "observed_at": lambda i: i.freshness.observed_at,
}

RANGES = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(hours=24), "7d": timedelta(days=7)}


def _get_token(db: Session, chain_id: str, address: str) -> Token:
    t = db.scalar(select(Token).where(Token.chain_id == chain_id, Token.address == normalize_address(chain_id, address)))
    if t is None:
        raise api_error(404, "token_not_found", "Token não encontrado no sistema")
    return t


def _tokens_from_board(con, chain_id, min_liq, max_liq, min_vol, min_age, max_age, risk_level, freshness_status, sort, order, page, page_size):
    where, args = [], []
    for sql, value in (("chain_id = ?", chain_id), ("min_filter_liq >= ?", min_liq), ("min_filter_liq <= ?", max_liq), ("min_filter_vol >= ?", min_vol),
                       ("age >= ?", min_age), ("age <= ?", max_age)):
        if value not in (None, ""):
            where.append(sql)
            args.append(value)
    for col, values in (("risk_level", risk_level), ("freshness_status", freshness_status)):
        if values:
            where.append(f"{col} IN ({','.join('?' * len(values))})")
            args += list(values)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = con.execute(f"SELECT COUNT(*) FROM tokens{clause}", args).fetchone()[0]
    column = f"s_{sort}"  # `sort` já foi validado contra SORT_FIELDS
    rows = con.execute(f"SELECT payload FROM tokens{clause} ORDER BY {column} IS NULL, {column} {'DESC' if order == 'desc' else 'ASC'} LIMIT ? OFFSET ?",
                       [*args, page_size, (page - 1) * page_size]).fetchall()
    return Page[TokenListItem](items=[TokenListItem.model_validate_json(r[0]) for r in rows], total=total, page=page, page_size=page_size)


@router.get("", response_model=Page[TokenListItem])
def list_tokens(
    db: Session = Depends(get_db),
    q: str | None = Query(None, max_length=128, description="Ticker, nome ou endereço"),
    chain_id: str | None = None,
    tracked: bool | None = True,
    min_liquidity: float | None = Query(None, ge=0),
    max_liquidity: float | None = Query(None, ge=0),
    min_volume_h24: float | None = Query(None, ge=0),
    min_age_hours: float | None = Query(None, ge=0),
    max_age_hours: float | None = Query(None, ge=0),
    risk_level: list[Literal["low", "moderate", "high", "critical"]] | None = Query(None),
    freshness_status: list[Literal["fresh", "delayed", "stale", "no_data"]] | None = Query(None),
    sort: str = Query("opportunity_score"),
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    if sort not in SORT_FIELDS:
        raise api_error(422, "invalid_sort", f"sort deve ser um de {sorted(SORT_FIELDS)}")
    stmt = select(Token)
    if tracked is not None:
        stmt = stmt.where(Token.is_tracked.is_(tracked))
    if chain_id:
        stmt = stmt.where(Token.chain_id == chain_id)
    if q:
        qs = q.strip()
        stmt = stmt.where(or_(Token.symbol.ilike(f"%{qs}%"), Token.name.ilike(f"%{qs}%"), Token.address == qs, Token.address == qs.lower()))
    con = board.read_connection() if tracked is True and not q else None
    if con is not None:
        try:
            return _tokens_from_board(con, chain_id, min_liquidity, max_liquidity, min_volume_h24, min_age_hours, max_age_hours, risk_level,
                                      freshness_status, sort, order, page, page_size)
        finally:
            con.close()
    if tracked is True and not q:
        items = [i for i in tracked_list_items(db) if not chain_id or i.token.chain_id == chain_id]
    else:
        items = build_list_items(db, list(db.scalars(stmt).all()), source_status(db, dexscreener.SOURCE_NAME)["status"])

    def keep(i: TokenListItem) -> bool:
        liq = i.market.liquidity_usd if i.market else None
        vol = i.market.volume_h24 if i.market else None
        age = i.pair_age_hours
        if min_liquidity is not None and (liq is None or liq < min_liquidity):
            return False
        if max_liquidity is not None and (liq is None or liq > max_liquidity):
            return False
        if min_volume_h24 is not None and (vol is None or vol < min_volume_h24):
            return False
        if min_age_hours is not None and (age is None or age < min_age_hours):
            return False
        if max_age_hours is not None and (age is None or age > max_age_hours):
            return False
        if risk_level and (i.scores is None or i.scores.risk_level not in risk_level):
            return False
        if freshness_status and i.freshness.status not in freshness_status:
            return False
        return True

    items = [i for i in items if keep(i)]
    key = SORT_FIELDS[sort]
    # Valores ausentes sempre ao final, independentemente da ordem.
    present = [i for i in items if key(i) is not None]
    missing = [i for i in items if key(i) is None]
    present.sort(key=key, reverse=(order == "desc"))
    items = present + missing
    start = (page - 1) * page_size
    return Page[TokenListItem](items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)


@router.post("/track", response_model=TokenListItem, status_code=201, responses={404: {}, 502: {}})
def track(body: TrackRequest, db: Session = Depends(get_db)):
    token, res = track_token(db, body.chain_id, body.address)
    if not res.ok:
        raise api_error(502, "source_error", "Falha ao consultar a fonte de dados", {"source": "dexscreener", "error": res.error})
    if token is None:
        raise api_error(404, "not_found_on_source", "Nenhum par encontrado na fonte para este token como token-base")
    analyze_token(db, token, force=True)
    return build_list_items(db, [token], source_status(db, dexscreener.SOURCE_NAME)["status"])[0]


@router.delete("/{chain_id}/{address}/track", status_code=204)
def untrack(chain_id: str, address: str, db: Session = Depends(get_db)):
    t = _get_token(db, chain_id, address)
    t.is_tracked = False
    db.commit()
    return Response(status_code=204)


def _check_out(c) -> CheckOut | None:
    return CheckOut.model_validate(c) if c else None


@router.get("/{chain_id}/{address}", response_model=TokenDetail)
def token_detail(chain_id: str, address: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _get_token(db, chain_id, address)
    src = source_status(db, dexscreener.SOURCE_NAME)["status"]
    base = build_list_items(db, [t], src)[0]
    pairs = db.scalars(select(Pair).where(Pair.base_token_id == t.id).order_by(Pair.last_seen_at.desc())).all()
    a = db.scalar(select(Analysis).where(Analysis.token_id == t.id).order_by(Analysis.computed_at.desc()).limit(1))
    analysis = None
    if a:
        analysis = AnalysisOut(
            id=a.id, computed_at=a.computed_at, engine_version=a.engine_version, risk_score=a.risk_score,
            risk_level=a.risk_level, risk_confidence=a.risk_confidence,
            insufficient_data=bool((a.data_quality or {}).get("insufficient_data")),
            opportunity_score=a.opportunity_score, opportunity_confidence=a.opportunity_confidence,
            risk_factors=[FactorOut(**f) for f in a.risk_factors], opportunity_factors=[FactorOut(**f) for f in a.opportunity_factors],
            checks_not_performed=a.checks_not_performed, data_quality=a.data_quality,
            invalidation_conditions=a.invalidation_conditions, features=a.features,
        )
    supported = t.chain_id == "solana"
    tech = TechnicalChecksOut(
        supported=supported,
        note="Autoridades de mint/freeze e extensões Token-2022 via RPC Solana." if supported
        else f"Verificações técnicas não implementadas para {t.chain_id}; ausência de alerta não indica segurança.",
        mint=_check_out(checks.latest_check(db, t.id, checks.CHECK_MINT)) if supported else None,
        holders=_check_out(checks.latest_check(db, t.id, checks.CHECK_HOLDERS)) if supported else None,
    )
    alerts = db.scalars(select(Alert).where(Alert.token_id == t.id).order_by(Alert.detected_at.desc()).limit(20)).all()
    preds = db.scalars(select(Prediction).where(Prediction.token_id == t.id).order_by(Prediction.created_at.desc()).limit(10)).all()
    exit_est = _exit_estimate(db, t, src, DEFAULT_POSITIONS_USD)
    sig = db.scalar(select(Signal).where(Signal.token_id == t.id, Signal.status == "active").limit(1))
    estimates = outcomes.estimate(db, a.opportunity_score, a.risk_score) if a else []
    pos = db.scalar(select(Position).where(Position.user_id == user.id, Position.token_id == t.id))
    price_now = base.market.price_usd if base.market else None
    advice = advise(sig, pos, price_now, exit_est.model_dump() if exit_est else None, user)
    last_buy = db.scalar(select(Signal).where(Signal.token_id == t.id, Signal.action == "buy", Signal.reference_price_usd.is_not(None))
                         .order_by(Signal.created_at.desc()).limit(1))
    return TokenDetail(
        **base.model_dump(),
        buy_simulation=BuySimulationOut(signal_id=last_buy.id, signal_at=last_buy.created_at, entry_price_usd=last_buy.reference_price_usd,
                                        strength=last_buy.strength) if last_buy else None,
        signal=signal_out(sig, t, user) if sig else None, estimates=estimates,
        position=position_out(db, pos, t) if pos else None, advice=advice,
        links=t.links, pairs=[PairOut.model_validate(p) for p in pairs], analysis=analysis, technical_checks=tech,
        recent_alerts=alerts_out(db, list(alerts)), recent_predictions=predictions_out(db, list(preds)),
        exit_estimate=exit_est,
        wallet_intelligence={"status": "not_implemented", "note": "Inteligência de carteiras planejada (Fase 7); nenhum dado exibido."},
        social={"status": "links_only", "note": "Somente links declarados na fonte; não verificados e sem métricas sociais.", "links": t.links or []},
    )


def _exit_estimate(db: Session, t: Token, src: str, positions) -> ExitEstimateOut | None:
    if not t.primary_pair_id:
        return None
    pair = db.get(Pair, t.primary_pair_id)
    snap = latest_snapshots(db, [pair.id]).get(pair.id)
    est = estimate_exit(
        pair.dex_id, pair.labels, snap.price_usd if snap else None, snap.liquidity_base if snap else None,
        snap.liquidity_quote if snap else None, snap.liquidity_usd if snap else None, positions,
    )
    return ExitEstimateOut(**est, freshness=freshness(snap.received_at if snap else None, src))


@router.get("/{chain_id}/{address}/exit-plan", response_model=ExitPlanOut)
def token_exit_plan(chain_id: str, address: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Quando e quanto vender (regras `exit-1`) com o preço da atualização rápida (`app.live`).

    Cada consulta mantém o token na lista da atualização rápida por mais 60 s. Sem cotação
    rápida recente, usa o snapshot do coletor e diz isso em `live`.
    """
    t = _get_token(db, chain_id, address)
    try:
        live.request_watch(db, t.id)
    except OperationalError:
        db.rollback()  # banco ocupado: o pedido entra na próxima consulta, o plano sai mesmo assim
    feed = live.feed(db, t)
    src = source_status(db, dexscreener.SOURCE_NAME)["status"]
    snap = latest_snapshots(db, [t.primary_pair_id]).get(t.primary_pair_id) if t.primary_pair_id else None
    a = db.scalar(select(Analysis).where(Analysis.token_id == t.id).order_by(Analysis.computed_at.desc()).limit(1))
    sig = db.scalar(select(Signal).where(Signal.token_id == t.id, Signal.status == "active").limit(1))
    pos = db.scalar(select(Position).where(Position.user_id == user.id, Position.token_id == t.id))
    if feed["status"] == "live":
        price, observed = feed["price_usd"], freshness(feed["observed_at"], "ok")
        observed.source = feed["source"]
        alerts, peak = live.live_alerts(db, t.id), live.peak_call(db, t.id)
    else:
        price, observed, alerts, peak = (snap.price_usd if snap else None), freshness(snap.received_at if snap else None, src), [], None
    estimates = outcomes.estimate(db, a.opportunity_score, a.risk_score) if a else []
    adv = advise(sig, pos, price, None, user)
    plan = exit_plan.build(price, snap.liquidity_usd if snap else None, a, sig, pos, estimates, adv, alerts, peak)
    return ExitPlanOut(**plan, has_position=pos is not None, freshness=observed, live=feed, generated_at=utcnow())


@router.get("/{chain_id}/{address}/security", response_model=SecurityOut)
def token_security(chain_id: str, address: str, db: Session = Depends(get_db)):
    """Última verificação de segurança (`sec-1`). "Sem alertas" nunca significa seguro."""
    t = _get_token(db, chain_id, address)
    r = db.get(SecurityReport, t.id)
    verdict = "danger" if t.rugged_at else r.verdict if r else "unknown"
    return SecurityOut(verdict=verdict, label=security.LABELS[verdict], checked_at=r.checked_at if r else None, rugged_at=t.rugged_at,
                       rug_reason=t.rug_reason, checks=r.checks if r else [], holders=r.holders if r else [],
                       total_holders=(r.facts or {}).get("total_holders") if r else None, service_running=security.running(db),
                       limitations=security.LIMITATIONS, rules_version=security.RULES_VERSION)


@router.get("/{chain_id}/{address}/exit-estimate", response_model=ExitEstimateOut)
def exit_estimate(
    chain_id: str, address: str, db: Session = Depends(get_db),
    positions: str | None = Query(None, description="Tamanhos em USD separados por vírgula (máx. 10)"),
):
    t = _get_token(db, chain_id, address)
    sizes = DEFAULT_POSITIONS_USD
    if positions:
        try:
            sizes = tuple(float(x) for x in positions.split(",") if x.strip())
        except ValueError:
            raise api_error(422, "invalid_positions", "positions deve conter números separados por vírgula")
        if not sizes or len(sizes) > 10 or any(x <= 0 or x > 1e9 for x in sizes):
            raise api_error(422, "invalid_positions", "1 a 10 valores positivos")
    est = _exit_estimate(db, t, source_status(db, dexscreener.SOURCE_NAME)["status"], sizes)
    if est is None:
        raise api_error(404, "no_pair", "Token sem par principal conhecido")
    return est


@router.get("/{chain_id}/{address}/history", response_model=HistoryOut)
def history(
    chain_id: str, address: str, db: Session = Depends(get_db),
    range: Literal["1h", "6h", "24h", "7d"] = "24h",
    max_points: int = Query(500, ge=10, le=2000),
):
    t = _get_token(db, chain_id, address)
    pair = db.get(Pair, t.primary_pair_id) if t.primary_pair_id else None
    points: list[HistoryPoint] = []
    downsampled = False
    if pair:
        rows = db.scalars(
            select(PairSnapshot)
            .where(PairSnapshot.pair_id == pair.id, PairSnapshot.received_at >= utcnow() - RANGES[range])
            .order_by(PairSnapshot.received_at)
        ).all()
        if len(rows) > max_points:
            step = -(-len(rows) // max_points)
            rows = rows[::step] + ([rows[-1]] if (len(rows) - 1) % step else [])
            downsampled = True
        points = [
            HistoryPoint(t=r.received_at, price_usd=r.price_usd, liquidity_usd=r.liquidity_usd, market_cap=r.market_cap,
                         volume_h1=r.volume_h1, buys_h1=r.buys_h1, sells_h1=r.sells_h1)
            for r in rows
        ]
    return HistoryOut(token=token_ref(t), pair_address=pair.pair_address if pair else None, range=range,
                      points=points, downsampled=downsampled, source=dexscreener.SOURCE_NAME)
