"""Orquestrador: disparo congelado, fila com prioridade, radar, descoberta dividida e painel igual ao cálculo direto."""
from datetime import timedelta

import pytest

from app import agents, board, config
from app.db import utcnow
from app.engine import burst
from app.ingest import service as svc
from app.ingest.service import track_token
from app.models import Signal, Token
from app.sources.http import FetchResult
from app.worker import AnalysisQueue, Radar, RANKINGS
from tests.conftest import SOL_MINT

API = "/api/v1"


# ---------------- Regra número 1: o disparo não muda ----------------
BURST = {"available": True, "liquidity_usd": 20_000, "volume_accel_m5": 5.0, "price_change_m5": 3.0, "txns_m5": 20, "buys_m5": 15, "sells_m5": 5, "price_change_h1": 40}


def test_burst_rules_are_frozen():
    assert burst.RULES_VERSION == "burst-1"
    assert (burst.MIN_LIQUIDITY_USD, burst.MIN_VOLUME_ACCEL_M5, burst.MIN_PRICE_CHANGE_M5, burst.MIN_TXNS_M5, burst.MIN_BUY_SHARE_M5, burst.MAX_PRICE_CHANGE_H1) == (5000, 4.0, 2.0, 8, 0.65, 300.0)
    assert (burst.EXTREME_ACCEL, burst.EXTREME_PRICE_CHANGE_M5) == (10.0, 8.0)
    assert burst.detect(BURST)["strength"] == "strong"
    assert burst.detect({**BURST, "volume_accel_m5": 11, "price_change_m5": 9})["strength"] == "extreme"


@pytest.mark.parametrize("change", [{"liquidity_usd": 4999}, {"volume_accel_m5": 3.9}, {"price_change_m5": 1.9}, {"txns_m5": 7}, {"buys_m5": 12, "sells_m5": 8}, {"price_change_h1": 301}, {"available": False}])
def test_burst_stays_quiet_below_each_limit(change):
    assert burst.detect({**BURST, **change}) is None


# ---------------- Fila e radar ----------------
def test_queue_hot_jumps_ahead_and_never_repeats():
    q = AnalysisQueue()
    q.add([1, 2, 3], hot=False)
    q.add([9, 2], hot=True)
    q.add([1], hot=False)
    assert q.take(2) == [9, 2] and q.sizes() == (0, 2)
    assert q.take(10) == [1, 3] and q.take(10) == []


def test_radar_expires():
    now = [0.0]
    r = Radar(ttl=10, clock=lambda: now[0])
    r.add({1})
    assert r.active() == {1}
    now[0] = 11
    assert r.active() == set()


def test_scout_lists_are_the_five_minute_windows():
    assert [RANKINGS[i % 3 * 4 % len(RANKINGS)] for i in range(3)] == ["toptraded/5m", "toporganicscore/5m", "toptrending/5m"]


# ---------------- Prioridade ----------------
def _many(db, n, **kw):
    old = utcnow() - timedelta(hours=1)
    tokens = [Token(chain_id="solana", address=f"M{i:04d}" + "1" * 39, discovered_via="t", first_seen_at=old, heat=float(i), last_refreshed_at=old + timedelta(seconds=i), **kw) for i in range(n)]
    db.add_all(tokens)
    db.commit()
    return tokens


def test_split_promotes_radar_and_signals(db, monkeypatch):
    monkeypatch.setenv("REFRESH_HOT_TOKENS", "5")
    config.get_settings.cache_clear()
    tokens = _many(db, 20)
    db.add(Signal(token_id=tokens[0].id, action="buy", strength="strong", status="active", headline="c", reasons=[], risk_score=1, risk_level="low", opportunity_score=70, estimates=[], rules_version="sig-1"))
    db.commit()
    hot, cold = svc.split_hot_cold(db, {tokens[1].id})
    ids = {t.id for t in hot}
    assert tokens[0].id in ids and tokens[1].id in ids and len(hot) == 5 and tokens[19].id in ids  # sinal, radar e mais volume
    assert {t.id for t in cold}.isdisjoint(ids) and len(cold) == 15
    ages = [t.last_refreshed_at for t in cold]
    assert ages == sorted(ages)  # rodízio: o mais antigo primeiro


