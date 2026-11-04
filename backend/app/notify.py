"""Aviso no celular pelo ntfy.sh: grátis, sem conta e sem chave.

Na primeira vez sorteia um canal secreto, guardado em `data/ntfy_topic.txt` (fora do Git). Basta abrir
o link do canal no celular, uma vez. Quem souber o link vê os avisos, por isso ele é longo e aleatório.
O que vai, com que prioridade, texto, filtros, horário silencioso e limites ficam em `app/notify_prefs.py`
(editável no site). O serviço grátis limita a ~250 mensagens por dia: o teto nunca passa de `DAILY_CAP`.
Não vai saldo, posição nem nada pessoal: só nome da moeda, motivo e link público.
"""
import base64
import logging
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import metrics, notify_prefs
from app.config import BACKEND_DIR, get_settings
from app.models import Alert, Favorite, PairSnapshot, Signal, Token

log = logging.getLogger("notify")
DAILY_CAP = 200
TOKEN_COOLDOWN = 3600.0  # padrão: a mesma moeda no máximo 1 aviso por hora (o sinal oscila e repetia aviso)
_last_by_token: dict[int, float] = {}
_hour: list[float] = []
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
    p = notify_prefs.load()
    return f"{p.server or get_settings().ntfy_base_url}/{p.topic or topic()}"


