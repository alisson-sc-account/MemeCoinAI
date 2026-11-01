"""Segurança (`sec-1`): pool fora da conta, regras, sem dado não vira aprovação, golpe permanente, trava de compra.

As respostas da RugCheck aqui são SIMULADAS (formato copiado de uma resposta real de 2026-10-30).
"""
from datetime import timedelta
from types import SimpleNamespace

from app import config
from app.db import utcnow
from app.engine.pipeline import analyze_token
from app.ingest.service import track_token
from app.models import PairSnapshot, SecurityReport, Signal, WalletProfile
from app.safety import service as sec
from app.safety.sources import parse_report
from app.sources.http import FetchResult
from tests.conftest import SOL_MINT

API = "/api/v1"
POOL_OWNER = "PoolOwner111"


def _raw(**over):
    base = {
        "rugged": False, "mintAuthority": None, "freezeAuthority": None, "totalHolders": 500, "graphInsidersDetected": 0, "insiderNetworks": None,
        "score_normalised": 10, "risks": [], "knownAccounts": {"LockerX": {"name": "x", "type": "LOCKER"}}, "token": {"supply": 1000},
        "markets": [{"pubkey": "PoolPub", "marketType": "pump_fun_amm", "liquidityAAccount": {"owner": POOL_OWNER}, "lp": {"lpLockedPct": 100, "quoteUSD": 50}}],
        "topHolders": [{"owner": POOL_OWNER, "address": "a", "pct": 74.5, "insider": False}, {"owner": "LockerX", "address": "b", "pct": 5, "insider": False},
                       {"owner": "W1", "address": "c", "pct": 4.0, "insider": False}, {"owner": "W2", "address": "d", "pct": 3.0, "insider": True}],
    }
    return {**base, **over}


def _token(**over):
    return SimpleNamespace(**{"symbol": "AAA", "name": "Aaa", "rugged_at": None, "rug_reason": None, **over})


CALM = {"available": True, "micro": False, "constant": False}
MARKET = {"liq_to_mcap": 0.2, "age_hours": 500, "market_cap": 100_000}
WALLETS = {"analyzed": 5, "fresh_count": 0, "fresh_pct": 0.0, "cluster_size": 0, "cluster_pct": 0.0}


def _keys(checks, status):
    return {c["key"] for c in checks if c["status"] == status}


def test_parse_excludes_pool_and_lockers():
    rc = parse_report(_raw())
    assert [h["owner"] for h in rc["holders"]] == ["W1", "W2"] and rc["holders"][1]["insider"]
    assert rc["lp"] == {"type": "pump_fun_amm", "locked_pct": 100.0, "reliable": True}
    assert parse_report(_raw(insiderNetworks=[{"size": 79, "type": "transfer", "currentHolding": 250}]))["networks"][0]["pct"] == 25.0


def test_clean_coin_is_clear_never_safe():
    v, c = sec.assess(_token(), parse_report(_raw()), WALLETS, CALM, MARKET)
    assert v == "clear" and sec.LABELS[v] == "Sem alertas" and "Seguro" not in sec.LABELS.values()
    assert not _keys(c, "danger") and not _keys(c, "warn")


def test_missing_source_is_not_approval():
    v, c = sec.assess(_token(), None, None, {"available": False}, {})
    assert v == "unknown" and not _keys(c, "ok") and "rugcheck" in _keys(c, "unknown")


def test_each_danger_rule():
    cases = {
        "authority": _raw(mintAuthority="abc"),
        "lp": _raw(markets=[{"pubkey": "P", "marketType": "raydium", "lp": {"lpLockedPct": 0, "quoteUSD": 5}}]),
        "top1": _raw(topHolders=[{"owner": "W", "address": "x", "pct": 25}]),
        "top10": _raw(topHolders=[{"owner": f"W{i}", "address": f"x{i}", "pct": 8} for i in range(8)]),
        "insiders": _raw(insiderNetworks=[{"size": 9, "currentHolding": 300}]),
    }
    for key, raw in cases.items():
        v, c = sec.assess(_token(), parse_report(raw), WALLETS, CALM, MARKET)
        assert v == "danger" and key in _keys(c, "danger"), key
    fresh = {**WALLETS, "fresh_pct": 35.0, "fresh_count": 4}
    assert "fresh" in _keys(sec.assess(_token(), parse_report(_raw()), fresh, CALM, MARKET)[1], "danger")
    cluster = {**WALLETS, "cluster_size": 4, "cluster_pct": 40.0}
    assert "cluster" in _keys(sec.assess(_token(), parse_report(_raw()), cluster, CALM, MARKET)[1], "danger")


def test_meteora_unlocked_lp_is_only_caution():
    raw = _raw(markets=[{"pubkey": "P", "marketType": "meteora_damm_v2", "liquidityAAccount": {"owner": POOL_OWNER}, "lp": {"lpLockedPct": 0, "quoteUSD": 5}}])
    v, c = sec.assess(_token(), parse_report(raw), WALLETS, CALM, MARKET)
    assert v == "caution" and "lp" in _keys(c, "warn")


