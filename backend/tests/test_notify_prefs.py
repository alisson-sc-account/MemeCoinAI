"""Aviso no celular personalizável: tipos, prioridade, texto, filtros, silêncio, limites, silenciadas e favoritas."""
import base64

import httpx
import pytest

from app import config, notify, notify_prefs
from app.ingest.service import track_token
from app.models import Favorite, Signal, User
from tests.conftest import SOL_MINT

API = "/api/v1"


@pytest.fixture
def phone(monkeypatch, tmp_path):
    monkeypatch.setenv("NTFY_ENABLED", "true")
    config.get_settings.cache_clear()
    monkeypatch.setattr(notify, "topic_path", lambda: tmp_path / "topic.txt")
    notify.reset()
    sent = []

    def handler(request):
        sent.append({"url": str(request.url), "body": request.content.decode(), **dict(request.headers)})
        return httpx.Response(200, json={})
    return sent, httpx.Client(transport=httpx.MockTransport(handler))


def _signal(db, token_id, action="buy", strength="strong", score=70.0, risk=10.0, headline="motivo"):
    db.add(Signal(token_id=token_id, action=action, strength=strength, status="active", headline=headline, reasons=[],
                  risk_score=risk, risk_level="low", opportunity_score=score, estimates=[], rules_version="sig-1"))
    db.commit()


def _save(**changes):
    p = notify_prefs.NotifyPrefs().model_dump()
    for k, v in changes.items():
        if k == "rules":
            for kind, rule in v.items():
                p["rules"][kind].update(rule)
        else:
            p[k] = v
    return notify_prefs.save(notify_prefs.NotifyPrefs.model_validate(p))


def _start(db, client):
    token, _ = track_token(db, "solana", SOL_MINT)
    notify.run_once(db, client)  # marca o ponto de partida
    return token


def _title(h):
    t = h["title"]
    return base64.b64decode(t[10:-2]).decode() if t.startswith("=?UTF-8?B?") else t


def test_defaults_keep_old_behavior(db, fake_dex, phone):
    sent, client = phone
    token = _start(db, client)
    _signal(db, token.id, strength="moderate")
    _signal(db, token.id, action="sell", strength="strong")
    assert notify.run_once(db, client) == 0  # compra moderada e venda vêm desligadas
    _signal(db, token.id)
    assert notify.run_once(db, client) == 1 and sent[0]["priority"] == "high" and sent[0]["tags"] == "green_circle"


def test_custom_text_priority_and_tags(db, fake_dex, phone):
    sent, client = phone
    _save(body="{reason} | score {score} | risco {risk} | {liquidity}",
          rules={"buy_strong": {"title": "Ação já: {symbol} ({kind})", "priority": "urgent", "tags": "fire"}})
    token = _start(db, client)
    _signal(db, token.id, headline="volume subindo")
    assert notify.run_once(db, client) == 1
    assert _title(sent[0]) == "Ação já: TEST (Compra forte)"
    assert sent[0]["body"].startswith("volume subindo | score 70 | risco 10 | US$")
    assert sent[0]["priority"] == "urgent" and sent[0]["tags"] == "fire"


def test_filters_and_switching_types(db, fake_dex, phone):
    sent, client = phone
    _save(min_opportunity_score=80, rules={"sell": {"enabled": True}})
    token = _start(db, client)
    _signal(db, token.id, score=70)
    assert notify.run_once(db, client) == 0  # score abaixo do mínimo
    _signal(db, token.id, action="sell", strength="moderate", score=10)
    assert notify.run_once(db, client) == 0  # venda também passa pelo score mínimo
    _save(min_opportunity_score=0, max_risk_score=5, rules={"sell": {"enabled": True}})
    _signal(db, token.id, action="sell", strength="moderate")
    assert notify.run_once(db, client) == 0  # risco acima do máximo
    _save(min_liquidity_usd=10_000_000, rules={"sell": {"enabled": True}})
    _signal(db, token.id, action="sell", strength="moderate")
    assert notify.run_once(db, client) == 0  # liquidez abaixo do mínimo
    _save(rules={"sell": {"enabled": True, "title": "VENDA {symbol}"}})
    _signal(db, token.id, action="sell", strength="moderate")
    assert notify.run_once(db, client) == 1 and _title(sent[-1]) == "VENDA TEST"


