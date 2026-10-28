from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import current_user
from app.api.views import build_list_items, token_link, token_ref
from app.config import get_settings
from app.db import get_db, utcnow
from app.engine.alerts import ALERT_TYPES
from app.engine.predict import TARGETS
from app.engine.scoring import ENGINE_VERSION
from app.api.tokens import SORT_FIELDS
from app.api.views import TARGET_DESCRIPTIONS
from app.ingest.service import source_status
from app.models import Alert, CollectorRun, Prediction, Token
from app.schemas import DashboardSummary, HealthOut, MetaOut, RankedToken, SystemSourcesOut
from app.sources import dexscreener, solana_rpc

router = APIRouter(tags=["system"])
SOURCES = (dexscreener.SOURCE_NAME, solana_rpc.SOURCE_NAME)


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return HealthOut(status="ok" if db_ok else "degraded", database="ok" if db_ok else "error",
                     version=__version__, time=utcnow())


@router.get("/system/sources", response_model=SystemSourcesOut, dependencies=[Depends(current_user)])
def sources(db: Session = Depends(get_db)):
    runs = db.scalars(select(CollectorRun).order_by(CollectorRun.started_at.desc()).limit(30)).all()
    return SystemSourcesOut(sources=[source_status(db, s) for s in SOURCES], recent_runs=list(runs))


@router.get("/meta", response_model=MetaOut, dependencies=[Depends(current_user)])
def meta():
    s = get_settings()
    return MetaOut(
        chains=s.chain_list, alert_types=ALERT_TYPES, severities=["info", "low", "medium", "high", "critical"],
        risk_levels=["low", "moderate", "high", "critical"], token_sort_fields=sorted(SORT_FIELDS),
        prediction_targets={k: TARGET_DESCRIPTIONS.get(k, k) for k in TARGETS}, engine_version=ENGINE_VERSION,
        freshness_thresholds_seconds={"fresh": s.fresh_max_age_seconds, "delayed": s.delayed_max_age_seconds},
    )


@router.get("/dashboard/summary", response_model=DashboardSummary, dependencies=[Depends(current_user)])
def dashboard(db: Session = Depends(get_db)):
    src_list = [source_status(db, s) for s in SOURCES]
    dex_state = src_list[0]["status"]
    tokens = db.scalars(select(Token).where(Token.is_tracked.is_(True))).all()
    items = build_list_items(db, list(tokens), dex_state)
    fresh = [i for i in items if i.freshness.status == "fresh"]
    sev_rows = db.execute(
        select(Alert.severity, func.count()).where(Alert.status.in_(("open", "acknowledged"))).group_by(Alert.severity)
    ).all()
    by_sev = {k: 0 for k in ("info", "low", "medium", "high", "critical")} | dict(sev_rows)
    opp_open = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.alert_type == "opportunity_candidate", Alert.status == "open")
    ) or 0
    pred_rows = dict(db.execute(select(Prediction.status, func.count()).group_by(Prediction.status)).all())
    scored = [i for i in items if i.scores]

    def ranked(i) -> RankedToken:
        tok = next(t for t in tokens if t.chain_id == i.token.chain_id and t.address == i.token.address)
        return RankedToken(token=token_ref(tok), risk_score=i.scores.risk_score, risk_level=i.scores.risk_level,
                           opportunity_score=i.scores.opportunity_score,
                           liquidity_usd=i.market.liquidity_usd if i.market else None,
                           freshness_status=i.freshness.status, link=token_link(tok))

    # Agregados usam somente dados frescos para não somar cotações antigas.
    liqs = [i.market.liquidity_usd for i in fresh if i.market and i.market.liquidity_usd is not None]
    vols = [i.market.volume_h24 for i in fresh if i.market and i.market.volume_h24 is not None]
    observed = [i.freshness.observed_at for i in items if i.freshness.observed_at]
    return DashboardSummary(
        generated_at=utcnow(), tokens_tracked=len(items), tokens_with_fresh_data=len(fresh),
        alerts_open_total=sum(by_sev.values()), alerts_open_by_severity=by_sev,
        critical_risk_tokens=sum(1 for i in scored if i.scores.risk_level == "critical"),
        opportunity_candidates=opp_open,
        aggregate_liquidity_usd=sum(liqs) if liqs else None, aggregate_volume_h24_usd=sum(vols) if vols else None,
        predictions={k: pred_rows.get(k, 0) for k in ("pending", "evaluated", "unevaluable")},
        last_refresh_at=max(observed) if observed else None, sources=src_list,
        top_opportunities=[ranked(i) for i in sorted(
            (i for i in scored if i.freshness.status in ("fresh", "delayed")),
            key=lambda i: i.scores.opportunity_score, reverse=True)[:5]],
        top_risks=[ranked(i) for i in sorted(scored, key=lambda i: i.scores.risk_score, reverse=True)[:5]],
    )