def test_usdf_pattern_is_caught_before_the_rug():
    """Valores reais da USDF antes do golpe: liquidez 1,2% do valor, US$ 50 mi com 2 dias, robôs, nome de fundo."""
    usdf = _token(symbol="USDF", name="United States Dividend Fund")
    market = {"liq_to_mcap": 0.012, "age_hours": 48, "market_cap": 50_000_000}
    pts = [SimpleNamespace(buys_h1=2930 + i % 3, sells_h1=1080, volume_h1=24_000.0, received_at=utcnow() + timedelta(minutes=30 * i)) for i in range(10)]
    activity = sec.activity_facts(pts)
    assert activity["micro"] and activity["constant"]
    v, c = sec.assess(usdf, parse_report(_raw()), WALLETS, activity, market)
    assert v == "danger" and {"depth", "activity"} <= _keys(c, "danger") and "name" in _keys(c, "warn")


def test_activity_does_not_flag_real_trading():
    pts = [SimpleNamespace(buys_h1=100 + 90 * (i % 4), sells_h1=80, volume_h1=90_000.0, received_at=utcnow() + timedelta(minutes=30 * i)) for i in range(10)]
    a = sec.activity_facts(pts)
    assert not a["micro"] and not a["constant"]


def test_buy_gate():
    buy = {"action": "buy", "strength": "strong", "reasons": [], "headline": "c"}
    assert sec.apply_to_decision(buy, "clear")["strength"] == "strong"
    assert sec.apply_to_decision(buy, "caution")["strength"] == "moderate"
    assert sec.apply_to_decision(buy, None)["strength"] == "moderate" and "não verificada" in sec.apply_to_decision(buy, None)["reasons"][-1]
    assert sec.apply_to_decision(buy, "danger")["action"] == "avoid"
    sell = {"action": "sell", "strength": "strong", "reasons": []}
    assert sec.apply_to_decision(sell, "danger") == sell


def test_detect_rug_needs_both_price_and_liquidity():
    f = {"history_points_1h": 5, "price_change_h1": -98.7, "liquidity_change_vs_max_1h": -0.89}
    assert "98%" in sec.detect_rug(f) or "99%" in sec.detect_rug(f)
    assert sec.detect_rug({**f, "liquidity_change_vs_max_1h": -0.1}) is None  # só preço: pode ser queda normal
    assert sec.detect_rug({**f, "price_change_h1": -20}) is None


