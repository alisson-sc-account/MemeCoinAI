from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.engine.checks import parse_largest_accounts, parse_mint_account
from app.engine.features import SnapshotView, compute_features
from app.engine.scoring import score_opportunity, score_risk
from app.engine.slippage import estimate_exit, pool_model
from app.ingest.normalize import NormalizationError, normalize_address, normalize_pair
from app.sources.http import ResilientClient
from tests.conftest import make_pair

T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


# ---------------- Normalização ----------------
def test_normalize_parses_strings_and_timestamps():
    np = normalize_pair(make_pair())
    assert np.metrics["price_usd"] == pytest.approx(0.000003187)
    assert np.metrics["buys_h1"] == 192
    assert np.pair_created_at == datetime.fromtimestamp(1671980424, tz=UTC)
    assert np.missing_fields == []
    assert np.base_address == "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"  # Solana: case preservado


def test_normalize_missing_is_none_not_zero():
    raw = make_pair()
    del raw["liquidity"]
    raw["volume"] = {"h24": 10}
    np = normalize_pair(raw)
    assert np.metrics["liquidity_usd"] is None
    assert np.metrics["volume_h1"] is None
    assert "liquidity_usd" in np.missing_fields and "volume_h1" in np.missing_fields


def test_normalize_rejects_incomplete_identity():
    raw = make_pair()
    raw["baseToken"] = {"symbol": "X"}
    with pytest.raises(NormalizationError):
        normalize_pair(raw)


def test_evm_addresses_lowercased_solana_preserved():
    assert normalize_address("ethereum", "0xAbC") == "0xabc"
    assert normalize_address("solana", "AbC") == "AbC"


def test_same_ticker_different_address_are_distinct():
    a = normalize_pair(make_pair(baseToken={"address": "Mint111111111111111111111111111111111111111", "symbol": "PEPE"}))
    b = normalize_pair(make_pair(baseToken={"address": "Mint222222222222222222222222222222222222222", "symbol": "PEPE"}))
    assert (a.chain_id, a.base_address) != (b.chain_id, b.base_address)


# ---------------- Features (vazamento temporal) ----------------
def _snap(minutes, **kw):
    base = dict(price_usd=1.0, liquidity_usd=100_000, volume_h1=1000, volume_h6=6000, buys_h1=60, sells_h1=40,
                buys_h6=300, sells_h6=300, market_cap=1_000_000)
    base.update(kw)
    return SnapshotView(received_at=T0 + timedelta(minutes=minutes), **base)


def test_features_ignore_future_snapshots():
    snaps = [_snap(0), _snap(30), _snap(60, liquidity_usd=10)]  # snapshot futuro com liquidez ~0
    f = compute_features(snaps, T0 - timedelta(days=1), as_of=T0 + timedelta(minutes=45))
    assert f["liquidity_usd"] == 100_000
    assert f["history_points"] == 2
    assert f["observed_at"] == (T0 + timedelta(minutes=30)).isoformat()


def test_features_liquidity_change_and_ratios():
    snaps = [_snap(0, liquidity_usd=100_000), _snap(30, liquidity_usd=50_000)]
    f = compute_features(snaps, T0 - timedelta(hours=2), as_of=T0 + timedelta(minutes=30))
    assert f["liquidity_change_vs_max_1h"] == pytest.approx(-0.5)
    assert f["volume_accel_h1"] == pytest.approx(1.0)
    assert f["buy_ratio_h1"] == pytest.approx(0.6)
    assert f["pair_age_hours"] == pytest.approx(2.5)


def test_features_empty():
    assert compute_features([], None, T0)["available"] is False


# ---------------- Scores ----------------
def test_missing_data_does_not_mean_low_risk():
    r = score_risk({"available": False}, None, None, "solana")
    assert r.score >= 50
    assert r.insufficient_data
    assert {c["check"] for c in r.checks_not_performed} >= {"market_data", "mint_authorities"}


def test_unsupported_chain_flags_unchecked():
    f = compute_features([_snap(0)], T0 - timedelta(days=30), T0)
    r = score_risk(f, None, None, "ethereum")
    assert any(x.id == "D3_technical_unchecked" for x in r.factors)


def test_mint_authority_and_liquidity_drop_raise_risk():
    snaps = [_snap(0, liquidity_usd=100_000), _snap(30, liquidity_usd=30_000)]
    f = compute_features(snaps, T0 - timedelta(days=3), T0 + timedelta(minutes=30))
    mint = {"status": "flagged", "result": {"mint_authority": "Auth1", "freeze_authority": None, "risky_extensions": []}, "checked_at": T0.isoformat()}
    holders = {"status": "ok", "result": {"top10_share": 0.2, "top1_share": 0.05}, "checked_at": T0.isoformat()}
    r = score_risk(f, mint, holders, "solana")
    ids = {x.id for x in r.factors}
    assert "T1_mint_authority" in ids and "L2_liquidity_drop_severe" in ids
    assert r.level in ("high", "critical")
    assert r.coverage == 1.0