def _header(value: str) -> str:
    """Cabeçalho HTTP só aceita ASCII: acento e emoji vão no formato RFC 2047, que o ntfy entende."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode() + "?="


def send(title: str, body: str, link: str | None = None, client: httpx.Client | None = None, priority: str = "high",
         tags: str = "", force: bool = False) -> bool:
    if not get_settings().ntfy_enabled:
        return False
    prefs = notify_prefs.load()
    now = time.time()
    day = time.strftime("%Y-%m-%d")
    if _state["day"] != day:
        _state.update(day=day, sent=0)
    _hour[:] = [t for t in _hour if now - t < 3600]
    if not force and (_state["sent"] >= min(DAILY_CAP, prefs.daily_cap) or len(_hour) >= prefs.max_per_hour):
        return False
    headers = {"Priority": priority, "Title": _header(title)}
    if tags:
        headers["Tags"] = _header(tags)
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
    _hour.append(now)
    return True


def reset() -> None:
    _state.update(alert=None, signal=None, day=None, sent=0)
    _last_by_token.clear()
    _hour.clear()


def _fresh_for(token_id: int, cooldown: float = TOKEN_COOLDOWN) -> bool:
    now = time.time()
    if now - _last_by_token.get(token_id, 0.0) < cooldown:
        return False
    _last_by_token[token_id] = now
    return True


def _dex_link(token: Token) -> str:
    return f"https://axiom.trade/t/{token.address}"  # compras são feitas na Axiom


def _measure(kind: str, item_id: int, analysis_id: int | None, token_id: int, decided_at) -> None:
    """Atraso decisão -> aviso enviado, com a mesma correlação do log do motor (a<análise>)."""
    if decided_at is None:
        return
    lag = (datetime.now(UTC) - decided_at).total_seconds() * 1000
    metrics.observe(f"notify.decision_to_send.{kind}", lag)
    log.info("aviso corr=a%s/%s%s token=%s atraso_ms=%.0f", analysis_id, kind[0], item_id, token_id, lag)


def _liquidity(db: Session, token: Token) -> float | None:
    if not token.primary_pair_id:
        return None
    return db.scalar(select(PairSnapshot.liquidity_usd).where(PairSnapshot.pair_id == token.primary_pair_id)
                     .order_by(PairSnapshot.id.desc()).limit(1))


def _usd(v: float | None) -> str:
    if v is None:
        return "?"
    return f"US$ {v / 1e6:.1f} mi" if v >= 1e6 else f"US$ {v / 1e3:.0f} mil" if v >= 1e3 else f"US$ {v:.0f}"


def _candidates(db: Session, prefs) -> list[tuple]:
    """(tipo, item, token_id, motivo, score, risco) do que surgiu desde a última volta, por ordem de importância."""
    out = []
    for a in db.scalars(select(Alert).where(Alert.id > _state["alert"]).order_by(Alert.id)):
        kind = "burst" if a.alert_type == "pump_burst" else "risk" if a.category == "risk" else None
        if kind and a.token_id and notify_prefs.severity_ok(a.severity, prefs.rules[kind].min_severity):
            out.append((kind, a, a.token_id, a.reason, None, None))
    for s in db.scalars(select(Signal).where(Signal.id > _state["signal"]).order_by(Signal.id)):
        kind = {("buy", "strong"): "buy_strong", ("buy", "moderate"): "buy",
                ("sell", "strong"): "sell", ("sell", "moderate"): "sell"}.get((s.action, s.strength))
        if kind:
            out.append((kind, s, s.token_id, s.headline, s.opportunity_score, s.risk_score))
    order = list(notify_prefs.KINDS)
    return sorted(out, key=lambda c: order.index(c[0]))


def _passes(db: Session, prefs, token: Token, score, risk, favorites: set[int]) -> tuple[bool, float | None]:
    muted = {m.lower() for m in prefs.muted}
    if token.rugged_at or token.address.lower() in muted or (token.symbol or "").lower() in muted:
        return False, None
    fav = token.id in favorites
    if prefs.favorites_only and not fav:
        return False, None
    liq = _liquidity(db, token)
    if fav and prefs.favorites_bypass_filters:
        return True, liq
    if score is not None and score < prefs.min_opportunity_score:
        return False, liq
    if risk is not None and risk > prefs.max_risk_score:
        return False, liq
    if prefs.min_liquidity_usd and (liq or 0) < prefs.min_liquidity_usd:
        return False, liq
    return True, liq


def run_once(db: Session, client: httpx.Client | None = None) -> int:
    """Envia o que surgiu desde a última volta, segundo as preferências. Ao ligar, só marca onde está."""
    if not get_settings().ntfy_enabled:
        return 0
    max_alert = db.scalar(select(func.max(Alert.id))) or 0
    max_signal = db.scalar(select(func.max(Signal.id))) or 0
    if _state["alert"] is None:
        _state.update(alert=max_alert, signal=max_signal)
        return 0
    prefs = notify_prefs.load()
    candidates = _candidates(db, prefs) if prefs.enabled else []
    _state.update(alert=max_alert, signal=max_signal)
    if not candidates:
        return 0
    favorites = set(db.scalars(select(Favorite.token_id)))
    quiet = notify_prefs.in_quiet(prefs.quiet, time.strftime("%H:%M"))
    sent = 0
    for kind, item, token_id, reason, score, risk in candidates:
        rule = prefs.rules[kind]
        if not rule.enabled or (quiet and not (prefs.quiet.allow_urgent and rule.priority == "urgent")):
            continue
        token = db.get(Token, token_id)
        if not token:
            continue
        ok, liq = _passes(db, prefs, token, score, risk, favorites)
        if not ok or not _fresh_for(token.id, prefs.token_cooldown_minutes * 60):
            continue
        values = {"symbol": token.symbol or "", "name": token.name or "", "reason": reason or "",
                  "score": "?" if score is None else f"{score:.0f}", "risk": "?" if risk is None else f"{risk:.0f}",
                  "liquidity": _usd(liq), "address": token.address, "chain": token.chain_id,
                  "kind": notify_prefs.KINDS[kind]}
        ok = send(notify_prefs.render(rule.title, values), notify_prefs.render(prefs.body, values) or reason or "",
                  _dex_link(token), client, priority=rule.priority, tags=rule.tags)
        sent += ok
        if ok:
            is_alert = isinstance(item, Alert)
            _measure("alert" if is_alert else "signal", item.id, item.analysis_id, token.id,
                     item.detected_at if is_alert else item.created_at)
    return sent


def send_test(kind: str = "buy_strong", client: httpx.Client | None = None) -> bool:
    """Manda um aviso de exemplo com o visual do tipo escolhido (ignora filtros e limites)."""
    prefs = notify_prefs.load()
    rule = prefs.rules[kind]
    values = {"symbol": "TESTE", "name": "Moeda de teste", "reason": "Aviso de teste do MemeCoinAI.", "score": "80",
              "risk": "20", "liquidity": "US$ 50 mil", "address": "-", "chain": "solana",
              "kind": notify_prefs.KINDS[kind]}
    return send(notify_prefs.render(rule.title, values), notify_prefs.render(prefs.body, values),
                None, client, priority=rule.priority, tags=rule.tags, force=True)
