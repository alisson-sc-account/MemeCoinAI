"""Detector de disparo, descoberta ampliada e limpeza de tokens sem vida."""
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import utcnow
from app.engine import burst
from app.engine.pipeline import analyze_token
from app.ingest.service import discover, prune_inactive, refresh_tracked, track_token
from app.models import Alert, Analysis, AnalysisOutcome, Position, Token, User
from tests.conftest import SOL_MINT, make_pair

API = "/api/v1"


def _burst_features(**over):
    f = {"available": True, "liquidity_usd": 50_000, "volume_accel_m5": 6.0, "price_change_m5": 5.0,
         "txns_m5": 20, "buys_m5": 16, "sells_m5": 4, "price_change_h1": 20.0, "volume_m5": 9000}
    f.update(over)
    return f


# ---------------- Regras do disparo ----------------
def test_detects_burst_and_extreme():
    d = burst.detect(_burst_features())
    assert d and d["strength"] == "strong" and len(d["reasons"]) == 4
    assert burst.detect(_burst_features(volume_accel_m5=12, price_change_m5=10))["strength"] == "extreme"


def test_burst_requires_every_condition():
    assert burst.detect(_burst_features(liquidity_usd=1_000)) is None          # pool raso demais
    assert burst.detect(_burst_features(volume_accel_m5=2)) is None            # volume normal
    assert burst.detect(_burst_features(price_change_m5=0.5)) is None          # preço parado
    assert burst.detect(_burst_features(txns_m5=3)) is None                    # poucas transações
    assert burst.detect(_burst_features(buys_m5=10, sells_m5=10)) is None      # vendas equilibram
    assert burst.detect(_burst_features(price_change_h1=500)) is None          # alta já enorme
    assert burst.detect({"available": False}) is None


def test_burst_ignores_missing_fields():
    assert burst.detect(_burst_features(volume_accel_m5=None)) is None
    assert burst.detect(_burst_features(buys_m5=None)) is None


