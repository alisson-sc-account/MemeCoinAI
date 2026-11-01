"""Sinais, rótulos de retorno por horizonte, estimativas e sugestão de posição."""
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.db import utcnow
from app.engine import outcomes
from app.engine.pipeline import analyze_token
from app.engine.signals import advise, allocation, decide, upsert_signal
from app.ingest.service import track_token
from app.models import Analysis, AnalysisOutcome, CollectorRun, PairSnapshot, Signal
from tests.conftest import SOL_MINT

API = "/api/v1"


def _analysis(risk=20.0, opp=70.0, risk_ids=(), opp_pts=(("O1_volume_accel", "Volume acelerando", 20),), insufficient=False, level="low", data_points=0, observed_points=10):
    factors = [{"id": i, "label": i, "points": observed_points, "category": "liquidity"} for i in risk_ids]
    if data_points:
        factors.append({"id": "D3_technical_unchecked", "label": "não verificado", "points": data_points, "category": "data"})
    return SimpleNamespace(
        risk_score=risk, opportunity_score=opp, risk_level=level, computed_at=utcnow(), id=1,
        risk_factors=factors,
        opportunity_factors=[{"id": i, "label": label, "points": p} for i, label, p in opp_pts],
        data_quality={"insufficient_data": insufficient},
    )


# ---------------- Regras de decisão ----------------
def test_decide_buy_strong_and_moderate():
    d = decide(_analysis(opp=70), {"liquidity_usd": 50_000}, [], True)
    assert (d["action"], d["strength"]) == ("buy", "strong") and "Volume acelerando" in d["reasons"]
    d = decide(_analysis(opp=50), {"liquidity_usd": 50_000}, [], True)
    assert (d["action"], d["strength"]) == ("buy", "moderate")


def test_decide_buy_blocked_by_data_freshness_and_liquidity():
    assert decide(_analysis(opp=80, insufficient=True), {"liquidity_usd": 50_000}, [], True)["action"] == "hold"
    assert decide(_analysis(opp=80), {"liquidity_usd": 50_000}, [], False)["action"] == "hold"
    assert decide(_analysis(opp=80), {"liquidity_usd": 5_000}, [], True)["action"] == "hold"


def test_history_that_contradicts_downgrades_strong_buy():
    bad = [{"horizon": "1h", "basis": "similar", "end_median": -0.05, "p_up_10": 0.1}]
    d = decide(_analysis(opp=80), {"liquidity_usd": 50_000}, bad, True)
    assert d["strength"] == "moderate"


def test_decide_sell_and_avoid():
    d = decide(_analysis(risk=55, risk_ids=("L2_liquidity_drop_severe",)), {"liquidity_usd": 50_000}, [], True)
    assert (d["action"], d["strength"]) == ("sell", "strong")
    d = decide(_analysis(risk=30, risk_ids=("A1_sell_pressure",)), {"liquidity_usd": 50_000, "price_change_h1": -15}, [], True)
    assert (d["action"], d["strength"]) == ("sell", "moderate")
    d = decide(_analysis(risk=40, risk_ids=("T1_mint_authority",)), {"liquidity_usd": 50_000}, [], True)
    assert d["action"] == "avoid"


def test_no_sell_or_buy_on_stale_data():
    # Regressão: "Venda agora" saiu para um token com cotação de 2 h atrás.
    d = decide(_analysis(risk=55, risk_ids=("L2_liquidity_drop_severe",)), {"liquidity_usd": 50_000}, [], False)
    assert d["action"] == "hold" and "desatualizados" in d["reasons"][0]


def test_high_risk_from_missing_data_is_avoid_not_sell():
    # Regressão: risco 80 composto por falta de verificação não é sinal de venda.
    d = decide(_analysis(risk=80, data_points=50, risk_ids=("L1_liquidity_low",), observed_points=30), {"liquidity_usd": 50_000}, [], True)
    assert d["action"] == "avoid"
    d = decide(_analysis(risk=80, risk_ids=("T1_mint_authority", "L1_liquidity_very_low"), observed_points=40), {"liquidity_usd": 50_000}, [], True)
    assert (d["action"], d["strength"]) == ("sell", "strong")


# ---------------- Sugestão de posição ----------------
def test_advise_without_position_buy_fraction():
    sig = SimpleNamespace(action="buy", strength="strong")
    a = advise(sig, None, 1.0, None)
    assert a["buy_percent_of_plan"] == 50 and not a["has_position"]


def test_advise_with_position():
    pos = SimpleNamespace(quantity=1000, entry_price_usd=1.0)
    assert advise(SimpleNamespace(action="sell", strength="strong"), pos, 0.8, None)["sell_percent"] == 100
    assert advise(SimpleNamespace(action="sell", strength="moderate"), pos, 0.8, None)["sell_percent"] == 50
    a = advise(SimpleNamespace(action="hold", strength="none"), pos, 2.2, None)
    assert a["sell_percent"] == 50 and a["pnl"] == 1.2 and a["keep_percent"] == 50
    assert advise(SimpleNamespace(action="hold", strength="none"), pos, 1.1, None)["sell_percent"] == 0