def test_muted_favorites_cooldown_and_hour_limit(db, fake_dex, phone):
    sent, client = phone
    _save(muted=["test"])  # símbolo, sem diferenciar maiúscula
    token = _start(db, client)
    _signal(db, token.id)
    assert notify.run_once(db, client) == 0
    _save(favorites_only=True)
    _signal(db, token.id)
    assert notify.run_once(db, client) == 0  # não é favorita
    user = db.query(User).first() or User(username="u", password_hash="x")
    db.add(user)
    db.flush()
    db.add(Favorite(user_id=user.id, token_id=token.id, signal_at=token.first_seen_at, reasons=[], specs={}, rules_version="t"))
    db.commit()
    _save(favorites_only=True, min_opportunity_score=99, token_cooldown_minutes=0, max_per_hour=2)
    for _ in range(3):
        _signal(db, token.id)
        notify.run_once(db, client)
    assert len(sent) == 2  # favorita ignora o score mínimo; sem espera por moeda; teto de 2 por hora


def test_quiet_hours(db, fake_dex, phone, monkeypatch):
    sent, client = phone
    monkeypatch.setattr(notify.time, "strftime", lambda fmt, *a: "02:30" if fmt == "%H:%M" else "2026-11-04")
    _save(quiet={"enabled": True, "start": "23:00", "end": "07:00", "allow_urgent": True})
    token = _start(db, client)
    _signal(db, token.id)
    assert notify.run_once(db, client) == 0  # prioridade alta: fica em silêncio
    _save(quiet={"enabled": True, "start": "23:00", "end": "07:00", "allow_urgent": True},
          rules={"buy_strong": {"priority": "urgent"}})
    _signal(db, token.id)
    assert notify.run_once(db, client) == 1  # urgente passa


def test_quiet_window_math():
    q = notify_prefs.Quiet(enabled=True, start="23:00", end="07:00")
    assert notify_prefs.in_quiet(q, "23:30") and notify_prefs.in_quiet(q, "06:59")
    assert not notify_prefs.in_quiet(q, "07:00") and not notify_prefs.in_quiet(q, "12:00")
    day = notify_prefs.Quiet(enabled=True, start="09:00", end="18:00")
    assert notify_prefs.in_quiet(day, "12:00") and not notify_prefs.in_quiet(day, "20:00")


def test_render_never_reads_attributes():
    assert notify_prefs.render("{symbol.__class__} {x} {symbol}", {"symbol": "A"}) == "{symbol.__class__} {x} A"


def test_bad_file_falls_back_to_defaults(tmp_path):
    notify_prefs.prefs_path().write_text("{ quebrado", encoding="utf-8")
    assert notify_prefs.load() == notify_prefs.NotifyPrefs()


def test_api_read_save_validate_reset_and_test(client, phone, monkeypatch):
    sent, mock = phone
    assert client.get(f"{API}/system/phone/prefs").status_code == 401
    client.post(f"{API}/auth/login", json={"username": "alisson", "password": "test-initial-pw"})
    p = client.get(f"{API}/system/phone/prefs").json()
    assert set(p["rules"]) == set(notify_prefs.KINDS)
    p["max_per_hour"] = 5
    p["topic"] = "meu-canal-123"
    assert client.put(f"{API}/system/phone/prefs", json=p).json()["max_per_hour"] == 5
    assert notify.phone_url().endswith("/meu-canal-123")
    bad = {**p, "quiet": {**p["quiet"], "start": "25:00"}}
    assert client.put(f"{API}/system/phone/prefs", json=bad).status_code == 422
    assert client.put(f"{API}/system/phone/prefs", json={**p, "server": "javascript:x"}).status_code == 422
    assert client.put(f"{API}/system/phone/prefs", json={**p, "rules": {"xpto": {}}}).status_code == 422
    assert client.delete(f"{API}/system/phone/prefs").json()["max_per_hour"] == 30
    monkeypatch.setattr(httpx, "post", mock.post)
    r = client.post(f"{API}/system/phone/test?kind=burst").json()
    assert r["sent"] is True and _title(sent[-1]) == "DISPARO TESTE" and sent[-1]["priority"] == "urgent"
    assert client.post(f"{API}/system/phone/test?kind=nada").status_code == 422
