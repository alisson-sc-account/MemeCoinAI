"""Features temporalmente válidas.

`compute_features(snapshots, pair_created_at, as_of)` usa SOMENTE snapshots com
received_at <= as_of. Isso é o que permite reavaliar o passado sem vazamento.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

FEATURE_VERSION = "f-1"


@dataclass
class SnapshotView:
    """Subconjunto de PairSnapshot usado pelo motor (facilita testes)."""

    received_at: datetime
    price_usd: float | None = None
    liquidity_usd: float | None = None
    liquidity_base: float | None = None
    liquidity_quote: float | None = None
    market_cap: float | None = None
    fdv: float | None = None
    volume_m5: float | None = None
    volume_h1: float | None = None
    volume_h6: float | None = None
    volume_h24: float | None = None
    buys_m5: int | None = None
    sells_m5: int | None = None
    buys_h1: int | None = None
    sells_h1: int | None = None
    buys_h6: int | None = None
    sells_h6: int | None = None
    buys_h24: int | None = None
    sells_h24: int | None = None
    price_change_m5: float | None = None
    price_change_h1: float | None = None
    price_change_h6: float | None = None
    price_change_h24: float | None = None

    @classmethod
    def from_model(cls, s) -> "SnapshotView":
        return cls(**{f: getattr(s, f) for f in cls.__dataclass_fields__})


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return a / b


def _sum(a: int | None, b: int | None) -> int | None:
    if a is None or b is None:
        return None
    return a + b


def compute_features(
    snapshots: list[SnapshotView], pair_created_at: datetime | None, as_of: datetime
) -> dict:
    valid = sorted((s for s in snapshots if s.received_at <= as_of), key=lambda s: s.received_at)
    if not valid:
        return {"available": False, "as_of": as_of.isoformat(), "feature_version": FEATURE_VERSION}
    cur = valid[-1]
    txns_h1 = _sum(cur.buys_h1, cur.sells_h1)
    txns_h6 = _sum(cur.buys_h6, cur.sells_h6)
    txns_m5 = _sum(cur.buys_m5, cur.sells_m5)

    window_start = as_of - timedelta(hours=1)
    prior_hour = [s for s in valid[:-1] if s.received_at >= window_start and s.liquidity_usd is not None]
    liq_max_1h = max((s.liquidity_usd for s in prior_hour), default=None)
    liq_change_1h = (
        (cur.liquidity_usd - liq_max_1h) / liq_max_1h
        if cur.liquidity_usd is not None and liq_max_1h and liq_max_1h > 0
        else None
    )
    oldest_prior = prior_hour[0] if prior_hour else None
    liq_trend_1h = (
        (cur.liquidity_usd - oldest_prior.liquidity_usd) / oldest_prior.liquidity_usd
        if oldest_prior and cur.liquidity_usd is not None and oldest_prior.liquidity_usd > 0
        else None
    )
    mcap = cur.market_cap if cur.market_cap is not None else cur.fdv

    return {
        "available": True,
        "feature_version": FEATURE_VERSION,
        "as_of": as_of.isoformat(),
        "observed_at": cur.received_at.isoformat(),
        "data_age_seconds": (as_of - cur.received_at).total_seconds(),
        "price_usd": cur.price_usd,
        "liquidity_usd": cur.liquidity_usd,
        "liquidity_base": cur.liquidity_base,
        "liquidity_quote": cur.liquidity_quote,
        "market_cap": mcap,
        "volume_m5": cur.volume_m5,
        "volume_h1": cur.volume_h1,
        "volume_h6": cur.volume_h6,
        "volume_h24": cur.volume_h24,
        "buys_h1": cur.buys_h1,
        "sells_h1": cur.sells_h1,
        "txns_m5": txns_m5,
        "txns_h1": txns_h1,
        "txns_h6": txns_h6,
        "price_change_m5": cur.price_change_m5,
        "price_change_h1": cur.price_change_h1,
        "price_change_h6": cur.price_change_h6,
        "price_change_h24": cur.price_change_h24,
        "pair_age_hours": (as_of - pair_created_at).total_seconds() / 3600 if pair_created_at else None,
        # >1 indica aceleração em relação à média horária das últimas 6h.
        "volume_accel_h1": _ratio(cur.volume_h1, cur.volume_h6 / 6 if cur.volume_h6 is not None else None),
        "volume_accel_m5": _ratio(cur.volume_m5, cur.volume_h1 / 12 if cur.volume_h1 is not None else None),
        "txn_accel_h1": _ratio(txns_h1, txns_h6 / 6 if txns_h6 is not None else None),
        "buy_ratio_h1": _ratio(cur.buys_h1, txns_h1) if txns_h1 else None,
        "avg_trade_usd_h1": _ratio(cur.volume_h1, txns_h1),
        "liquidity_to_mcap": _ratio(cur.liquidity_usd, mcap),
        "volume_h24_to_liquidity": _ratio(cur.volume_h24, cur.liquidity_usd),
        "liquidity_max_prior_1h": liq_max_1h,
        "liquidity_change_vs_max_1h": liq_change_1h,
        "liquidity_trend_1h": liq_trend_1h,
        "history_points": len(valid),
        "history_points_1h": len(prior_hour) + 1,
        "history_span_minutes": (cur.received_at - valid[0].received_at).total_seconds() / 60,
    }
