"""Ranking da aba "Compre agora": níveis, score, confiança e cobertura separados."""
import json
import threading
import time
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import board
from app.api.deps import api_error, current_user
from app.api.views import build_list_items, latest_analyses, token_link
from app.config import get_settings
from app.db import get_db, utcnow
from app.engine import ranking
from app.engine.signals import allocation
from app.ingest.service import source_status
from app.models import Analysis, SecurityReport, Signal, Token, User
from app.schemas import OpportunityOut, OpportunityPage
from app.sources import dexscreener

router = APIRouter(tags=["opportunities"], dependencies=[Depends(current_user)])

Tier = Literal["priority_buy", "possible_buy", "watch", "avoid"]


def _previous_scores(db: Session, token_ids: list[int]) -> dict[int, float]:
    """Score da penúltima análise de cada token (para mostrar a mudança recente)."""
    if not token_ids:
        return {}
    rows = db.execute(
        select(Analysis.token_id, Analysis.opportunity_score)
        .where(Analysis.token_id.in_(token_ids), Analysis.computed_at >= utcnow() - timedelta(hours=1))
        .order_by(Analysis.token_id, Analysis.computed_at.desc())
    ).all()
    seen: dict[int, int] = {}
    prev: dict[int, float] = {}
    for token_id, score in rows:
        seen[token_id] = seen.get(token_id, 0) + 1
        if seen[token_id] == 2:
            prev[token_id] = score
    return prev