def test_advise_warns_about_slippage():
    pos = SimpleNamespace(quantity=100_000, entry_price_usd=None)
    est = {"available": True, "spot_price_usd": 1.0,
           "scenarios": [{"tokens_sold": 100.0, "share_of_pool_base": 0.001}]}  # reserva = 100 mil
    a = advise(SimpleNamespace(action="sell", strength="strong"), pos, 1.0, est)
    assert a["slippage_note"] and "em partes" in a["slippage_note"]


# ---------------- Saldo do usuário (simulação) ----------------
def test_allocation_rule():
    assert allocation("buy", "strong", 10, 50, "BRL", 10) == {"percent_of_balance": 10.0, "amount": 5.0, "currency": "BRL", "max_trade_percent": 10, "rule": "size-1"}
    assert allocation("buy", "moderate", 10, 50, "BRL", 10)["percent_of_balance"] == 5.0
    assert allocation("buy", "strong", 30, 50, "BRL", 10)["amount"] == 2.5  # risco ≥ 25 corta pela metade
    assert allocation("sell", "strong", 10, 50, "BRL", 10) is None
    assert allocation("buy", "strong", 10, None, "BRL", 10) is None


def test_advise_uses_balance():
    user = SimpleNamespace(balance_amount=50.0, balance_currency="BRL", max_trade_percent=10.0)
    sig = SimpleNamespace(action="buy", strength="strong", risk_score=10)
    a = advise(sig, None, 1.0, None, user)
    assert a["summary"] == "Compre agora com 10% do seu saldo (R$ 5,00)." and a["buy_amount"] == 5.0 and a["currency"] == "BRL"
    no_balance = SimpleNamespace(balance_amount=None, balance_currency="BRL", max_trade_percent=10.0)
    assert "Informe seu saldo" in " ".join(advise(sig, None, 1.0, None, no_balance)["reasons"])


def test_api_account_settings_and_signal_allocation(auth_client, fake_dex, db):
    assert auth_client.get(f"{API}/auth/settings").json() == {"balance_amount": None, "balance_currency": "BRL", "max_trade_percent": 10.0}
    r = auth_client.put(f"{API}/auth/settings", json={"balance_amount": 50, "balance_currency": "BRL", "max_trade_percent": 20})
    assert r.status_code == 200 and auth_client.get(f"{API}/auth/settings").json()["balance_amount"] == 50
    assert auth_client.put(f"{API}/auth/settings", json={"balance_amount": -1}).status_code == 422
    assert auth_client.put(f"{API}/auth/settings", json={"balance_amount": 50, "max_trade_percent": 0}).status_code == 422
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    sig = db.scalar(select(Signal).where(Signal.status == "active"))
    sig.action, sig.strength, sig.risk_score = "buy", "strong", 10.0
    db.commit()
    item = auth_client.get(f"{API}/signals").json()["items"][0]
    assert item["allocation"] == {"percent_of_balance": 20.0, "amount": 10.0, "currency": "BRL", "max_trade_percent": 20.0, "rule": "size-1"}
    d = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()
    assert d["advice"]["summary"] == "Compre agora com 20% do seu saldo (R$ 10,00)."


# ---------------- Rótulos e estimativas (sem vazamento) ----------------
def _runs(db, start, end, every=timedelta(seconds=60)):
    t = start
    while t <= end:
        db.add(CollectorRun(source="dexscreener", job="refresh", started_at=t, finished_at=t, status="ok"))
        t += every
    db.commit()


