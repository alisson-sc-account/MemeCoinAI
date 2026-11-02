"""Níveis de oportunidade (casos da seção 16.5 do prompt mestre), histerese,
política de custo zero, trava do worker e saúde."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.db import utcnow
from app.engine import ranking
from app.engine.signals import decide
from app.ingest.service import track_token
from app.models import CollectorRun
from app.sources.registry import SOURCES, validate_policy
from app.worker_lock import WorkerAlreadyRunning, WorkerLock
from tests.conftest import SOL_MINT, make_pair

API = "/api/v1"
GOOD_FEATURES = {"available": True, "price_usd": 0.01, "liquidity_usd": 80_000}


def _analysis(risk_ids=(), checks_not_performed=(), opp_labels=("Volume acelerando",), data_points=0):
    factors = [{"id": i, "label": i, "points": 20, "category": "technical" if i.startswith("T") else "liquidity"} for i in risk_ids]
    if data_points:
        factors.append({"id": "D4_concentration_unchecked", "label": "Concentração não verificada", "points": data_points, "category": "data"})
    return SimpleNamespace(
        risk_factors=factors,
        opportunity_factors=[{"id": f"O{i}", "label": lbl, "points": 10} for i, lbl in enumerate(opp_labels)],
        checks_not_performed=[{"check": c, "reason": "rate limited (HTTP 429)"} for c in checks_not_performed],
    )


# ---------------- Casos obrigatórios 16.5 ----------------
def test_good_market_without_social_or_holders_still_gets_positive_tier():
    c = ranking.classify(_analysis(checks_not_performed=("holder_concentration",), data_points=5), GOOD_FEATURES,
                         "buy", "strong", "fresh")
    assert c["tier"] == "priority_buy"
    assert c["decision_quality"] == "partial"  # cobertura reduzida, não "sem sinal"
    assert any("social" in m.lower() for m in c["missing_data"])
    assert any("holders" in m.lower() for m in c["missing_data"])


def test_missing_secondary_is_not_no_reliable_signal():
    c = ranking.classify(_analysis(checks_not_performed=("holder_concentration", "mint_authorities")), GOOD_FEATURES,
                         "hold", "none", "fresh")
    assert c["decision_quality"] != "no_reliable_signal" and c["tier"] == "watch"


def test_missing_price_or_liquidity_never_positive():
    for feats in ({"available": True, "price_usd": None, "liquidity_usd": 80_000},
                  {"available": True, "price_usd": 0.01, "liquidity_usd": None}):
        c = ranking.classify(_analysis(), feats, "buy", "strong", "fresh")
        assert c["tier"] == "watch" and c["decision_quality"] == "no_reliable_signal"


def test_critical_risk_blocks_buy_even_with_high_momentum():
    c = ranking.classify(_analysis(risk_ids=("T1_mint_authority",), opp_labels=("a", "b", "c", "d")), GOOD_FEATURES,
                         "buy", "strong", "fresh")
    assert c["tier"] == "avoid" and c["critical_blocks"] == ["Autoridade de mint ativa"]


def test_holder_rpc_failure_is_partial_not_complete():
    c = ranking.classify(_analysis(checks_not_performed=("holder_concentration",)), GOOD_FEATURES, "buy", "moderate", "fresh")
    assert c["decision_quality"] == "partial" and "429" in c["decision_quality_reason"]


def test_stale_data_changes_quality():
    c = ranking.classify(_analysis(), GOOD_FEATURES, "buy", "strong", "stale")
    assert c["decision_quality"] == "no_reliable_signal" and c["tier"] == "watch"
    assert ranking.classify(_analysis(), GOOD_FEATURES, "buy", "strong", "delayed")["tier"] == "priority_buy"


def test_token_without_analysis_is_watch():
    c = ranking.classify(None, {}, None, None, "no_data")
    assert c["tier"] == "watch" and c["decision_quality"] == "no_reliable_signal"


def test_sort_items_missing_values_last_and_tier_default():
    items = [{"tier": "watch", "score": 90, "liquidity_usd": None}, {"tier": "priority_buy", "score": 10, "liquidity_usd": 5},
             {"tier": "possible_buy", "score": 50, "liquidity_usd": 50}]
    assert [i["tier"] for i in ranking.sort_items(items)] == ["priority_buy", "possible_buy", "watch"]
    assert [i["liquidity_usd"] for i in ranking.sort_items(items, "liquidity_usd")] == [50, 5, None]


# ---------------- Histerese ----------------
def _decide_analysis(opp):
    return SimpleNamespace(risk_score=20, opportunity_score=opp, risk_factors=[], opportunity_factors=[],
                           data_quality={"insufficient_data": False})


def test_hysteresis_keeps_buy_on_small_drop():
    feats = {"liquidity_usd": 50_000}
    assert decide(_decide_analysis(42), feats, [], True)["action"] == "hold"  # entrada exige 45
    assert decide(_decide_analysis(42), feats, [], True, previous=("buy", "moderate"))["action"] == "buy"
    assert decide(_decide_analysis(38), feats, [], True, previous=("buy", "moderate"))["action"] == "hold"
    strong = decide(_decide_analysis(57), feats, [], True, previous=("buy", "strong"))
    assert (strong["action"], strong["strength"]) == ("buy", "strong")
    assert decide(_decide_analysis(57), feats, [], True)["strength"] == "moderate"


# ---------------- Política de custo zero ----------------
def test_cost_policy_only_class_a_enabled():
    assert validate_policy() == []
    enabled = {s.key for s in SOURCES if s.enabled}
    assert enabled == {"dexscreener", "solana_rpc", "jupiter_price", "geckoterminal", "solana_pool", "jupiter_tokens", "rugcheck_security", "publicnode_rpc", "solana_logs", "ntfy"}  # jupiter_price: atualização rápida
    assert all(not s.needs_key for s in SOURCES if s.enabled)  # inicia sem nenhuma chave
    assert len(SOURCES) == 43  # as 36 do fluxograma + as 7 das pistas rápidas, descoberta e segurança


def test_conditional_sources_record_real_verification():
    for s in SOURCES:
        if s.access_class == "B":
            assert s.verified_on and "HTTP 200" in s.verification and not s.enabled


# ---------------- Trava do worker ----------------
def test_worker_lock_blocks_second_instance(tmp_path):
    path = tmp_path / "worker.lock"
    first = WorkerLock(path).acquire()
    with pytest.raises(WorkerAlreadyRunning):
        WorkerLock(path).acquire()
    first.release()
    WorkerLock(path).acquire().release()  # liberada, pode adquirir de novo


# ---------------- API ----------------
def test_health_reports_worker_state(client, db):
    h = client.get(f"{API}/health").json()
    assert h["worker"]["status"] == "unknown" and h["status"] == "degraded"
    assert h["worker"]["last_cycle_duration_seconds"] is None
    finished = utcnow()
    db.add(CollectorRun(source="dexscreener", job="refresh", started_at=finished - timedelta(seconds=45),
                        finished_at=finished, status="ok"))
    db.commit()
    h = client.get(f"{API}/health").json()
    assert h["worker"]["status"] == "running"
    assert h["worker"]["last_cycle_duration_seconds"] == 45.0
    db.add(CollectorRun(source="dexscreener", job="refresh", started_at=utcnow() - timedelta(hours=1),
                        finished_at=utcnow() - timedelta(hours=1), status="ok"))
    db.commit()
    h = client.get(f"{API}/health").json()["worker"]
    assert h["status"] == "running" and h["last_cycle_duration_seconds"] == 45.0  # usa a mais recente


def test_registry_endpoint(auth_client):
    r = auth_client.get(f"{API}/system/registry").json()
    assert len(r) == 43 and {x["access_class"] for x in r} <= {"A", "B", "C", "D"}
    assert next(x for x in r if x["key"] == "birdeye")["enabled"] is False


def test_opportunities_lists_multiple_tokens_with_tiers(auth_client, fake_dex, db):
    other = "Other111111111111111111111111111111111111111"
    fake_dex.pairs.append(make_pair(pairAddress="OtherPair11111111111111111111111111111111111",
                                    baseToken={"address": other, "symbol": "OTH"}))
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": other})
    page = auth_client.get(f"{API}/opportunities").json()
    assert page["total"] == 2 and sum(page["counts"].values()) == 2
    item = page["items"][0]
    for key in ("tier", "tier_label", "score", "confidence", "coverage", "decision_quality", "reasons_for",
                "reasons_against", "missing_data", "freshness", "link"):
        assert key in item
    assert item["score"] is not None and item["confidence"] is not None  # separados, não um número só
    assert auth_client.get(f"{API}/opportunities", params={"tier": "avoid"}).json()["total"] == page["counts"]["avoid"]
    assert auth_client.get(f"{API}/opportunities", params={"min_liquidity": 1e12}).json()["total"] == 0
    assert auth_client.get(f"{API}/opportunities", params={"sort": "bogus"}).status_code == 422
    assert auth_client.get(f"{API}/opportunities", params={"sort": "liquidity_usd"}).status_code == 200


def test_opportunities_requires_session(client):
    assert client.get(f"{API}/opportunities").status_code == 401


def test_untracked_token_not_in_opportunities(auth_client, fake_dex, db):
    token, _ = track_token(db, "solana", SOL_MINT)
    token.is_tracked = False
    db.commit()
    assert auth_client.get(f"{API}/opportunities").json()["total"] == 0
