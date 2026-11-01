"""Acertos dos sinais de subida/queda (`acc-1`) e plano de venda (`exit-1`)."""
from datetime import timedelta
from types import SimpleNamespace

from app.db import utcnow
from app.engine import accuracy, exit_plan
from app.ingest.service import track_token
from app.models import CollectorRun, PairSnapshot, Signal
from tests.conftest import SOL_MINT

API = "/api/v1"


def _signal(db, token, action, created_at, ref=1.0, strength="strong"):
    s = Signal(token_id=token.id, created_at=created_at, last_confirmed_at=created_at, action=action, strength=strength,
               status="active", headline=f"{action} {strength}", reasons=[], risk_score=20, risk_level="low",
               opportunity_score=60, reference_price_usd=ref, estimates=[], rules_version="sig-1")
    db.add(s)
    db.commit()
    return s


def _runs(db, start, end):
    t = start
    while t <= end:
        db.add(CollectorRun(source="dexscreener", job="refresh", started_at=t, finished_at=t, status="ok"))
        t += timedelta(seconds=60)
    db.commit()


def _snap(db, pair_id, at, price, tag):
    db.add(PairSnapshot(pair_id=pair_id, source="test", received_at=at, normalizer_version="t", payload_hash=tag, price_usd=price))
    db.commit()


# ---------------- Regra de acerto ----------------
def test_judge_rule():
    assert accuracy.judge("buy", 0.01) and not accuracy.judge("buy", 0.0) and not accuracy.judge("buy", -0.1)
    assert accuracy.judge("sell", -0.01) and not accuracy.judge("sell", 0.0) and not accuracy.judge("sell", 0.2)


