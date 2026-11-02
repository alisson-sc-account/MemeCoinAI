"""Atualização rápida (`live-1`): lista de acompanhamento, ciclo, golpe ao vivo e o plano de venda.

As respostas da Jupiter aqui são SIMULADAS (formato copiado de uma resposta real de 2026-10-29).
"""
from datetime import timedelta

import httpx
import pytest

from app.db import utcnow
from app.ingest.service import track_token
from app.live import service as live
from app.live.jupiter import JupiterPriceClient, _limiter, parse_quote
from app.models import LiveQuote, LiveWatch, PairSnapshot, Position, ServiceHeartbeat, User
from app.sources.http import ResilientClient
from tests.conftest import SOL_MINT

API = "/api/v1"


class FakeJupiter:
    def __init__(self):
        self.prices = {SOL_MINT: {"usdPrice": 0.0000040, "liquidity": 300_000.0, "blockId": 463121135,
                                  "decimals": 6, "priceChange24h": 2.1}}
        self.calls: list[list[str]] = []
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(503, json={})
        ids = request.url.params["ids"].split(",")
        self.calls.append(ids)
        return httpx.Response(200, json={k: v for k, v in self.prices.items() if k in ids})

    def client(self):
        return JupiterPriceClient(ResilientClient("https://lite-api.jup.ag", transport=httpx.MockTransport(self.handler),
                                                  sleep=lambda s: None, max_attempts=1))


@pytest.fixture
def jup(monkeypatch):
    monkeypatch.setattr(_limiter, "min_interval", 0)
    fake = FakeJupiter()
    monkeypatch.setattr(live, "JupiterPriceClient", fake.client)
    return fake


def _quote(db, token, ago, price, liq):
    db.add(LiveQuote(token_id=token.id, source="jupiter_price", received_at=utcnow() - timedelta(seconds=ago),
                     price_usd=price, liquidity_usd=liq))
    db.commit()


def test_parse_quote_rejects_bad_values():
    assert parse_quote({"usdPrice": 1.5, "liquidity": 10, "blockId": 7}) == {"price_usd": 1.5, "liquidity_usd": 10.0, "block_id": 7}
    assert parse_quote({"usdPrice": 0}) is None and parse_quote({"usdPrice": "1"}) is None and parse_quote(None) is None
    assert parse_quote({"usdPrice": 2.0, "liquidity": None})["liquidity_usd"] is None