def test_new_tokens_cannot_push_hot_out(db, monkeypatch):
    monkeypatch.setenv("REFRESH_HOT_TOKENS", "400")
    config.get_settings.cache_clear()
    tokens = _many(db, 50)
    db.add_all([Token(chain_id="solana", address=f"N{i:04d}" + "1" * 39, discovered_via="t", first_seen_at=utcnow()) for i in range(500)])
    db.commit()
    hot, cold = svc.split_hot_cold(db)
    assert {t.id for t in tokens} <= {t.id for t in hot}  # 300 novatos no máximo: as quentes continuam
    assert len(hot) == 400 and len(cold) == 150


def test_scout_promotes_known_and_adds_new(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)

    class Lists:
        def listing(self, name):
            return FetchResult(ok=True, data=[{"id": SOL_MINT, "liquidity": 9000}, {"id": "New" + "1" * 40, "liquidity": 9000}, {"id": "Thin" + "1" * 39, "liquidity": 5}])
    ids, added = svc.scout(db, "toptraded/5m", Lists())
    assert token.id in ids and len(ids) == 2 and added == 1
    assert db.query(Token).filter(Token.discovered_via == "jupiter_scout").count() == 1


def test_discovery_parts_run_only_what_was_asked(db, fake_dex):
    fake_dex.calls = 0
    assert svc.discover(db, parts=("gecko",)) == [] and fake_dex.calls == 0
    svc.discover(db, parts=("lists",))
    assert fake_dex.calls == 3


# ---------------- Contagem ----------------
def test_confirmed_unchanged_counts_as_fresh(auth_client, fake_dex, db):
    from app.models import PairSnapshot
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    snap = db.query(PairSnapshot).one()
    snap.received_at = utcnow() - timedelta(hours=2)
    db.commit()
    assert auth_client.get(f"{API}/tokens").json()["items"][0]["freshness"]["status"] == "fresh"
    t = db.query(Token).one()
    t.last_refreshed_at = utcnow() - timedelta(hours=2)
    db.commit()
    assert auth_client.get(f"{API}/tokens").json()["items"][0]["freshness"]["status"] == "stale"


# ---------------- Painel ----------------
@pytest.fixture
def board_on(monkeypatch, tmp_path):
    path = tmp_path / "board.db"
    monkeypatch.setattr(board, "board_path", lambda: path)
    monkeypatch.setenv("BOARD_ENABLED", "true")
    config.get_settings.cache_clear()
    return path