@router.get("/opportunities", response_model=OpportunityPage)
def list_opportunities(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    tier: list[Tier] | None = Query(None, description="Repetível; padrão: todos"),
    sort: str = Query("tier", description=f"Um de {', '.join(ranking.SORT_FIELDS)}"),
    min_liquidity: float | None = Query(None, ge=0),
    max_age_hours: float | None = Query(None, ge=0, description="Idade máxima do par"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    if sort not in ranking.SORT_FIELDS:
        raise api_error(422, "invalid_sort", f"sort deve ser um de {list(ranking.SORT_FIELDS)}")
    con = board.read_connection()
    if con is not None:
        try:
            return _from_board(con, user, tier, sort, min_liquidity, max_age_hours, page, page_size)
        finally:
            con.close()
    all_rows = _ranked_rows(db)
    rows: list[dict] = []
    for row in all_rows:
        if min_liquidity is not None and (row["liquidity_usd"] is None or row["liquidity_usd"] < min_liquidity):
            continue
        if max_age_hours is not None and (row["pair_age_hours"] is None or row["pair_age_hours"] > max_age_hours):
            continue
        sig = row["_sig"]
        alloc = None
        if sig and row["tier"] in ("priority_buy", "possible_buy"):
            alloc = allocation(sig[0], sig[1], sig[2], user.balance_amount, user.balance_currency, user.max_trade_percent)
        rows.append({**{k: v for k, v in row.items() if k != "_sig"}, "allocation": alloc})

    counts = {t: 0 for t in ranking.TIER_ORDER}
    for r in rows:
        counts[r["tier"]] += 1
    if tier:
        rows = [r for r in rows if r["tier"] in tier]
    rows = ranking.sort_items(rows, sort)
    start = (page - 1) * page_size
    return OpportunityPage(
        items=[OpportunityOut(**r) for r in rows[start:start + page_size]], total=len(rows), page=page,
        page_size=page_size, counts=counts, generated_at=utcnow(), ranking_version=ranking.RANKING_VERSION,
    )


def _allocate(row: dict, user: User) -> dict:
    sig = row.pop("_sig", None)
    alloc = None
    if sig and row["tier"] in ("priority_buy", "possible_buy"):
        alloc = allocation(sig[0], sig[1], sig[2], user.balance_amount, user.balance_currency, user.max_trade_percent)
    return {**row, "allocation": alloc}


def _from_board(con, user: User, tier, sort: str, min_liquidity, max_age_hours, page: int, page_size: int) -> OpportunityPage:
    """Mesma lista e mesma ordem de `ranking.sort_items`, lida pronta. Ausentes sempre no fim."""
    where, args = [], []
    if min_liquidity is not None:
        where.append("liquidity_usd >= ?")
        args.append(min_liquidity)
    if max_age_hours is not None:
        where.append("pair_age_hours <= ?")
        args.append(max_age_hours)
    base = f" WHERE {' AND '.join(where)}" if where else ""
    counts = {t: 0 for t in ranking.TIER_ORDER} | dict(con.execute(f"SELECT tier, COUNT(*) FROM opportunities{base} GROUP BY tier", args).fetchall())
    if tier:
        where.append(f"tier IN ({','.join('?' * len(tier))})")
        args = [*args, *tier]
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = con.execute(f"SELECT COUNT(*) FROM opportunities{clause}", args).fetchone()[0]
    if sort == "tier":
        order = "tier_order, COALESCE(score, 0) DESC"
    else:
        order = f"{sort} IS NULL, {sort} {'ASC' if sort == 'risk_score' else 'DESC'}"
    rows = con.execute(f"SELECT payload FROM opportunities{clause} ORDER BY {order} LIMIT ? OFFSET ?", [*args, page_size, (page - 1) * page_size]).fetchall()
    return OpportunityPage(items=[OpportunityOut(**_allocate(json.loads(r[0]), user)) for r in rows], total=total, page=page, page_size=page_size,
                           counts=counts, generated_at=utcnow(), ranking_version=ranking.RANKING_VERSION)


_rows_cache: tuple[float, list[dict]] | None = None
_rows_lock = threading.Lock()


def _ranked_rows(db: Session) -> list[dict]:
    """Linhas do ranking sem a parte de cada usuário, calculadas no máximo a cada `list_cache_seconds`."""
    global _rows_cache
    ttl = get_settings().list_cache_seconds
    with _rows_lock:
        if ttl > 0 and _rows_cache and time.monotonic() - _rows_cache[0] < ttl:
            return _rows_cache[1]
        rows = _build_rows(db)
        _rows_cache = (time.monotonic(), rows)
        return rows


def _build_rows(db: Session) -> list[dict]:
    tokens = list(db.scalars(select(Token).where(Token.is_tracked.is_(True))))
    base = build_list_items(db, tokens, source_status(db, dexscreener.SOURCE_NAME)["status"])
    ids = [t.id for t in tokens]
    analyses = latest_analyses(db, ids)
    previous = _previous_scores(db, ids)
    gate = get_settings().security_gate
    verdicts = dict(db.execute(select(SecurityReport.token_id, SecurityReport.verdict)).all())
    signals = {s.token_id: s for s in db.scalars(select(Signal).where(Signal.status == "active", Signal.token_id.in_(ids)))} if ids else {}

    rows: list[dict] = []
    for item, tok in zip(base, tokens):
        a = analyses.get(tok.id)
        sig = signals.get(tok.id)
        market = item.market
        liq = market.liquidity_usd if market else None
        c = ranking.classify(a, (a.features if a else {}) or {}, sig.action if sig else None,
                             sig.strength if sig else None, item.freshness.status)
        verdict = verdicts.get(tok.id)
        if verdict == "danger":  # vale na hora, sem esperar a próxima análise
            c["tier"] = "avoid"
            c["critical_blocks"] = [*c["critical_blocks"], "Verificação de segurança: perigo"]
        elif gate and c["tier"] == "priority_buy" and verdict != "clear":  # compra prioritária exige verificação limpa
            c["tier"] = "possible_buy"
        score = a.opportunity_score if a else None
        prev = previous.get(tok.id)
        rows.append({
            **c, "token": item.token, "link": token_link(tok), "tier_label": ranking.TIER_LABELS[c["tier"]],
            "score": score, "score_previous": prev,
            "score_change": round(score - prev, 2) if score is not None and prev is not None else None,
            "confidence": a.opportunity_confidence if a else None,
            "coverage": (a.data_quality or {}).get("coverage") if a else None,
            "risk_score": a.risk_score if a else None, "risk_level": a.risk_level if a else None,
            "price_usd": market.price_usd if market else None,
            "price_change_h1": market.price_change_h1 if market else None,
            "price_change_h24": market.price_change_h24 if market else None,
            "liquidity_usd": liq, "volume_h24": market.volume_h24 if market else None,
            "pair_age_hours": item.pair_age_hours, "dex_id": item.pair.dex_id if item.pair else None,
            "freshness": item.freshness,
            "signal_headline": sig.headline if sig else None, "signal_since": sig.created_at if sig else None, "signal_id": sig.id if sig else None,
            "security_verdict": verdict or "unknown", "computed_at": a.computed_at if a else None, "_sig": (sig.action, sig.strength, sig.risk_score) if sig else None,
            "ranking_version": ranking.RANKING_VERSION,
        })
    return rows