def test_opportunity_capped_for_shallow_pool_and_penalized_by_risk():
    snaps = [_snap(0, liquidity_usd=8_000), _snap(30, liquidity_usd=8_000, volume_h1=5000, buys_h1=90, sells_h1=10, price_change_h1=25)]
    f = compute_features(snaps, T0 - timedelta(days=3), T0 + timedelta(minutes=30))
    mint = {"status": "ok", "result": {"mint_authority": None, "freeze_authority": None, "risky_extensions": []}, "checked_at": T0.isoformat()}
    holders = {"status": "ok", "result": {"top10_share": 0.2}, "checked_at": T0.isoformat()}
    r = score_risk(f, mint, holders, "solana")
    o = score_opportunity(f, r)
    assert o.score <= 30
    assert any(x.id == "P2_shallow_pool_cap" for x in o.factors) or o.raw_score <= 30


# ---------------- Slippage ----------------
def test_constant_product_exit():
    est = estimate_exit("raydium", ["CPMM"], price_usd=1.0, liquidity_base=1000, liquidity_quote=1000,
                        liquidity_usd=2000, positions_usd=(100,))
    sc = est["scenarios"][0]
    # vender 100 tokens num pool 1000/1000: impacto = 100/1100
    assert sc["price_impact"] == pytest.approx(100 / 1100, rel=1e-5)
    assert sc["estimated_received_usd"] == pytest.approx(100 * 1000 / 1100, rel=1e-4)
    assert est["fees_included"] is False


@pytest.mark.parametrize("dex,labels,model", [
    ("raydium", ["CLMM"], "concentrated"), ("orca", ["wp"], "concentrated"), ("meteora", ["DLMM"], "concentrated"),
    ("pumpfun", [], "bonding_curve"), ("meteora", ["DYN2"], "unsupported"), ("pumpswap", [], "constant_product"),
    ("raydium", [], "constant_product"), ("somedex", [], "unknown"),
])
def test_pool_model_mapping(dex, labels, model):
    assert pool_model(dex, labels)[0] == model


def test_non_constant_product_has_no_estimate():
    est = estimate_exit("raydium", ["CLMM"], 1.0, 1000, 1000, 2000)
    assert est["available"] is False and est["scenarios"] == []


# ---------------- HTTP resiliente ----------------
def test_retry_on_429_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json={"ok": 1})

    c = ResilientClient("https://x.invalid", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    r = c.request("GET", "/")
    assert r.ok and r.attempts == 2 and r.rate_limited


def test_gives_up_after_max_attempts_and_no_retry_on_404():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500 if req.url.path == "/err" else 404)

    c = ResilientClient("https://x.invalid", transport=httpx.MockTransport(handler), max_attempts=3, sleep=lambda s: None)
    r = c.request("GET", "/err")
    assert not r.ok and calls["n"] == 3
    calls["n"] = 0
    r = c.request("GET", "/missing")
    assert not r.ok and r.status_code == 404 and calls["n"] == 1


def test_network_error_is_reported():
    def handler(req):
        raise httpx.ConnectError("boom")

    c = ResilientClient("https://x.invalid", transport=httpx.MockTransport(handler), max_attempts=2, sleep=lambda s: None)
    r = c.request("GET", "/")
    assert not r.ok and "ConnectError" in r.error


# ---------------- Verificações Solana ----------------
def test_parse_mint_account_real_shape():
    value = {  # formato real observado (BONK, 2026-10-28)
        "data": {"parsed": {"info": {"decimals": 5, "freezeAuthority": None, "isInitialized": True,
                                     "mintAuthority": None, "supply": "8799430975477737620"}, "type": "mint"},
                 "program": "spl-token", "space": 82},
        "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    }
    status, r = parse_mint_account(value)
    assert status == "ok" and r["program"] == "spl-token" and r["mint_authority"] is None


def test_parse_token2022_risky_extensions():
    value = {
        "owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "data": {"parsed": {"type": "mint", "info": {
            "decimals": 6, "supply": "1000", "mintAuthority": None, "freezeAuthority": "F1",
            "extensions": [
                {"extension": "permanentDelegate", "state": {"delegate": "D1"}},
                {"extension": "defaultAccountState", "state": {"accountState": "initialized"}},
                {"extension": "metadataPointer", "state": {}},
            ]}}},
    }
    status, r = parse_mint_account(value)
    assert status == "flagged"
    assert [e["extension"] for e in r["risky_extensions"]] == ["permanentDelegate"]


def test_parse_largest_accounts_shares():
    accounts = [{"address": "A", "uiAmountString": "500"}, {"address": "B", "uiAmountString": "300"}]
    status, r = parse_largest_accounts(accounts, "100000", 2)  # supply = 1000
    assert r["top1_share"] == 0.5 and r["top10_share"] == 0.8 and status == "flagged"