def _strip(value):
    """Tira só o que muda com o relógio entre as duas leituras."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in ("generated_at", "age_seconds", "pair_age_hours")}
    return [_strip(v) for v in value] if isinstance(value, list) else value


def test_board_gives_exactly_the_same_lists(auth_client, fake_dex, db, board_on, monkeypatch):
    from app.engine.pipeline import analyze_token
    token, _ = track_token(db, "solana", SOL_MINT)
    analyze_token(db, token, force=True)
    db.add(Token(chain_id="solana", address="Empty" + "1" * 38, discovered_via="t", first_seen_at=utcnow()))
    db.commit()
    urls = ["/opportunities", "/opportunities?sort=risk_score", "/opportunities?sort=liquidity_usd&tier=watch", "/opportunities?min_liquidity=1000",
            "/tokens", "/tokens?sort=liquidity_usd&order=asc", "/tokens?min_liquidity=1&freshness_status=fresh"]
    monkeypatch.setenv("BOARD_ENABLED", "false")
    config.get_settings.cache_clear()
    direct = {u: auth_client.get(API + u).json() for u in urls}
    monkeypatch.setenv("BOARD_ENABLED", "true")
    config.get_settings.cache_clear()
    assert board.build_once() == 2 and board_on.exists()
    for u in urls:
        got = auth_client.get(API + u).json()
        assert _strip(got) == _strip(direct[u]), u
    assert auth_client.get(f"{API}/dashboard/summary").json()["tokens_tracked"] == 2


def test_board_old_or_missing_falls_back(auth_client, fake_dex, db, board_on):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    assert board.read_connection() is None and auth_client.get(f"{API}/opportunities").json()["total"] == 1
    board.build_once()
    con = board.read_connection()
    assert con is not None
    con.close()
    assert board.read_connection(max_age=-1) is None


# ---------------- Agentes ----------------
def test_agents_listed_by_category(auth_client, db):
    agents.beat(db, "market_hot", 30, items=7, duration_ms=12.0)
    agents.beat(db, "scout", 20, error="429")
    r = auth_client.get(f"{API}/system/agents").json()
    by = {a["name"]: a for a in r}
    assert len({a["category"] for a in r}) >= 8 and by["market_hot"]["status"] == "running" and by["market_hot"]["items"] == 7
    assert by["scout"]["last_error"] == "429" and by["board"]["status"] == "unknown"


def test_impossible_price_change_blocks_buy():
    from types import SimpleNamespace

    from app.engine.ranking import classify
    a = SimpleNamespace(risk_factors=[], opportunity_factors=[], checks_not_performed=[])
    f = {"available": True, "price_usd": 1.0, "liquidity_usd": 9000.0, "price_change_h1": 161_000_000_000.0}
    r = classify(a, f, "buy", "strong", "fresh")
    assert r["tier"] == "avoid" and "suspeito" in r["critical_blocks"][0]
    assert classify(a, {**f, "price_change_h1": 900.0}, "buy", "strong", "fresh")["tier"] == "priority_buy"


def test_estimate_memo_changes_nothing(db, monkeypatch):
    from app.engine import outcomes
    from app.models import Analysis, AnalysisOutcome
    token = _many(db, 1)[0]
    now = utcnow()
    for i in range(40):
        at = now - timedelta(hours=2, minutes=i)
        a = Analysis(token_id=token.id, computed_at=at, engine_version="t", risk_score=10, risk_level="low", risk_confidence=1, opportunity_score=50,
                     opportunity_confidence=1, risk_factors=[], opportunity_factors=[], checks_not_performed=[], data_quality={}, features={}, invalidation_conditions=[])
        db.add(a)
        db.flush()
        for secs in outcomes.HORIZONS.values():
            db.add(AnalysisOutcome(analysis_id=a.id, token_id=token.id, horizon_seconds=secs, analysis_time=at, opportunity_score=50, risk_score=10, status="ok",
                                   max_return=0.1 * i, min_return=-0.01 * i, end_return=0.01 * i, observations=3, labeled_at=now))
    db.commit()
    first = outcomes.estimate(db, 50, 10, now)
    calls = []
    monkeypatch.setattr(outcomes, "summarize", lambda r: calls.append(1) or {})
    assert outcomes.estimate(db, 55, 12, now) == first and not calls  # mesma faixa: mesmo resultado, sem recalcular
    outcomes.estimate(db, 90, 10, now)
    assert calls  # outra faixa calcula
    monkeypatch.undo()
    outcomes._cache.clear()
    assert outcomes.estimate(db, 50, 10, now) == first  # igual ao cálculo do zero
    first[0]["n"] = -1
    assert outcomes.estimate(db, 50, 10, now)[0]["n"] != -1  # quem recebe não altera a memória


def test_samples_keep_only_current_minute(db):
    from app.engine import outcomes
    now = utcnow()
    for i in range(5):
        outcomes.estimate(db, 50, 10, now + timedelta(minutes=i))
    assert {(k[1] if k[0] == "estimate" else k[-1]) for k in outcomes._cache} == {(now + timedelta(minutes=4)).replace(second=0, microsecond=0)}