def test_label_outcome_uses_only_window_and_carries_price(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    t0 = a.computed_at
    ref = a.features["price_usd"]
    for minutes, mult in ((5, 1.3), (10, 0.9), (70, 5.0)):  # 70 min fica fora do horizonte de 15 min/1 h
        db.add(PairSnapshot(pair_id=a.pair_id, source="test", received_at=t0 + timedelta(minutes=minutes),
                            normalizer_version="t", payload_hash=f"h{minutes}", price_usd=ref * mult))
    _runs(db, t0 - timedelta(minutes=1), t0 + timedelta(minutes=75))
    n = outcomes.label_due(db, now=t0 + timedelta(minutes=80))
    assert n >= 2
    o15 = db.scalar(select(AnalysisOutcome).where(AnalysisOutcome.analysis_id == a.id, AnalysisOutcome.horizon_seconds == 900))
    o1h = db.scalar(select(AnalysisOutcome).where(AnalysisOutcome.analysis_id == a.id, AnalysisOutcome.horizon_seconds == 3600))
    assert o15.status == "ok" and abs(o15.max_return - 0.3) < 1e-9 and abs(o15.end_return - (-0.1)) < 1e-9
    assert o1h.status == "ok" and abs(o1h.max_return - 0.3) < 1e-9  # o pico de 70 min não vaza
    assert db.scalar(select(AnalysisOutcome).where(AnalysisOutcome.horizon_seconds == 21600)) is None  # 6 h não terminou


def test_label_unevaluable_without_collection(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    outcomes.label_due(db, now=a.computed_at + timedelta(minutes=20))
    o = db.scalar(select(AnalysisOutcome).where(AnalysisOutcome.horizon_seconds == 900))
    assert o.status == "unevaluable"


def test_estimate_requires_samples_and_ignores_future(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    now = utcnow()
    outcomes._cache.clear()
    assert outcomes.estimate(db, 70, 20, now)[0]["basis"] == "insufficient"
    # Rótulos sintéticos de 40 análises distintas (restrição única por análise + horizonte).
    for i in range(40):
        extra = Analysis(token_id=token.id, pair_id=a.pair_id, computed_at=now - timedelta(hours=2, minutes=i), engine_version="t",
                         risk_score=20, risk_level="low", risk_confidence=1, opportunity_score=70, opportunity_confidence=1,
                         risk_factors=[], opportunity_factors=[], checks_not_performed=[], data_quality={}, features={},
                         invalidation_conditions=[])
        db.add(extra)
        db.flush()
        db.add(AnalysisOutcome(analysis_id=extra.id, token_id=token.id, horizon_seconds=900, analysis_time=extra.computed_at,
                               opportunity_score=70, risk_score=20, status="ok", max_return=0.2 if i % 2 else 0.05,
                               min_return=-0.05, end_return=0.1 if i % 2 else -0.02))
    db.commit()
    outcomes._cache.clear()
    e15 = outcomes.estimate(db, 72, 10, now)[0]
    assert e15["basis"] == "similar" and e15["n"] >= 40 and e15["p_up_10"] == 0.5
    # Reavaliando "antes" dos rótulos existirem, nada é usado (sem vazamento).
    outcomes._cache.clear()
    assert outcomes.estimate(db, 72, 10, now - timedelta(hours=3))[0]["basis"] == "insufficient"


# ---------------- Persistência de sinais ----------------
def test_upsert_signal_dedup_and_escalation(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    first = db.scalar(select(Signal).where(Signal.token_id == token.id, Signal.status == "active"))
    assert first is not None
    same = {"action": first.action, "strength": first.strength, "headline": first.headline, "reasons": []}
    s, created = upsert_signal(db, token.id, a, same, [], 1.0)
    assert not created and s.id == first.id
    new = {"action": "sell", "strength": "strong", "headline": "Venda", "reasons": ["x"]}
    s2, created2 = upsert_signal(db, token.id, a, new, [], 1.0)
    db.commit()
    db.refresh(first)
    assert created2 and first.status == "superseded" and s2.status == "active"


# ---------------- API ----------------
def test_api_signals_positions_and_detail(auth_client, fake_dex, db):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    sigs = auth_client.get(f"{API}/signals").json()
    assert sigs["total"] == 1 and sigs["items"][0]["link"] == f"/tokens/solana/{SOL_MINT}"
    sid = sigs["items"][0]["id"]
    assert auth_client.get(f"{API}/signals", params={"after_id": sid}).json()["total"] == 0
    assert auth_client.get(f"{API}/signals/{sid}").status_code == 200
    assert auth_client.get(f"{API}/signals/performance").json() == []

    d = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()
    assert d["signal"]["id"] == sid and d["position"] is None and d["advice"]["has_position"] is False
    assert [e["horizon"] for e in d["estimates"]] == ["15m", "1h", "6h"]
    assert all(e["basis"] == "insufficient" for e in d["estimates"])

    r = auth_client.put(f"{API}/positions/solana/{SOL_MINT}", json={"quantity": 1000, "entry_price_usd": 0.000001})
    assert r.status_code == 200 and r.json()["pnl"] > 2  # preço atual 0.000003187
    d = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()
    assert d["position"]["quantity"] == 1000 and d["advice"]["has_position"] and d["advice"]["sell_percent"] == 50
    assert len(auth_client.get(f"{API}/positions").json()) == 1
    assert auth_client.put(f"{API}/positions/solana/{SOL_MINT}", json={"quantity": -1}).status_code == 422
    assert auth_client.delete(f"{API}/positions/solana/{SOL_MINT}").status_code == 204
    assert auth_client.get(f"{API}/positions").json() == []


def test_positions_are_per_user(client, fake_dex):
    client.post(f"{API}/auth/login", json={"username": "alisson", "password": "test-initial-pw"})
    client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    client.put(f"{API}/positions/solana/{SOL_MINT}", json={"quantity": 10})
    client.post(f"{API}/auth/logout")
    client.post(f"{API}/auth/login", json={"username": "natan", "password": "test-initial-pw"})
    assert client.get(f"{API}/positions").json() == []
