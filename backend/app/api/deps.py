from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.models import User, UserSession
from app.security import hash_session_token

# Atualiza last_seen_at no máximo a cada 5 min (evita escrita por requisição).
_TOUCH_INTERVAL = timedelta(minutes=5)


def api_error(status: int, code: str, message: str, details=None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "details": details})


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise api_error(401, "unauthenticated", "Sessão ausente")
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_session_token(token)))
    now = utcnow()
    if sess is None or sess.revoked_at is not None or sess.expires_at <= now:
        raise api_error(401, "unauthenticated", "Sessão inválida ou expirada")
    if now - sess.last_seen_at > _TOUCH_INTERVAL:
        sess.last_seen_at = now
        try:
            db.commit()
        except OperationalError:
            # "último acesso" é só informativo: com o banco ocupado pelo coletor, não
            # derruba a requisição; tenta de novo na próxima.
            db.rollback()
    return sess


def current_user(sess: UserSession = Depends(current_session)) -> User:
    return sess.user
