from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import api_error, current_user
from app.api.views import alerts_out
from app.db import get_db, utcnow
from app.ingest.normalize import normalize_address
from app.models import Alert, Token, User
from app.schemas import AlertOut, AlertStatusUpdate, Page

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=Page[AlertOut])
def list_alerts(
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
    status: list[Literal["open", "acknowledged", "resolved"]] | None = Query(None),
    severity: list[Literal["info", "low", "medium", "high", "critical"]] | None = Query(None),
    category: list[Literal["risk", "opportunity", "system"]] | None = Query(None),
    alert_type: list[str] | None = Query(None),
    chain_id: str | None = None,
    address: str | None = None,
    since: datetime | None = Query(None, description="ISO 8601; filtra detected_at >= since"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    stmt = select(Alert)
    if status:
        stmt = stmt.where(Alert.status.in_(status))
    if severity:
        stmt = stmt.where(Alert.severity.in_(severity))
    if category:
        stmt = stmt.where(Alert.category.in_(category))
    if alert_type:
        stmt = stmt.where(Alert.alert_type.in_(alert_type))
    if address:
        if not chain_id:
            raise api_error(422, "chain_required", "address exige chain_id")
        tid = db.scalar(select(Token.id).where(Token.chain_id == chain_id, Token.address == normalize_address(chain_id, address)))
        stmt = stmt.where(Alert.token_id == (tid if tid is not None else -1))
    elif chain_id:
        stmt = stmt.where(Alert.token_id.in_(select(Token.id).where(Token.chain_id == chain_id)))
    if since:
        stmt = stmt.where(Alert.detected_at >= since)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Alert.detected_at.desc(), Alert.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return Page[AlertOut](items=alerts_out(db, list(rows)), total=total, page=page, page_size=page_size)


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = db.get(Alert, alert_id)
    if a is None:
        raise api_error(404, "alert_not_found", "Alerta não encontrado")
    return alerts_out(db, [a])[0]


@router.patch("/{alert_id}", response_model=AlertOut)
def update_alert_status(
    alert_id: int, body: AlertStatusUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    a = db.get(Alert, alert_id)
    if a is None:
        raise api_error(404, "alert_not_found", "Alerta não encontrado")
    if a.status != body.status:
        a.status = body.status
        a.status_changed_at = utcnow()
        a.status_changed_by = user.id
        db.commit()
    return alerts_out(db, [a])[0]