def test_rug_mark_never_forgets(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    token.rugged_at, token.rug_reason = utcnow(), "teste"
    db.commit()
    a = analyze_token(db, token, force=True)
    assert a.risk_score == 100 and a.risk_level == "critical" and any(f["id"] == "R1_rugged" for f in a.risk_factors)
    sig = db.query(Signal).filter(Signal.token_id == token.id, Signal.status == "active").one()
    assert sig.action == "sell"


class FakeRC:
    def __init__(self, raw=None, fail=False):
        self.raw, self.fail = raw or _raw(), fail

    def report(self, mint):
        return FetchResult(ok=False, error="429") if self.fail else FetchResult(ok=True, data=self.raw)


class FakeRpc:
    def __init__(self, now):
        self.now, self.calls = now, 0

    def profile(self, address):
        self.calls += 1
        return {"first_seen_ts": (self.now - timedelta(hours=5)).timestamp(), "signatures": 10, "complete": True, "funder": "SameFunder"}


def test_scan_fresh_wallets_cluster_and_wallet_cache(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    rpc = FakeRpc(now)
    r = sec.scan(db, token, True, FakeRC(), rpc, now)
    w = r.facts["wallets"]
    assert w["analyzed"] == 2 and w["fresh_count"] == 2 and w["fresh_pct"] == 7.0 and w["cluster_size"] == 2
    assert all(h["fresh"] and h["cluster"] == 1 for h in r.holders) and db.query(WalletProfile).count() == 2
    sec.scan(db, token, True, FakeRC(), rpc, now + timedelta(minutes=5))
    assert rpc.calls == 2  # carteira já conhecida não gasta RPC de novo


def test_scan_failure_keeps_last_map_and_says_unknown(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    sec.scan(db, token, True, FakeRC(), FakeRpc(now), now)
    r = sec.scan(db, token, False, FakeRC(fail=True), None, now)
    assert r.verdict != "clear" and len(r.holders) == 2 and r.facts["rugcheck_error"] == "429"


def test_rugcheck_rugged_sets_permanent_mark(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    sec.scan(db, token, False, FakeRC(_raw(rugged=True)))
    assert db.merge(token).rugged_at is not None


def test_queue_priority(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    assert sec.next_target(db)[1] is False  # só quente: verificação simples
    db.add(Signal(token_id=token.id, action="buy", strength="strong", status="active", headline="c", reasons=[], risk_score=1, risk_level="low",
                  opportunity_score=70, estimates=[], rules_version="sig-1"))
    db.commit()
    assert sec.next_target(db)[1] is False  # com sinal: veredito rápido primeiro
    sec.scan(db, token, False, FakeRC(), None)
    assert sec.next_target(db)[1] is True  # depois as carteiras
    sec.scan(db, token, True, FakeRC(), FakeRpc(utcnow()))
    assert sec.next_target(db) is None


def test_api_and_ranking_block(auth_client, fake_dex, db):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/security").json()
    assert j["verdict"] == "unknown" and j["checked_at"] is None and j["limitations"] and j["service_running"] is False
    token = db.query(SecurityReport).first()
    assert token is None
    from app.models import Token
    t = db.query(Token).filter(Token.address == SOL_MINT).one()
    sec.scan(db, t, False, FakeRC(_raw(mintAuthority="abc")))
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/security").json()
    assert j["verdict"] == "danger" and j["label"] == "Perigo" and any(c["key"] == "authority" for c in j["checks"])
    analyze_token(db, t, force=True)
    o = auth_client.get(f"{API}/opportunities").json()["items"][0]
    assert o["tier"] == "avoid" and o["security_verdict"] == "danger" and "Verificação de segurança: perigo" in o["critical_blocks"]


def test_security_gate_in_pipeline(db, fake_dex, monkeypatch):
    monkeypatch.setenv("SECURITY_GATE", "true")
    config.get_settings.cache_clear()
    token, _ = track_token(db, "solana", SOL_MINT)
    captured = {}
    from app.engine import pipeline, signals
    real = signals.decide
    monkeypatch.setattr(signals, "decide", lambda *a, **k: {**real(*a, **k), "action": "buy", "strength": "strong"})
    original = signals.upsert_signal

    def spy(db_, tid, analysis, decision, *rest):
        captured.update(decision)
        return original(db_, tid, analysis, decision, *rest)
    monkeypatch.setattr(signals, "upsert_signal", spy)
    analyze_token(db, token, force=True)
    assert captured["strength"] == "moderate"  # sem verificação não é compra forte
    assert pipeline is not None and db.query(PairSnapshot).count() >= 1


def test_mark_past_rugs_uses_history(db, fake_dex):
    from app.models import Analysis
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    db.add(Analysis(token_id=token.id, computed_at=utcnow(), engine_version="t", risk_score=1, risk_level="low", risk_confidence=1, opportunity_score=1,
                    opportunity_confidence=1, risk_factors=[], opportunity_factors=[], checks_not_performed=[], data_quality={}, invalidation_conditions=[],
                    features={"history_points_1h": 5, "price_change_h1": -98.0, "liquidity_change_vs_max_1h": -0.9}))
    db.commit()
    assert a is not None and [t.id for t in sec.mark_past_rugs(db)] == [token.id]
    assert sec.mark_past_rugs(db) == []  # não marca de novo


# ---------------- Idade das carteiras: nunca chuta ----------------
def _rpc_client(handler):
    import httpx

    from app.sources.http import ResilientClient
    return ResilientClient("https://rpc.test", transport=httpx.MockTransport(handler), sleep=lambda s: None, max_attempts=1)


def _rpc(screen_sigs, full=None):
    import json

    import httpx

    from app.safety import sources

    def responder(sigs):
        def handler(request):
            body = json.loads(request.content)
            if sigs == 429:
                return httpx.Response(429, json={})
            if body["method"] == "getTransaction":
                return httpx.Response(200, json={"result": {"transaction": {"message": {"accountKeys": [{"pubkey": "Funder"}]}}}})
            return httpx.Response(200, json={"result": [{"signature": f"s{i}", "blockTime": 1000 + i} for i in range(sigs)]})
        return handler
    for lim in (sources._screen_limiter, sources._full_limiter):
        lim.min_interval = 0
    return sources.WalletRpc(_rpc_client(responder(screen_sigs)), _rpc_client(responder(full if full is not None else 0)))


def test_quiet_wallet_in_short_history_is_definitely_not_new():
    assert _rpc(0).profile("W") == {"first_seen_ts": None, "signatures": 0, "complete": True, "funder": None}


def test_very_active_wallet_stays_unknown():
    p = _rpc(100).profile("W")
    assert p["complete"] is False and p["first_seen_ts"] is None


def test_few_transactions_needs_full_history_to_count():
    p = _rpc(3, full=3).profile("W")
    assert p["complete"] is True and p["first_seen_ts"] == 1002 and p["funder"] == "Funder"


def test_full_rpc_blocked_never_claims_new_and_pauses():
    rpc = _rpc(3, full=429)
    p = rpc.profile("W")
    assert p["complete"] is False and p["first_seen_ts"] is None
    assert rpc._full_paused_until > 0


def test_unknown_wallets_do_not_count_as_fresh(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)

    class Unknown:
        def profile(self, address):
            return {"first_seen_ts": None, "signatures": 3, "complete": False, "funder": None}
    r = sec.scan(db, token, True, FakeRC(), Unknown())
    assert r.facts["wallets"]["analyzed"] == 0 and r.facts["wallets"]["fresh_count"] == 0
    assert all(h.get("fresh") is None for h in r.holders)
    assert any(c["key"] == "fresh" and c["status"] == "unknown" for c in r.checks)
