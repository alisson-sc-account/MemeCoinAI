from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import api_error, current_user
from app.api.views import position_out, signal_out, signals_out
from app.db import get_db, utcnow
from app.engine.signals import performance
from app.ingest.normalize import normalize_address
from app.models import Position, Signal, Token, User
from app.schemas import Page, PositionIn, PositionOut, SignalOut, SignalPerformanceOut

router = APIRouter(tags=["signals"], dependencies=[Depends(current_user)])


@router.get("/signals", response_model=Page[SignalOut])
def list_signals(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    action: list[Literal["buy", "sell", "avoid", "hold"]] | None = Query(None),
    strength: list[Literal["strong", "moderate", "none"]] | None = Query(None),
    status: Literal["active", "all"] = "active",
    after_id: int | None = Query(None, ge=0, description="Somente sinais com id maior (para notificações)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    stmt = select(Signal)
    if status == "active":
        stmt = stmt.where(Signal.status == "active")
    if action:
        stmt = stmt.where(Signal.action.in_(action))
    if strength:
        stmt = stmt.where(Signal.strength.in_(strength))
    if after_id is not None:
        stmt = stmt.where(Signal.id > after_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Signal.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page[SignalOut](items=signals_out(db, list(rows), user), total=total, page=page, page_size=page_size)


@router.get("/signals/performance", response_model=list[SignalPerformanceOut])
def signals_performance(db: Session = Depends(get_db)):
    return performance(db)


@router.get("/signals/{signal_id}", response_model=SignalOut)
def get_signal(signal_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    s = db.get(Signal, signal_id)
    if s is None:
        raise api_error(404, "signal_not_found", "Sinal não encontrado")
    return signal_out(s, db.get(Token, s.token_id), user)


def _token(db: Session, chain_id: str, address: str) -> Token:
    t = db.scalar(select(Token).where(Token.chain_id == chain_id, Token.address == normalize_address(chain_id, address)))
    if t is None:
        raise api_error(404, "token_not_found", "Token não encontrado no sistema")
    return t


@router.get("/positions", response_model=list[PositionOut])
def list_positions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Position).where(Position.user_id == user.id).order_by(Position.updated_at.desc())).all()
    return [position_out(db, p, db.get(Token, p.token_id)) for p in rows]


@router.put("/positions/{chain_id}/{address}", response_model=PositionOut)
def upsert_position(chain_id: str, address: str, body: PositionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _token(db, chain_id, address)
    p = db.scalar(select(Position).where(Position.user_id == user.id, Position.token_id == t.id))
    if p is None:
        p = Position(user_id=user.id, token_id=t.id, quantity=body.quantity, created_at=utcnow())
        db.add(p)
    p.quantity = body.quantity
    p.entry_price_usd = body.entry_price_usd
    p.updated_at = utcnow()
    db.commit()
    return position_out(db, p, t)


@router.delete("/positions/{chain_id}/{address}", status_code=204)
def delete_position(chain_id: str, address: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _token(db, chain_id, address)
    p = db.scalar(select(Position).where(Position.user_id == user.id, Position.token_id == t.id))
    if p is not None:
        db.delete(p)
        db.commit()
    return Response(status_code=204)
