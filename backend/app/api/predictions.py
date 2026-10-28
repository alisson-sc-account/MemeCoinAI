from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import api_error, current_user
from app.api.views import predictions_out
from app.db import get_db
from app.engine.predict import TARGETS, compute_metrics
from app.ingest.normalize import normalize_address
from app.models import Prediction, Token
from app.schemas import Page, PredictionMetricsOut, PredictionOut

router = APIRouter(prefix="/predictions", tags=["predictions"], dependencies=[Depends(current_user)])


@router.get("", response_model=Page[PredictionOut])
def list_predictions(
    db: Session = Depends(get_db),
    status: list[Literal["pending", "evaluated", "unevaluable"]] | None = Query(None),
    target: str | None = None,
    chain_id: str | None = None,
    address: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    stmt = select(Prediction)
    if status:
        stmt = stmt.where(Prediction.status.in_(status))
    if target:
        if target not in TARGETS:
            raise api_error(422, "invalid_target", f"target deve ser um de {sorted(TARGETS)}")
        stmt = stmt.where(Prediction.target == target)
    if address:
        if not chain_id:
            raise api_error(422, "chain_required", "address exige chain_id")
        tid = db.scalar(select(Token.id).where(Token.chain_id == chain_id, Token.address == normalize_address(chain_id, address)))
        stmt = stmt.where(Prediction.token_id == (tid if tid is not None else -1))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Prediction.created_at.desc(), Prediction.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[PredictionOut](items=predictions_out(db, list(rows)), total=total, page=page, page_size=page_size)


@router.get("/metrics", response_model=list[PredictionMetricsOut])
def metrics(db: Session = Depends(get_db), target: str | None = None):
    if target and target not in TARGETS:
        raise api_error(422, "invalid_target", f"target deve ser um de {sorted(TARGETS)}")
    return compute_metrics(db, target)