def test_pattern_stats_uses_only_closed_horizons(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    now = utcnow()
    burst.clear_cache()
    assert burst.pattern_stats(db, now)["n"] == 0
    for i in range(10):
        a = Analysis(token_id=token.id, pair_id=token.primary_pair_id, computed_at=now - timedelta(hours=1, minutes=i),
                     engine_version="t", risk_score=20, risk_level="low", risk_confidence=1, opportunity_score=70,
                     opportunity_confidence=1, risk_factors=[], opportunity_factors=[], checks_not_performed=[],
                     data_quality={}, features=_burst_features(), invalidation_conditions=[])
        db.add(a)
        db.flush()
        db.add(AnalysisOutcome(analysis_id=a.id, token_id=token.id, horizon_seconds=900, analysis_time=a.computed_at,
                               opportunity_score=70, risk_score=20, status="ok",
                               max_return=0.25 if i < 4 else 0.02, min_return=-0.03, end_return=0.1 if i < 4 else -0.01))
    db.commit()
    burst.clear_cache()
    s = burst.pattern_stats(db, now)
    assert s["n"] == 10 and s["p_up_20"] == 0.4 and s["p_end_positive"] == 0.4
    burst.clear_cache()
    assert burst.pattern_stats(db, now - timedelta(days=1))["n"] == 0  # antes de existirem


def test_burst_generates_alert_with_stats(db, fake_dex):
    burst.clear_cache()
    fake_dex.pairs = [make_pair(volume={"m5": 9000, "h1": 18000, "h6": 100000, "h24": 200000},
                                txns={"m5": {"buys": 18, "sells": 3}, "h1": {"buys": 100, "sells": 80},
                                      "h6": {"buys": 500, "sells": 500}, "h24": {"buys": 900, "sells": 900}},
                                priceChange={"m5": 7.0, "h1": 20.0, "h6": 30.0, "h24": 40.0})]
    token, _ = track_token(db, "solana", SOL_MINT)
    analyze_token(db, token, force=True)
    a = db.scalar(select(Alert).where(Alert.alert_type == "pump_burst"))
    assert a is not None and a.severity in ("high", "critical") and a.category == "opportunity"
    assert a.evidence["volume_accel_m5"] >= 4 and "pattern_stats" in a.evidence
    assert "5 min" in a.reason


def test_burst_alert_resolves_when_it_ends(db, fake_dex):
    burst.clear_cache()
    fake_dex.pairs = [make_pair(volume={"m5": 9000, "h1": 18000, "h6": 100000, "h24": 200000},
                                txns={"m5": {"buys": 18, "sells": 3}, "h1": {"buys": 100, "sells": 80},
                                      "h6": {"buys": 500, "sells": 500}, "h24": {"buys": 900, "sells": 900}},
                                priceChange={"m5": 7.0, "h1": 20.0, "h6": 30.0, "h24": 40.0})]
    token, _ = track_token(db, "solana", SOL_MINT)
    analyze_token(db, token, force=True)
    alert = db.scalar(select(Alert).where(Alert.alert_type == "pump_burst"))
    fake_dex.pairs = [make_pair()]  # volume volta ao normal
    refresh_tracked(db, fake_dex.client())
    analyze_token(db, token, force=True)
    db.refresh(alert)
    assert alert.status == "resolved"


def test_api_lists_burst_alerts(auth_client, fake_dex):
    burst.clear_cache()
    fake_dex.pairs = [make_pair(volume={"m5": 9000, "h1": 18000, "h6": 100000, "h24": 200000},
                                txns={"m5": {"buys": 18, "sells": 3}, "h1": {"buys": 100, "sells": 80},
                                      "h6": {"buys": 500, "sells": 500}, "h24": {"buys": 900, "sells": 900}},
                                priceChange={"m5": 7.0, "h1": 20.0, "h6": 30.0, "h24": 40.0})]
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    r = auth_client.get(f"{API}/alerts", params={"alert_type": "pump_burst", "status": "open"}).json()
    assert r["total"] == 1 and r["items"][0]["link"] == f"/tokens/solana/{SOL_MINT}"


# ---------------- Descoberta ampliada ----------------
def test_discover_uses_profiles_boosts_and_searches(db, fake_dex, monkeypatch):
    calls: list[str] = []

    def handler(request):
        import httpx

        path = request.url.path
        calls.append(path)
        if path.startswith("/token-profiles"):
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": "Prof1111111111111111111111111111111111111"}])
        if path == "/token-boosts/latest/v1":
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": "Boost111111111111111111111111111111111111"}])
        if path == "/token-boosts/top/v1":
            return httpx.Response(200, json=[{"chainId": "solana", "tokenAddress": "Top11111111111111111111111111111111111111"},
                                             {"chainId": "ethereum", "tokenAddress": "0xAbC"}])
        if path == "/latest/dex/search":
            q = request.url.params.get("q")
            return httpx.Response(200, json={"pairs": [make_pair(baseToken={"address": f"Search{q}11111111111111111111111111", "symbol": q})]})
        return httpx.Response(404, json={})

    fake_dex.handler = handler
    added = discover(db, fake_dex.client())
    vias = {t.discovered_via for t in added}
    assert vias == {"dexscreener_profiles", "dexscreener_boosts", "dexscreener_boosts_top", "dexscreener_search"}
    assert all(t.chain_id == "solana" for t in added)  # rede fora de CHAINS é ignorada
    assert sum(1 for t in added if t.discovered_via == "dexscreener_search") == get_settings().discovery_queries_per_cycle
    assert len([c for c in calls if c == "/latest/dex/search"]) == get_settings().discovery_queries_per_cycle


def test_discover_respects_capacity(db, fake_dex, monkeypatch):
    monkeypatch.setenv("MAX_TRACKED_TOKENS", "1")
    get_settings.cache_clear()
    track_token(db, "solana", SOL_MINT)
    assert discover(db, fake_dex.client()) == []
    get_settings.cache_clear()


# ---------------- Limpeza ----------------
def test_prune_drops_dead_tokens_only(db, fake_dex):
    old = utcnow() - timedelta(hours=5)
    dead = Token(chain_id="solana", address="Dead1111111111111111111111111111111111111", discovered_via="dexscreener_search", first_seen_at=old)
    manual = Token(chain_id="solana", address="Manual11111111111111111111111111111111111", discovered_via="watchlist", first_seen_at=old)
    recent = Token(chain_id="solana", address="New11111111111111111111111111111111111111", discovered_via="dexscreener_search", first_seen_at=utcnow())
    db.add_all([dead, manual, recent])
    db.commit()
    assert prune_inactive(db) == 1
    db.refresh(dead); db.refresh(manual); db.refresh(recent)
    assert dead.is_tracked is False and manual.is_tracked is True and recent.is_tracked is True


def test_prune_keeps_liquid_tokens_and_positions(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)  # liquidez de US$ 318 mil
    token.first_seen_at = utcnow() - timedelta(hours=5)
    token.discovered_via = "dexscreener_search"
    db.commit()
    assert prune_inactive(db) == 0

    fake_dex.pairs = [make_pair(liquidity={"usd": 100.0, "base": 1.0, "quote": 1.0}, volume={"m5": 0, "h1": 0, "h6": 0, "h24": 10.0})]
    refresh_tracked(db, fake_dex.client())
    user = User(username="dono", password_hash="x", must_change_password=False)
    db.add(user)
    db.flush()
    db.add(Position(user_id=user.id, token_id=token.id, quantity=1.0))
    db.commit()
    assert prune_inactive(db) == 0  # posição registrada protege o token
    db.query(Position).delete()
    db.commit()
    assert prune_inactive(db) == 1


def test_geckoterminal_discovery_skips_low_liquidity(db, fake_dex, monkeypatch):
    import app.ingest.service as svc
    from app.sources.http import FetchResult

    def pool(mint, liq):
        return {"attributes": {"reserve_in_usd": str(liq)}, "relationships": {"base_token": {"data": {"id": f"solana_{mint}"}}}}

    class Gecko:
        def pools(self, network, kind, page):
            return FetchResult(ok=True, data=[pool("Good111111111111111111111111111111111111111", 50_000),
                                              pool("Poor111111111111111111111111111111111111111", 50), {"x": 1}] if page == 1 else [])

    monkeypatch.setattr(svc, "GeckoTerminalClient", Gecko)
    added = svc.discover(db)
    assert [t.address[:4] for t in added if t.discovered_via.startswith("geckoterminal")] == ["Good"]


def test_raw_retention_keeps_normalized_data(db, fake_dex):
    from datetime import timedelta

    from app.db import utcnow
    from app.ingest.service import apply_raw_retention, track_token
    from app.models import PairSnapshot
    from tests.conftest import SOL_MINT

    track_token(db, "solana", SOL_MINT)
    snap = db.query(PairSnapshot).one()
    assert apply_raw_retention(db) == 0 and snap.raw is not None
    snap.received_at = utcnow() - timedelta(days=2)
    db.commit()
    assert apply_raw_retention(db) == 1
    db.refresh(snap)
    assert snap.raw is None and snap.price_usd is not None


def test_refresh_priority_with_more_tokens_than_budget(db, fake_dex, monkeypatch):
    from datetime import timedelta

    from app import config
    from app.db import utcnow
    from app.ingest import service as svc
    from app.models import Signal, Token

    monkeypatch.setenv("REFRESH_REQUESTS_PER_CYCLE", "1")  # 30 tokens por ciclo
    monkeypatch.setenv("REFRESH_HOT_TOKENS", "10")
    config.get_settings.cache_clear()
    old = utcnow() - timedelta(hours=1)
    tokens = [Token(chain_id="solana", address=f"T{i:03d}" + "1" * 40, discovered_via="test", first_seen_at=old, heat=float(i), last_refreshed_at=old + timedelta(seconds=i))
              for i in range(100)]
    db.add_all(tokens)
    db.commit()
    db.add(Signal(token_id=tokens[0].id, action="buy", strength="strong", status="active", headline="c", reasons=[], risk_score=1,
                  risk_level="low", opportunity_score=70, estimates=[], rules_version="sig-1"))
    db.commit()
    chosen = svc._refresh_selection(db)
    heats = [t.heat for t in chosen]
    assert len(chosen) == 30 and heats[0] == 0.0  # com sinal vem primeiro, mesmo frio
    assert heats[1:10] == [99.0 - i for i in range(9)]  # depois os mais quentes
    assert heats[10:12] == [1.0, 2.0]  # e o rodízio pega os atualizados há mais tempo


def test_snapshot_retention_keeps_recent(db, fake_dex):
    from datetime import timedelta

    from app.db import utcnow
    from app.ingest.service import apply_snapshot_retention, track_token
    from app.models import PairSnapshot
    from tests.conftest import SOL_MINT

    track_token(db, "solana", SOL_MINT)
    assert apply_snapshot_retention(db) == 0
    db.query(PairSnapshot).one().received_at = utcnow() - timedelta(days=200)
    db.commit()
    assert apply_snapshot_retention(db) == 1 and db.query(PairSnapshot).count() == 0
