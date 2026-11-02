"""Aviso no celular pelo ntfy.sh: grátis, sem conta e sem chave.

Na primeira vez sorteia um canal secreto, guardado em `data/ntfy_topic.txt` (fora do Git). Basta abrir
o link do canal no celular, uma vez. Quem souber o link vê os avisos, por isso ele é longo e aleatório.
O serviço grátis limita a ~250 mensagens por dia: vão só disparo extremo e compra forte, até `DAILY_CAP`.
Não vai saldo, posição nem nada pessoal: só nome da moeda, motivo e link público.
"""
import logging
import secrets
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.models import Alert, Signal, Token

log = logging.getLogger("notify")
DAILY_CAP = 200
_state: dict = {"alert": None, "signal": None, "day": None, "sent": 0}


def topic_path() -> Path:
    return BACKEND_DIR / "data" / "ntfy_topic.txt"


def topic() -> str:
    path = topic_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = f"memecoinai-{secrets.token_urlsafe(18)}"
    path.write_text(value, encoding="utf-8")
    return value


def phone_url() -> str:
    return f"{get_settings().ntfy_base_url}/{topic()}"


def send(title: str, body: str, link: str | None = None, client: httpx.Client | None = None, priority: str = "high") -> bool:
    if not get_settings().ntfy_enabled:
        return False
    day = time.strftime("%Y-%m-%d")
    if _state["day"] != day:
        _state.update(day=day, sent=0)
    if _state["sent"] >= DAILY_CAP:
        return False
    headers = {"Priority": priority, "Title": title.encode("ascii", "replace").decode()}
    if link:
        headers["Click"] = link
    try:
        r = (client or httpx).post(phone_url(), content=body.encode("utf-8"), headers=headers, timeout=8)
    except httpx.HTTPError as exc:
        log.warning("aviso no celular falhou: %s", exc)
        return False
    if r.status_code >= 400:
        log.warning("aviso no celular: HTTP %s", r.status_code)
        return False
    _state["sent"] += 1
    return True


def reset() -> None:
    _state.update(alert=None, signal=None, day=None, sent=0)


def _dex_link(token: Token) -> str:
    return f"https://dexscreener.com/{token.chain_id}/{token.address}"


def run_once(db: Session, client: httpx.Client | None = None) -> int:
    """Envia o que surgiu desde a última volta. Ao ligar, só marca onde está: não repete aviso antigo."""
    if not get_settings().ntfy_enabled:
        return 0
    max_alert = db.scalar(select(func.max(Alert.id))) or 0
    max_signal = db.scalar(select(func.max(Signal.id))) or 0
    if _state["alert"] is None:
        _state.update(alert=max_alert, signal=max_signal)
        return 0
    sent = 0
    alerts = db.scalars(select(Alert).where(Alert.id > _state["alert"], Alert.alert_type == "pump_burst", Alert.severity == "critical").order_by(Alert.id)).all()
    signals = db.scalars(select(Signal).where(Signal.id > _state["signal"], Signal.action == "buy", Signal.strength == "strong").order_by(Signal.id)).all()
    _state.update(alert=max_alert, signal=max_signal)
    for a in alerts:
        token = db.get(Token, a.token_id) if a.token_id else None
        if token and not token.rugged_at:
            sent += send(f"DISPARO {token.symbol or ''}".strip(), a.reason, _dex_link(token), client)
    for s in signals:
        token = db.get(Token, s.token_id)
        if token and not token.rugged_at:
            sent += send(f"COMPRA FORTE {token.symbol or ''}".strip(), s.headline, _dex_link(token), client)
    return sent