def test_watch_list_expires_and_positions_stay(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    live.request_watch(db, token.id, now - timedelta(seconds=120))
    assert live.watched_tokens(db, now) == []  # quadro fechado há 2 min: saiu da lista
    live.request_watch(db, token.id, now)
    assert [t.id for t in live.watched_tokens(db, now)] == [token.id]
    db.execute(LiveWatch.__table__.delete())
    user = db.query(User).first() or User(username="u", password_hash="x")
    db.add(user)
    db.commit()
    db.add(Position(user_id=user.id, token_id=token.id, quantity=10, entry_price_usd=1.0))
    db.commit()
    assert [t.id for t in live.watched_tokens(db, now)] == [token.id]  # posição: sempre acompanhado


def test_request_watch_throttles_writes(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    live.request_watch(db, token.id, now)
    live.request_watch(db, token.id, now + timedelta(seconds=1))
    assert db.get(LiveWatch, token.id).last_requested_at == now  # menos de 2 s: não regrava
    live.request_watch(db, token.id, now + timedelta(seconds=20))
    assert db.get(LiveWatch, token.id).last_requested_at == now + timedelta(seconds=20)


def test_tick_stores_quotes_and_beats(db, fake_dex, jup):
    token, _ = track_token(db, "solana", SOL_MINT)
    live.request_watch(db, token.id)
    r = live.tick(db)
    assert r == {"watched": 1, "quoted": 1, "requests": 1, "errors": []} and jup.calls == [[SOL_MINT]]
    q = db.query(LiveQuote).one()
    assert q.price_usd == 0.0000040 and q.liquidity_usd == 300_000.0 and q.block_id == 463121135
    assert live.service_status(db)["status"] == "running"
    jup.fail = True
    r = live.tick(db)
    assert r["errors"] and db.query(LiveQuote).count() == 1  # falha da fonte não grava nada inventado
    assert db.get(ServiceHeartbeat, "live").last_error


def test_tick_without_record_does_not_beat(db, fake_dex, jup):
    token, _ = track_token(db, "solana", SOL_MINT)
    live.tick(db, tokens=[token], record=False)
    assert db.get(ServiceHeartbeat, "live") is None and db.query(LiveQuote).count() == 1


def test_service_status_running_stopped_unknown(db):
    assert live.service_status(db)["status"] == "unknown"
    live.beat(db, interval=10, now=utcnow() - timedelta(seconds=5))
    assert live.service_status(db)["status"] == "running"
    live.beat(db, interval=10, now=utcnow() - timedelta(minutes=2))
    assert live.service_status(db)["status"] == "stopped"


def test_live_alerts_liquidity_pulled(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    for ago in (120, 100, 80):
        _quote(db, token, ago, 1.0, 600_000)
    _quote(db, token, 20, 0.5, 70_000)
    assert live.live_alerts(db, token.id) == []  # uma leitura só não basta
    _quote(db, token, 10, 0.02, 69_000)
    alerts = live.live_alerts(db, token.id)
    assert any("Liquidez retirada" in a and "golpe" in a for a in alerts)
    assert any("Preço despencou" in a for a in alerts)


def test_live_alerts_quiet_on_normal_moves(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    for i, ago in enumerate((60, 50, 40, 30, 20, 10)):
        _quote(db, token, ago, 1.0 + i * 0.01, 300_000 - i * 5_000)
    assert live.live_alerts(db, token.id) == []


def test_feed_states(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    assert live.feed(db, token)["status"] == "off"  # serviço nunca rodou
    live.beat(db, interval=10)
    assert live.feed(db, token)["status"] == "waiting"
    live.request_watch(db, token.id, utcnow() - timedelta(seconds=40))
    assert live.feed(db, token)["status"] == "unavailable"  # já passou 2 ciclos sem preço
    _quote(db, token, 3, 0.5, 1000)
    f = live.feed(db, token)
    assert f["status"] == "live" and f["price_usd"] == 0.5 and f["age_seconds"] < 10


def test_prune_removes_old_quotes(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    _quote(db, token, 60 * 60 * 30, 1.0, 1)
    _quote(db, token, 5, 1.0, 1)
    assert live.prune(db) == 1 and db.query(LiveQuote).count() == 1


# ---------------- API ----------------
def test_exit_plan_uses_live_price_and_registers_watch(auth_client, fake_dex, db):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()
    assert j["live"]["status"] == "off" and j["freshness"]["source"] == "dexscreener"  # sem serviço: coletor
    token = db.query(LiveWatch).one()  # o pedido do quadro entrou na lista
    live.beat(db, interval=10)
    db.add(LiveQuote(token_id=token.token_id, source="jupiter_price", received_at=utcnow(), price_usd=0.0000050,
                     liquidity_usd=1.0))
    db.commit()
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()
    assert j["live"]["status"] == "live" and j["current_price_usd"] == 0.0000050
    assert j["freshness"]["source"] == "jupiter_price" and j["freshness"]["age_seconds"] < 10


def test_exit_plan_sells_everything_on_live_rug(auth_client, fake_dex, db):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan")
    token_id = db.query(LiveWatch).one().token_id
    live.beat(db, interval=10)
    for ago, price, liq in ((90, 1.0, 600_000), (70, 1.0, 600_000), (50, 1.0, 600_000), (15, 0.02, 60_000), (5, 0.02, 59_000)):
        db.add(LiveQuote(token_id=token_id, source="jupiter_price", received_at=utcnow() - timedelta(seconds=ago),
                         price_usd=price, liquidity_usd=liq))
    db.commit()
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()
    assert j["urgency"] == "sell_now" and j["sell_percent_now"] == 100
    assert "Liquidez retirada" in j["reasons"][0]


def test_health_reports_live_service(client, db):
    h = client.get(f"{API}/health").json()
    assert h["live"]["status"] == "unknown" and h["status"] == "degraded"
    live.beat(db, interval=10, watched=2, quoted=2)
    h = client.get(f"{API}/health").json()["live"]
    assert h["status"] == "running" and h["watched"] == 2 and h["interval_seconds"] == 10


# ---------------- Moeda aberta: reservas na blockchain a cada ~1 s ----------------
def _b58(raw):
    from app.live.chain import b58encode
    return b58encode(raw)


def test_parse_curve_and_vaults():
    import struct

    from app.live import chain
    curve = b"\0" * 8 + struct.pack("<5Q", 1_000_000, 50_000_000, 0, 7, 0) + b"\0"
    assert chain.parse_curve(curve) == {"ratio": 50.0, "quote_raw": 7, "quote_mint": chain.WSOL}
    assert chain.parse_curve(curve[:48] + b"\1") is None  # migrou
    assert chain.parse_curve(b"\0" * 8 + struct.pack("<5Q", 1000, 5, 0, 0, 0) + b"\0") is None  # vazia
    mint = bytes(range(32))
    token = _b58(mint)
    other = bytes(range(1, 33))
    a = mint + b"\0" * 32 + struct.pack("<Q", 1000)
    b = other + b"\0" * 32 + struct.pack("<Q", 5_000_000)
    r = chain.parse_vaults(a, b, token)
    assert r["ratio"] == 5000.0 and r["quote_mint"] == _b58(other)
    assert chain.parse_vaults(a, other + b"\0" * 32 + struct.pack("<Q", 1), token) is None  # cofre vazio (pool drenada)
    assert chain.parse_vaults(b, b, token) is None  # nenhum cofre é do token


class FakeReader:
    def __init__(self, ratio):
        self.ratio, self.resolves, self.error = ratio, 0, None

    def resolve(self, pair, token):
        from app.live.chain import PoolRef
        self.resolves += 1
        return PoolRef("curve", [pair])

    def read(self, pools):
        if self.error:
            return {}, self.error
        return {tid: {"ratio": self.ratio, "quote_raw": 2_000_000_000, "quote_mint": "x"} for tid in pools}, None


def test_focus_lane_calibrates_then_follows_reserves(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    anchor = db.query(PairSnapshot).first().price_usd
    reader = FakeReader(10.0)
    lane = live.FocusLane(reader)
    assert lane.tick(db, [token])["quoted"] == 1
    assert abs(db.query(LiveQuote).one().price_usd - anchor) < 1e-12  # primeira leitura = referência
    reader.ratio = 12.0
    lane.tick(db, [token])
    last = db.query(LiveQuote).order_by(LiveQuote.id.desc()).first()
    assert last.source == "solana_pool" and abs(last.price_usd / anchor - 1.2) < 0.03  # reservas subiram 20%
    assert reader.resolves == 1  # pool resolvida uma vez só
    reader.error = "429"
    assert lane.tick(db, [token])["error"] == "429" and db.query(LiveQuote).count() == 2


def test_focused_expires_in_seconds(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    live.request_watch(db, token.id, now)
    assert live.focused_tokens(db, now) and not live.focused_tokens(db, now + timedelta(seconds=10))


def test_feed_prefers_one_second_source(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    live.beat(db, interval=10)
    _quote(db, token, 8, 0.5, 1000)
    assert live.feed(db, token)["interval_seconds"] == 10
    db.add(LiveQuote(token_id=token.id, source="solana_pool", received_at=utcnow(), price_usd=0.6))
    db.commit()
    f = live.feed(db, token)
    assert f["interval_seconds"] == 1 and f["price_usd"] == 0.6 and f["source"] == "solana_pool"


def test_peak_call_needs_gain_then_fall(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    for ago, p in ((60, 1.0), (50, 1.15), (40, 1.2)):
        _quote(db, token, ago, p, 1000)
    assert live.peak_call(db, token.id, reference=1.0) is None
    _quote(db, token, 20, 1.08, 1000)
    assert live.peak_call(db, token.id, reference=1.0) is None  # uma leitura só não basta
    _quote(db, token, 10, 1.08, 1000)
    call = live.peak_call(db, token.id, reference=1.0)
    assert call[0] == 100 and "topo" in call[1]
    assert live.peak_call(db, token.id, reference=1.15) is None  # sem ter subido 10% ainda não armou


def test_peak_call_warns_near_top_when_sellers_take_over(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    for ago, p in ((40, 1.25), (30, 1.3), (20, 1.3), (10, 1.29)):
        _quote(db, token, ago, p, 1000)
    sellers = {"buy_usd": 100.0, "sell_usd": 200.0, "buys": 3, "sells": 5}
    assert live.peak_call(db, token.id, 1.0, sellers)[0] == 50
    assert live.peak_call(db, token.id, 1.0, {**sellers, "sell_usd": 120.0}) is None  # compradores ainda seguram
    assert live.peak_call(db, token.id, 1.0, {**sellers, "buys": 1, "sells": 2}) is None  # poucas negociações
    assert live.peak_call(db, token.id, 1.0) is None  # sem fluxo não avisa


def test_exit_plan_uses_peak_call():
    from types import SimpleNamespace

    from app.engine import exit_plan
    hold = SimpleNamespace(action="hold", strength="none", reference_price_usd=1.0, reasons=[])
    p = exit_plan.build(1.0, 1000, None, hold, None, [], None, [], (50, "Começou a cair: 9% desde o topo"))
    assert p["urgency"] == "reduce" and p["sell_percent_now"] == 50 and "topo" in p["reasons"][0]
    p = exit_plan.build(1.0, 1000, None, hold, None, [], None, [], (100, "Caiu 20% desde o topo"))
    assert p["urgency"] == "sell_now" and p["sell_percent_now"] == 100


def test_token_detail_has_buy_simulation(auth_client, fake_dex, db):
    from app.models import Signal
    token, _ = track_token(db, "solana", SOL_MINT)
    assert auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()["buy_simulation"] is None
    db.add(Signal(token_id=token.id, action="buy", strength="strong", status="superseded", headline="c", reasons=[], risk_score=1,
                  risk_level="low", opportunity_score=70, reference_price_usd=0.5, estimates=[], rules_version="sig-1"))
    db.commit()
    sim = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()["buy_simulation"]
    assert sim["entry_price_usd"] == 0.5 and sim["strength"] == "strong"  # continua mesmo depois que o sinal mudou
