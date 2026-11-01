from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__, agents, board
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
from app.live import service as live
from app.models import Alert, CollectorRun, Prediction, Token
from app.schemas import AgentStatusOut, DashboardSummary, HealthOut, MetaOut, RankedToken, SourceRegistryOut, SystemSourcesOut
from app.sources import dexscreener, solana_rpc
from app.sources.registry import registry

router = APIRouter(tags=["system"])
SOURCES = (dexscreener.SOURCE_NAME, solana_rpc.SOURCE_NAME)


def worker_status(db: Session) -> dict:
    """O worker não tem porta própria: o estado vem da última coleta de mercado concluída."""
    interval = get_settings().refresh_interval_seconds
    last = db.scalar(
        select(CollectorRun)
        .where(CollectorRun.source == dexscreener.SOURCE_NAME, CollectorRun.job == "refresh",
               CollectorRun.finished_at.is_not(None))
        .order_by(CollectorRun.finished_at.desc())
        .limit(1)
    )
    if last is None:
        return {"status": "unknown", "last_cycle_at": None, "age_seconds": None,
                "expected_interval_seconds": interval, "last_cycle_duration_seconds": None}
    age = (utcnow() - last.finished_at).total_seconds()
    duration = round((last.finished_at - last.started_at).total_seconds(), 1)
    running = age <= max(3 * interval, 120)
    return {"status": "running" if running else "stopped", "last_cycle_at": last.finished_at,
            "age_seconds": round(age, 1), "expected_interval_seconds": interval,
            "last_cycle_duration_seconds": duration}


@router.get("/health", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    worker = worker_status(db) if db_ok else {"status": "unknown", "last_cycle_at": None, "age_seconds": None,
                                              "expected_interval_seconds": get_settings().refresh_interval_seconds}
    fast = live.service_status(db) if db_ok else None
    degraded = not db_ok or worker["status"] != "running" or fast["status"] != "running"
    return HealthOut(status="degraded" if degraded else "ok", database="ok" if db_ok else "error",
                     version=__version__, time=utcnow(), worker=worker, live=fast)


@router.get("/system/agents", response_model=list[AgentStatusOut], dependencies=[Depends(current_user)])
def system_agents(db: Session = Depends(get_db)):
    """Todos os agentes por categoria, com o estado de cada um."""
    return agents.status_list(db)


@router.get("/system/registry", response_model=list[SourceRegistryOut], dependencies=[Depends(current_user)])
def source_registry():
    """Todas as fontes do fluxograma com classe de custo/acesso (A/B/C/D) e estado real."""
    return registry()


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
    con = board.read_connection()
    if con is not None:
        try:
            row = con.execute("SELECT value FROM meta WHERE key='dashboard'").fetchone()
            if row:
                return DashboardSummary.model_validate_json(row[0])
        finally:
            con.close()
    return build_dashboard(db)


def build_dashboard(db: Session) -> DashboardSummary:
    src_list = [source_status(db, s) for s in SOURCES]
    dex_state = src_list[0]["status"]
    tokens = db.scalars(select(Token).where(Token.is_tracked.is_(True))).all()
    items = build_list_items(db, list(tokens), dex_state)
    by_key = {(t.chain_id, t.address): t for t in tokens}
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
        tok = by_key[(i.token.chain_id, i.token.address)]
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
