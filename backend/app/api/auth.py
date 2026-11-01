import logging
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import api_error, current_session, current_user
from app.config import get_settings
from app.db import get_db, utcnow
from app.models import User, UserSession
from app.schemas import AccountSettings, ChangePasswordRequest, LoginRequest, LoginResponse, UserOut
from app.security import DUMMY_HASH, hash_password, hash_session_token, new_session_token, verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Limite simples em memória: 5 falhas por (usuário, IP) em 15 min.
_FAIL_WINDOW = 15 * 60
_FAIL_LIMIT = 5
_failures: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = threading.Lock()


def _too_many(key: tuple[str, str]) -> bool:
    with _lock:
        q = _failures[key]
        now = time.monotonic()
        while q and now - q[0] > _FAIL_WINDOW:
            q.popleft()
        return len(q) >= _FAIL_LIMIT


def _record_failure(key: tuple[str, str]) -> None:
    with _lock:
        _failures[key].append(time.monotonic())


def reset_login_limiter() -> None:
    with _lock:
        _failures.clear()


@router.post("/login", response_model=LoginResponse, responses={401: {}, 429: {}})
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    username = body.username.strip().lower()
    key = (username, request.client.host if request.client else "?")
    if _too_many(key):
        raise api_error(429, "too_many_attempts", "Muitas tentativas. Aguarde alguns minutos.")
    user = db.scalar(select(User).where(User.username == username))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not user or not ok:
        _record_failure(key)
        log.warning("login falhou para usuário=%s", username)  # nunca registra a senha
        raise api_error(401, "invalid_credentials", "Usuário ou senha inválidos")
    token = new_session_token()
    now = utcnow()
    sess = UserSession(
        token_hash=hash_session_token(token), user_id=user.id, created_at=now,
        expires_at=now + timedelta(hours=s.session_ttl_hours), last_seen_at=now,
    )
    user.last_login_at = now
    db.add(sess)
    db.commit()
    response.set_cookie(
        s.session_cookie_name, token, max_age=s.session_ttl_hours * 3600, httponly=True,
        secure=s.session_cookie_secure, samesite="lax", path="/",
    )
    log.info("login ok usuário=%s", username)
    return LoginResponse(user=UserOut.model_validate(user), expires_at=sess.expires_at)


@router.post("/logout", status_code=204)
def logout(response: Response, sess: UserSession = Depends(current_session), db: Session = Depends(get_db)):
    db_sess = db.get(UserSession, sess.id)
    db_sess.revoked_at = utcnow()
    db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/settings", response_model=AccountSettings)
def get_settings_route(user: User = Depends(current_user)):
    return AccountSettings(balance_amount=user.balance_amount, balance_currency=user.balance_currency,
                           max_trade_percent=user.max_trade_percent)


@router.put("/settings", response_model=AccountSettings)
def put_settings(body: AccountSettings, sess: UserSession = Depends(current_session), db: Session = Depends(get_db)):
    user = db.get(User, sess.user_id)
    user.balance_amount = body.balance_amount
    user.balance_currency = body.balance_currency
    user.max_trade_percent = body.max_trade_percent
    db.commit()
    return body


@router.post("/change-password", status_code=204)
def change_password(
    body: ChangePasswordRequest, sess: UserSession = Depends(current_session), db: Session = Depends(get_db)
):
    user = db.get(User, sess.user_id)
    if not verify_password(user.password_hash, body.current_password):
        raise api_error(400, "invalid_current_password", "Senha atual incorreta")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # Revoga as outras sessões do usuário.
    for other in db.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.id != sess.id)):
        other.revoked_at = other.revoked_at or utcnow()
    db.commit()
    return Response(status_code=204)
