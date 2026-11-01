"""Testes de integração: ingestão -> persistência -> motor -> alertas -> API.

Fonte de mercado SIMULADA (FakeDex). Nenhuma chamada de rede real.
"""
from datetime import timedelta

from sqlalchemy import select

from app.db import utcnow
from app.engine.alerts import AlertCandidate, upsert_alert
from app.engine.pipeline import analyze_token, sync_source_alerts
from app.engine.predict import evaluate_prediction, maybe_create_predictions
from app.ingest.service import refresh_tracked, source_status, track_token
from app.models import Alert, Analysis, PairSnapshot, Prediction, RiskCheck, Token, User
from tests.conftest import SOL_MINT, make_pair

API = "/api/v1"


# ---------------- Autenticação ----------------
def test_passwords_are_hashed(client, db):
    users = db.scalars(select(User)).all()
    assert {u.username for u in users} == {"natan", "alisson"}
    assert all(u.password_hash.startswith("$argon2") for u in users)
    assert all("test-initial-pw" not in u.password_hash for u in users)


def test_protected_routes_require_session(client):
    assert client.get(f"{API}/health").status_code == 200
    for path in ("/tokens", "/alerts", "/dashboard/summary", "/predictions", "/system/sources", "/auth/me"):
        r = client.get(API + path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_login_logout_cycle(client):
    r = client.post(f"{API}/auth/login", json={"username": "natan", "password": "errada"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    r = client.post(f"{API}/auth/login", json={"username": "NATAN", "password": "test-initial-pw"})
    assert r.status_code == 200
    assert r.json()["user"]["must_change_password"] is True
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get(f"{API}/auth/me").json()["username"] == "natan"
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/auth/me").status_code == 401


def test_login_rate_limited(client):
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"username": "natan", "password": "x"})
    r = client.post(f"{API}/auth/login", json={"username": "natan", "password": "test-initial-pw"})
    assert r.status_code == 429


def test_change_password(auth_client):
    r = auth_client.post(f"{API}/auth/change-password", json={"current_password": "test-initial-pw", "new_password": "nova-senha-forte"})
    assert r.status_code == 204
    assert auth_client.get(f"{API}/auth/me").json()["must_change_password"] is False


# ---------------- Ingestão ----------------
def test_ingest_dedups_cached_responses(db, fake_dex):
    token, res = track_token(db, "solana", SOL_MINT)
    assert res.ok and token.symbol == "TEST"
    refresh_tracked(db, fake_dex.client())  # mesma resposta -> duplicata
    assert len(db.scalars(select(PairSnapshot)).all()) == 1
    fake_dex.pairs = [make_pair(priceUsd="0.0000040")]
    touched = refresh_tracked(db, fake_dex.client())
    assert touched == {token.id}
    snaps = db.scalars(select(PairSnapshot)).all()
    assert len(snaps) == 2 and snaps[-1].received_at >= snaps[0].received_at
    assert snaps[-1].normalizer_version == "dexs-1" and snaps[-1].source_time is None


def test_quote_side_pairs_are_ignored(db, fake_dex):
    track_token(db, "solana", SOL_MINT)
    # Par em que nosso token aparece como quote não deve virar snapshot do token.
    other = make_pair(pairAddress="OtherPair1111111111111111111111111111111111",
                      baseToken={"address": "OtherMint111111111111111111111111111111111", "symbol": "OTH"})
    fake_dex.pairs.append(other)
    refresh_tracked(db, fake_dex.client())
    assert db.scalar(select(Token).where(Token.symbol == "OTH")) is None


def test_source_failure_is_reported(db, fake_dex):
    track_token(db, "solana", SOL_MINT)
    fake_dex.fail = True
    for _ in range(3):
        refresh_tracked(db, fake_dex.client())
    st = source_status(db, "dexscreener")
    assert st["status"] == "down" and st["consecutive_failures"] == 3
    sync_source_alerts(db, ("dexscreener",))
    alert = db.scalar(select(Alert).where(Alert.alert_type == "source_unavailable"))
    assert alert and alert.status == "open" and alert.token_id is None
    fake_dex.fail = False
    refresh_tracked(db, fake_dex.client())
    sync_source_alerts(db, ("dexscreener",))
    db.refresh(alert)
    assert alert.status == "resolved"


# ---------------- Motor -> alertas ----------------
def _add_mint_check(db, token, mint_authority=None, freeze=None, at=None):
    db.add(RiskCheck(token_id=token.id, check_type="solana_mint_account", status="flagged" if (mint_authority or freeze) else "ok",
                     result={"mint_authority": mint_authority, "freeze_authority": freeze, "risky_extensions": [], "program": "spl-token"},
                     source="solana_rpc", method_version="sol-1", checked_at=at or utcnow()))
    db.commit()


def test_liquidity_drop_generates_alert_and_dedups(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    _add_mint_check(db, token)
    analyze_token(db, token, force=True)
    fake_dex.pairs = [make_pair(liquidity={"usd": 60000, "base": 13e9, "quote": 180})]
    refresh_tracked(db, fake_dex.client())
    a = analyze_token(db, token, force=True)
    assert any(f["id"].startswith("L2_liquidity_drop") for f in a.risk_factors)
    alerts = db.scalars(select(Alert).where(Alert.alert_type == "liquidity_drop")).all()
    assert len(alerts) == 1 and alerts[0].severity == "critical"
    assert alerts[0].evidence["prior_max_usd"] == 318553.22
    # Reanálise com a mesma condição não cria alerta duplicado.
    analyze_token(db, token, force=True)
    alerts = db.scalars(select(Alert).where(Alert.alert_type == "liquidity_drop")).all()
    assert len(alerts) == 1 and alerts[0].occurrences == 2


def test_severity_escalation_creates_new_alert(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    low = AlertCandidate("risk_high", "high", "t", "r", {}, 0.5)
    crit = AlertCandidate("risk_high", "critical", "t", "r", {}, 0.5)
    a1, new1 = upsert_alert(db, low, token.id, None, None)
    a2, new2 = upsert_alert(db, low, token.id, None, None)
    a3, new3 = upsert_alert(db, crit, token.id, None, None)
    assert new1 and not new2 and new3 and a1.id == a2.id != a3.id


def test_permission_change_alert(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    _add_mint_check(db, token, at=utcnow() - timedelta(hours=1))
    _add_mint_check(db, token, mint_authority="NewAuth111")
    analyze_token(db, token, force=True)
    types = {a.alert_type for a in db.scalars(select(Alert))}
    assert {"permission_change", "mint_authority_active"} <= types


def test_condition_alerts_auto_resolve(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    analyze_token(db, token, force=True)
    # Token recém-adicionado: período de carência, sem alerta de dados insuficientes.
    assert db.scalar(select(Alert).where(Alert.alert_type == "insufficient_data")) is None
    token.first_seen_at = utcnow() - timedelta(hours=2)
    db.commit()
    analyze_token(db, token, force=True)  # sem verificação técnica: cobertura 1/4
    ins = db.scalar(select(Alert).where(Alert.alert_type == "insufficient_data"))
    assert ins is not None and ins.status == "open"
    _add_mint_check(db, token)
    db.add(RiskCheck(token_id=token.id, check_type="solana_largest_accounts", status="ok",
                     result={"top10_share": 0.1, "top1_share": 0.05}, source="solana_rpc", method_version="sol-1", checked_at=utcnow()))
    db.commit()
    analyze_token(db, token, force=True)
    db.refresh(ins)
    assert ins.status == "resolved"


# ---------------- Previsões ----------------
def test_prediction_lifecycle(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    a = analyze_token(db, token, force=True)
    preds = db.scalars(select(Prediction)).all()
    assert {p.target for p in preds} == {"up_20pct_6h", "down_30pct_6h"}
    assert all(p.calibrated is False and p.baseline_probability is None for p in preds)
    # Não cria nova previsão dentro de meio horizonte.
    assert maybe_create_predictions(db, token.id, token.primary_pair_id, a, a.features, None) == []

    up = next(p for p in preds if p.target == "up_20pct_6h")
    evaluate_prediction(db, up, now=up.created_at + timedelta(hours=1))
    assert up.status == "pending"  # horizonte aberto: não contabiliza

    ref = up.reference_price_usd
    for i, mult in enumerate((1.05, 1.25, 1.10)):
        db.add(PairSnapshot(pair_id=up.pair_id, source="test", received_at=up.created_at + timedelta(hours=2 * i + 1, minutes=50),
                            normalizer_version="test", payload_hash=f"h{i}", price_usd=ref * mult))
    db.commit()
    evaluate_prediction(db, up, now=up.resolve_at + timedelta(minutes=1))
    assert up.status == "evaluated" and up.outcome is True
    assert abs(up.observed_max_return - 0.25) < 1e-9

    down = next(p for p in preds if p.target == "down_30pct_6h")
    evaluate_prediction(db, down, now=down.resolve_at + timedelta(minutes=1))
    assert down.status == "evaluated" and down.outcome is False


def test_prediction_unevaluable_without_coverage(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    analyze_token(db, token, force=True)
    p = db.scalars(select(Prediction)).first()
    evaluate_prediction(db, p, now=p.resolve_at + timedelta(minutes=1))
    assert p.status == "unevaluable" and p.outcome is None


# ---------------- API ponta a ponta ----------------
def test_api_end_to_end(auth_client, fake_dex, db):
    r = auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["token"]["symbol"] == "TEST" and item["freshness"]["status"] == "fresh"
    assert item["scores"]["risk_level"] in ("low", "moderate", "high", "critical")

    # Lista com filtros e ordenação
    r = auth_client.get(f"{API}/tokens", params={"q": "test", "min_liquidity": 100000, "sort": "liquidity_usd"})
    assert r.status_code == 200 and r.json()["total"] == 1
    assert auth_client.get(f"{API}/tokens", params={"min_liquidity": 1e9}).json()["total"] == 0
    assert auth_client.get(f"{API}/tokens", params={"sort": "bogus"}).status_code == 422

    # Detalhe
    d = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()
    assert d["token"]["address"] == SOL_MINT
    assert d["analysis"]["risk_factors"] and d["technical_checks"]["supported"] is True
    assert d["exit_estimate"]["pool_model"] == "constant_product" and d["exit_estimate"]["available"]
    assert d["wallet_intelligence"]["status"] == "not_implemented"
    assert d["freshness"]["observed_at"].endswith("Z")

    # Histórico e saída
    h = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/history", params={"range": "1h"}).json()
    assert len(h["points"]) == 1
    e = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-estimate", params={"positions": "1000,2000"}).json()
    assert [s["position_usd"] for s in e["scenarios"]] == [1000, 2000]
    assert auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-estimate", params={"positions": "abc"}).status_code == 422
    assert auth_client.get(f"{API}/tokens/solana/NaoExiste1111111111111111").status_code == 404

    # Alertas: link leva ao token correto; mudança de estado persiste.
    alerts = auth_client.get(f"{API}/alerts", params={"status": ["open"]}).json()
    assert alerts["total"] >= 1
    first = alerts["items"][0]
    assert first["link"] == f"/tokens/solana/{SOL_MINT}"
    r = auth_client.patch(f"{API}/alerts/{first['id']}", json={"status": "acknowledged"})
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert auth_client.patch(f"{API}/alerts/{first['id']}", json={"status": "bogus"}).status_code == 422

    # Dashboard, previsões, sistema, meta
    s = auth_client.get(f"{API}/dashboard/summary").json()
    assert s["tokens_tracked"] == 1 and s["aggregate_liquidity_usd"] == 318553.22
    assert s["predictions"]["pending"] == 2
    p = auth_client.get(f"{API}/predictions").json()
    assert p["total"] == 2 and p["items"][0]["calibrated"] is False
    m = auth_client.get(f"{API}/predictions/metrics").json()
    assert {x["target"] for x in m} == {"up_20pct_6h", "down_30pct_6h"} and m[0]["evaluated"] == 0
    assert auth_client.get(f"{API}/system/sources").json()["sources"][0]["status"] == "ok"
    assert "opportunity_score" in auth_client.get(f"{API}/meta").json()["token_sort_fields"]

    # Deixar de monitorar
    assert auth_client.delete(f"{API}/tokens/solana/{SOL_MINT}/track").status_code == 204
    assert auth_client.get(f"{API}/tokens").json()["total"] == 0


def test_track_unknown_token_returns_404(auth_client, fake_dex):
    r = auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": "Unknown11111111111111111111111111111111111"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found_on_source"


def test_track_when_source_down_returns_502(auth_client, fake_dex):
    fake_dex.fail = True
    r = auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    assert r.status_code == 502 and r.json()["error"]["code"] == "source_error"


def test_stale_data_is_flagged(auth_client, fake_dex, db):
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    snap = db.scalars(select(PairSnapshot)).first()
    snap.received_at = utcnow() - timedelta(hours=2)
    db.scalars(select(Token)).first().last_refreshed_at = utcnow() - timedelta(hours=2)  # nem conferido na fonte
    db.commit()
    item = auth_client.get(f"{API}/tokens").json()["items"][0]
    assert item["freshness"]["status"] == "stale"
    s = auth_client.get(f"{API}/dashboard/summary").json()
    assert s["tokens_with_fresh_data"] == 0 and s["aggregate_liquidity_usd"] is None


def test_analysis_persistence_throttled(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    assert analyze_token(db, token, force=True) is not None
    assert analyze_token(db, token) is None  # sem mudança relevante em < 5 min
    assert len(db.scalars(select(Analysis)).all()) == 1
