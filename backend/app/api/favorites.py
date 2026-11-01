"""Previsões favoritadas pelo usuário: registro do ganho e relatório para copiar (`fav-1`)."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import api_error, current_user
from app.api.views import token_ref
from app.db import get_db, utcnow
from app.engine import favorites
from app.ingest.normalize import normalize_address
from app.models import Favorite, Signal, Token, User
from app.schemas import FavoriteCreate, FavoriteOut, FavoritePage, FavoriteReport

router = APIRouter(prefix="/favorites", tags=["favorites"], dependencies=[Depends(current_user)])


def _evaluated(db: Session, user: User) -> list[dict]:
    favs = db.scalars(select(Favorite).where(Favorite.user_id == user.id).order_by(Favorite.favorited_at.desc())).all()
    tokens = {t.id: t for t in db.scalars(select(Token).where(Token.id.in_({f.token_id for f in favs})))} if favs else {}
    return [favorites.evaluate(f, tokens[f.token_id]) for f in favs]


def _out(item: dict) -> FavoriteOut:
    return FavoriteOut(**{**item, "token": token_ref(item["token"])})


@router.get("", response_model=FavoritePage)
def list_favorites(db: Session = Depends(get_db), user: User = Depends(current_user)):
    items = _evaluated(db, user)
    return FavoritePage(items=[_out(i) for i in items], summary=favorites.summarize(items), generated_at=utcnow(),
                        rules_version=favorites.RULES_VERSION, disclaimer=favorites.DISCLAIMER)


@router.get("/report", response_model=FavoriteReport)
def favorites_report(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Texto com todos os ganhos e especificações, feito para colar na conversa."""
    items = _evaluated(db, user)
    now = utcnow()
    return FavoriteReport(text=favorites.report_text(items, favorites.summarize(items), now), count=len(items), generated_at=now)


@router.post("", response_model=FavoriteOut, status_code=201, responses={404: {}})
def add_favorite(body: FavoriteCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Favorita a previsão indicada (ou o sinal ativo). Repetir o pedido devolve o registro original."""
    address = normalize_address(body.chain_id, body.address)
    token = db.scalar(select(Token).where(Token.chain_id == body.chain_id, Token.address == address))
    if token is None:
        raise api_error(404, "token_not_found", "Token não encontrado.")
    if body.signal_id is not None:
        signal = db.get(Signal, body.signal_id)
        if signal is None or signal.token_id != token.id:
            raise api_error(404, "signal_not_found", "Previsão não encontrada para este token.")
    else:
        signal = db.scalar(select(Signal).where(Signal.token_id == token.id, Signal.status == "active").limit(1))
    now = utcnow()
    existing = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.token_id == token.id,
                                                Favorite.signal_id == (signal.id if signal else None)))
    fav = existing or favorites.capture(db, user, token, signal, now)
    return _out(favorites.evaluate(fav, token))


@router.delete("/{favorite_id}", status_code=204, responses={404: {}})
def remove_favorite(favorite_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    fav = db.get(Favorite, favorite_id)
    if fav is None or fav.user_id != user.id:
        raise api_error(404, "favorite_not_found", "Favorito não encontrado.")
    db.delete(fav)
    db.commit()
    return Response(status_code=204)