def test_evaluate_hits_misses_pending_and_unevaluable(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    pair = token.primary_pair_id
    now = utcnow()
    t0 = now - timedelta(hours=2)
    buy = _signal(db, token, "buy", t0, ref=1.0)
    sell = _signal(db, token, "sell", t0 + timedelta(seconds=1), ref=1.0)
    _snap(db, pair, t0 + timedelta(minutes=5), 1.3, "a")
    _snap(db, pair, t0 + timedelta(minutes=14), 1.1, "b")    # fim de 15 min: +10%
    _snap(db, pair, t0 + timedelta(minutes=50), 0.9, "c")    # fim de 1 h: -10%
    _runs(db, t0 - timedelta(minutes=1), t0 + timedelta(minutes=65))
    items = accuracy.evaluate_signals(db, now=now, use_cache=False)
    res = {i["signal"].id: i["results"] for i in items}
    assert res[buy.id]["15m"]["status"] == "hit" and abs(res[buy.id]["15m"]["end_return"] - 0.1) < 1e-9
    assert res[buy.id]["1h"]["status"] == "miss" and abs(res[buy.id]["1h"]["max_return"] - 0.3) < 1e-9
    assert res[sell.id]["15m"]["status"] == "miss" and res[sell.id]["1h"]["status"] == "hit"
    assert res[buy.id]["6h"]["status"] == "pending"  # horizonte aberto: não conta
    s = accuracy.summarize(items)
    assert s["15m"]["all"] == {"hits": 1, "misses": 1, "evaluated": 2, "pending": 0, "unevaluable": 0, "hit_rate": 0.5}
    assert s["1h"]["buy"]["misses"] == 1 and s["1h"]["sell"]["hits"] == 1 and s["6h"]["all"]["pending"] == 2


def test_no_collection_means_unevaluable(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    _signal(db, token, "buy", utcnow() - timedelta(hours=2))
    items = accuracy.evaluate_signals(db, use_cache=False)
    assert items[0]["results"]["15m"]["status"] == "unevaluable"


def test_hold_is_reference_not_prediction_and_avoid_is_ignored(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    pair = token.primary_pair_id
    now = utcnow()
    t0 = now - timedelta(hours=2)
    _signal(db, token, "hold", t0, strength="none")
    _signal(db, token, "avoid", t0, strength="moderate")
    _signal(db, token, "buy", t0, strength="moderate")
    _snap(db, pair, t0 + timedelta(minutes=10), 1.2, "x")
    _runs(db, t0 - timedelta(minutes=1), t0 + timedelta(minutes=20))
    items = accuracy.evaluate_signals(db, now=now, use_cache=False)
    assert {i["signal"].action for i in items} == {"hold", "buy"}  # EVITAR não entra
    hold = next(i for i in items if i["signal"].action == "hold")
    assert hold["tier"] == "watch" and hold["results"]["15m"]["status"] == "hit"  # subiu mesmo sem sinal
    s15 = accuracy.summarize(items)["15m"]
    assert s15["all"]["evaluated"] == 1  # Observar fica fora das previsões
    assert s15["watch"]["hits"] == 1 and s15["possible_buy"]["hits"] == 1 and s15["priority_buy"]["evaluated"] == 0


def test_tier_mapping():
    assert accuracy.tier_of("buy", "strong") == "priority_buy"
    assert accuracy.tier_of("buy", "moderate") == "possible_buy"
    assert accuracy.tier_of("hold", "none") == "watch"
    assert accuracy.tier_of("sell", "strong") == "sell"
    assert accuracy.judge("hold", 0.1) and not accuracy.judge("hold", -0.1)


def test_accuracy_api(auth_client, fake_dex, db):
    token, _ = track_token(db, "solana", SOL_MINT)
    _signal(db, token, "buy", utcnow() - timedelta(hours=2))
    accuracy.clear_cache()
    r = auth_client.get(f"{API}/accuracy", params={"horizon": "15m"}).json()
    assert r["horizon"] == "15m" and set(r["summary"]) == {"15m", "1h", "6h"}
    assert r["items"][0]["prediction"] == "Deve subir" and r["items"][0]["link"] == f"/tokens/solana/{SOL_MINT}"
    assert auth_client.get(f"{API}/accuracy", params={"action": "sell"}).json()["total"] == 0
    _signal(db, token, "hold", utcnow() - timedelta(hours=2), strength="none")
    accuracy.clear_cache()
    assert auth_client.get(f"{API}/accuracy").json()["total"] == 1  # Observar só aparece quando pedido
    watch = auth_client.get(f"{API}/accuracy", params={"tier": "watch"}).json()
    assert watch["total"] == 1 and watch["items"][0]["tier_label"] == "Observar (referência)"
    assert auth_client.get(f"{API}/accuracy", params={"tier": "priority_buy"}).json()["items"][0]["tier"] == "priority_buy"
    assert set(watch["summary"]["1h"]) >= {"priority_buy", "possible_buy", "watch", "sell", "all"}
    assert auth_client.get(f"{API}/accuracy", params={"horizon": "2m"}).status_code == 422


# ---------------- Plano de venda ----------------
def _analysis(ids=()):
    return SimpleNamespace(risk_factors=[{"id": i} for i in ids])


def test_plan_hold_has_targets_and_stop():
    p = exit_plan.build(1.0, 50_000, _analysis(), SimpleNamespace(action="buy", strength="strong", reference_price_usd=1.0, reasons=[]),
                        None, [])
    assert p["urgency"] == "hold" and p["sell_percent_now"] == 0
    assert [t["sell_percent"] for t in p["take_profits"]] == [30, 30, 40]
    assert abs(p["take_profits"][0]["price_usd"] - 1.2) < 1e-9 and abs(p["stop"]["price_usd"] - 0.85) < 1e-9
    assert any("liquidez" in t for t in p["triggers"])


def test_plan_sell_now_cases():
    strong_sell = SimpleNamespace(action="sell", strength="strong", reference_price_usd=1.0, reasons=["Preço caiu"])
    assert exit_plan.build(1.0, 50_000, _analysis(), strong_sell, None, [])["sell_percent_now"] == 100
    crash = exit_plan.build(1.0, 50_000, _analysis(["A4_price_crash"]), None, None, [])
    assert crash["urgency"] == "sell_now" and "40%" in crash["reasons"][0]
    below = exit_plan.build(0.8, 50_000, _analysis(), SimpleNamespace(action="hold", strength="none", reference_price_usd=1.0, reasons=[]), None, [])
    assert below["urgency"] == "sell_now" and below["stop"]["reached"]
    reduce = exit_plan.build(1.0, 50_000, _analysis(), SimpleNamespace(action="avoid", strength="moderate", reference_price_usd=1.0, reasons=[]), None, [])
    assert reduce["urgency"] == "reduce" and reduce["sell_percent_now"] == 50


def test_plan_uses_position_and_estimate():
    pos = SimpleNamespace(entry_price_usd=0.5, quantity=10)
    est = [{"horizon": "1h", "basis": "general", "end_p75": 0.35}]
    advice = {"has_position": True, "sell_percent": 50, "reasons": ["Lucro de 100%"]}
    p = exit_plan.build(1.0, 50_000, _analysis(), None, pos, est, advice)
    assert p["reference_price_usd"] == 0.5 and "compra" in p["reference_kind"]
    assert abs(p["take_profits"][0]["change_from_reference"] - 0.35) < 1e-9  # alvo 1 usa a faixa alta típica de 1 h
    assert p["sell_percent_now"] == 50 and p["urgency"] == "reduce"


def test_plan_without_price():
    assert exit_plan.build(None, None, None, None, None, [])["urgency"] == "no_data"


def test_exit_plan_api(auth_client, fake_dex):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    r = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan")
    assert r.status_code == 200
    j = r.json()
    assert j["urgency"] in ("sell_now", "reduce", "hold") and j["freshness"]["observed_at"]
    assert len(j["take_profits"]) == 3 and j["stop"]["sell_percent"] == 100 and j["has_position"] is False
