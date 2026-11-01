"""Detector de disparo em andamento (`burst-1`).

Isto **não prevê** que um token vai subir: detecta que uma arrancada já está
acontecendo agora, na janela de 5 minutos (volume muito acima do ritmo da
última hora, compradores dominando, preço já se movendo), e mostra o que
aconteceu historicamente nos 15 minutos seguintes a padrões iguais.

Limites honestos: a fonte gratuita atualiza a cada ~30-60 s e pode atrasar até
~60 s, então o disparo é visto com algum atraso; parte do movimento pode já ter
ocorrido. Um disparo detectado frequentemente se desfaz (falso positivo).
"""
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Analysis, AnalysisOutcome

RULES_VERSION = "burst-1"

MIN_LIQUIDITY_USD = 5_000
MIN_VOLUME_ACCEL_M5 = 4.0
MIN_PRICE_CHANGE_M5 = 2.0
MIN_TXNS_M5 = 8
MIN_BUY_SHARE_M5 = 0.65
# Alta já enorme na última hora: entrada tardia, não sinalizamos como disparo novo.
MAX_PRICE_CHANGE_H1 = 300.0

EXTREME_ACCEL = 10.0
EXTREME_PRICE_CHANGE_M5 = 8.0

_STATS_TTL = 120.0
_stats_cache: tuple[float, dict] | None = None


def detect(f: dict) -> dict | None:
    """Retorna {strength, reasons, evidence} se um disparo está em andamento."""
    if not f.get("available"):
        return None
    liq = f.get("liquidity_usd")
    accel = f.get("volume_accel_m5")
    chg5 = f.get("price_change_m5")
    txns = f.get("txns_m5")
    buys, sells = f.get("buys_m5"), f.get("sells_m5")
    if liq is None or liq < MIN_LIQUIDITY_USD:
        return None
    if accel is None or accel < MIN_VOLUME_ACCEL_M5:
        return None
    if chg5 is None or chg5 < MIN_PRICE_CHANGE_M5:
        return None
    if txns is None or txns < MIN_TXNS_M5:
        return None
    if buys is None or sells is None or buys / max(1, buys + sells) < MIN_BUY_SHARE_M5:
        return None
    chg1h = f.get("price_change_h1")
    if chg1h is not None and chg1h > MAX_PRICE_CHANGE_H1:
        return None

    extreme = accel >= EXTREME_ACCEL and chg5 >= EXTREME_PRICE_CHANGE_M5
    return {
        "strength": "extreme" if extreme else "strong",
        "reasons": [
            f"Volume dos últimos 5 min {accel:.1f}x o ritmo da última hora",
            f"Preço subiu {chg5:.1f}% em 5 min",
            f"{buys} compras contra {sells} vendas em 5 min",
            f"Liquidez de US$ {liq:,.0f}".replace(",", "."),
        ],
        "evidence": {
            "volume_accel_m5": round(accel, 2), "price_change_m5": chg5, "buys_m5": buys, "sells_m5": sells,
            "liquidity_usd": liq, "volume_m5": f.get("volume_m5"), "price_change_h1": chg1h,
            "rules_version": RULES_VERSION,
        },
    }


def _features_of(f: dict) -> dict:
    """Mantém só o que `detect` usa (as features salvas podem crescer)."""
    keys = ("available", "liquidity_usd", "volume_accel_m5", "price_change_m5", "txns_m5",
            "buys_m5", "sells_m5", "price_change_h1", "volume_m5")
    return {k: f.get(k) for k in keys}


def pattern_stats(db: Session, as_of: datetime | None = None, lookback_days: int = 7, limit: int = 4000) -> dict:
    """O que aconteceu nos 15 min seguintes a disparos já medidos.

    Usa apenas rótulos cujo horizonte terminou antes de `as_of` (sem vazamento).
    """
    global _stats_cache
    as_of = as_of or utcnow()
    if _stats_cache and time.monotonic() - _stats_cache[0] < _STATS_TTL:
        return _stats_cache[1]

    rows = db.execute(
        select(Analysis.features, AnalysisOutcome.max_return, AnalysisOutcome.end_return)
        .join(AnalysisOutcome, AnalysisOutcome.analysis_id == Analysis.id)
        .where(
            AnalysisOutcome.horizon_seconds == 900,
            AnalysisOutcome.status == "ok",
            AnalysisOutcome.analysis_time <= as_of - timedelta(seconds=900),
            AnalysisOutcome.analysis_time >= as_of - timedelta(days=lookback_days),
        )
        .limit(limit)
    ).all()
    hits = [(mx, end) for feats, mx, end in rows if feats and detect(_features_of(feats))]
    n = len(hits)
    if n == 0:
        stats = {"n": 0, "sample_total": len(rows), "horizon": "15m", "rules_version": RULES_VERSION}
    else:
        maxs = sorted(h[0] for h in hits)
        stats = {
            "n": n,
            "sample_total": len(rows),
            "horizon": "15m",
            "rules_version": RULES_VERSION,
            "p_up_10": round(sum(1 for mx, _ in hits if mx >= 0.10) / n, 4),
            "p_up_20": round(sum(1 for mx, _ in hits if mx >= 0.20) / n, 4),
            "p_up_50": round(sum(1 for mx, _ in hits if mx >= 0.50) / n, 4),
            "median_max_return": round(maxs[n // 2], 4),
            "p_end_positive": round(sum(1 for _, end in hits if end > 0) / n, 4),
        }
    _stats_cache = (time.monotonic(), stats)
    return stats


def clear_cache() -> None:
    global _stats_cache
    _stats_cache = None
