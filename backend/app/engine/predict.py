"""Previsões probabilísticas + avaliação posterior + métricas.

Estado honesto (2026-10-28): o modelo `heuristic-logit` usa coeficientes
escolhidos a priori, NÃO calibrados. `calibrated=False` em toda previsão.
A baseline é a taxa-base empírica do alvo, calculada apenas com previsões
já avaliadas ANTES do instante da nova previsão (sem vazamento).

Alvos (ver ANALYSIS_ENGINE.md):
- up_20pct_6h:   preço máximo observado em (t, t+6h] >= preço_ref * 1.20
- down_30pct_6h: preço mínimo observado em (t, t+6h] <= preço_ref * 0.70
O preço observado vem dos snapshots coletados (~60 s); picos entre coletas
podem não ser vistos. Custos/slippage não entram no alvo (é bruto).
"""
import math
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import PairSnapshot, Prediction

MODEL_ID = "heuristic-logit"
MODEL_VERSION = "1"
MIN_LIQUIDITY_FOR_PREDICTION = 5_000
MIN_BASELINE_SAMPLES = 20
MIN_OBSERVATIONS = 3
# A última observação precisa estar a no máximo isto antes do fim do horizonte.
MAX_END_GAP = timedelta(minutes=30)

TARGETS = {
    "up_20pct_6h": {"horizon": timedelta(hours=6), "threshold": 0.20, "direction": "up",
                    "coef": {"intercept": -2.2, "opportunity": 2.5, "risk": -0.8}},
    "down_30pct_6h": {"horizon": timedelta(hours=6), "threshold": -0.30, "direction": "down",
                      "coef": {"intercept": -2.0, "opportunity": 0.0, "risk": 2.4}},
}


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def heuristic_probability(target: str, opportunity_score: float, risk_score: float) -> float:
    c = TARGETS[target]["coef"]
    z = c["intercept"] + c["opportunity"] * opportunity_score / 100 + c["risk"] * risk_score / 100
    return round(_sigmoid(z), 4)


def baseline_probability(db: Session, target: str, as_of) -> float | None:
    """Taxa-base com suavização de Laplace usando só resultados conhecidos em `as_of`."""
    rows = db.execute(
        select(func.count(), func.sum(case((Prediction.outcome.is_(True), 1), else_=0)))
        .where(Prediction.target == target, Prediction.status == "evaluated", Prediction.evaluated_at <= as_of)
    ).one()
    n = rows[0] or 0
    if n < MIN_BASELINE_SAMPLES:
        return None
    hits = int(rows[1] or 0)
    return round((hits + 1) / (n + 2), 4)


def maybe_create_predictions(db: Session, token_id: int, pair_id: int, analysis, features: dict, snapshot_id: int | None) -> list[Prediction]:
    price = features.get("price_usd")
    liq = features.get("liquidity_usd")
    if not features.get("available") or not price or liq is None or liq < MIN_LIQUIDITY_FOR_PREDICTION:
        return []
    now = analysis.computed_at
    created = []
    for target, spec in TARGETS.items():
        # No máximo uma previsão por alvo por token a cada meio horizonte
        # (reduz previsões altamente correlacionadas).
        recent = db.scalar(
            select(Prediction.id).where(
                Prediction.token_id == token_id, Prediction.target == target,
                Prediction.created_at > now - spec["horizon"] / 2,
            ).limit(1)
        )
        if recent:
            continue
        p = Prediction(
            token_id=token_id, pair_id=pair_id, analysis_id=analysis.id, created_at=now,
            model_id=MODEL_ID, model_version=MODEL_VERSION, target=target,
            horizon_seconds=int(spec["horizon"].total_seconds()), threshold=spec["threshold"],
            reference_price_usd=price, reference_snapshot_id=snapshot_id,
            probability=heuristic_probability(target, analysis.opportunity_score, analysis.risk_score),
            calibrated=False, baseline_probability=baseline_probability(db, target, now),
            features={"opportunity_score": analysis.opportunity_score, "risk_score": analysis.risk_score,
                      "liquidity_usd": liq, "pair_age_hours": features.get("pair_age_hours"),
                      "engine_version": analysis.engine_version},
            resolve_at=now + spec["horizon"], status="pending",
        )
        db.add(p)
        created.append(p)
    db.flush()
    return created


def evaluate_prediction(db: Session, p: Prediction, now=None) -> None:
    now = now or utcnow()
    if now < p.resolve_at:
        return  # horizonte ainda aberto: não contabiliza
    prices = db.execute(
        select(PairSnapshot.received_at, PairSnapshot.price_usd, PairSnapshot.liquidity_usd)
        .where(
            PairSnapshot.pair_id == p.pair_id,
            PairSnapshot.received_at > p.created_at,
            PairSnapshot.received_at <= p.resolve_at,
            PairSnapshot.price_usd.is_not(None),
        )
        .order_by(PairSnapshot.received_at)
    ).all()
    p.evaluated_at = now
    p.observations_count = len(prices)
    if len(prices) < MIN_OBSERVATIONS or prices[-1][0] < p.resolve_at - MAX_END_GAP:
        p.status = "unevaluable"
        p.outcome = None
        p.outcome_detail = (
            f"cobertura insuficiente: {len(prices)} observações; "
            "token pode ter deixado de ser negociado ou a coleta falhou (não descartado das métricas)"
        )
        return
    ref = p.reference_price_usd
    rets = [(px / ref) - 1 for _, px, _ in prices]
    p.observed_max_return = max(rets)
    p.observed_min_return = min(rets)
    p.observed_end_return = rets[-1]
    spec = TARGETS.get(p.target)
    direction = spec["direction"] if spec else ("up" if p.threshold > 0 else "down")
    p.outcome = p.observed_max_return >= p.threshold if direction == "up" else p.observed_min_return <= p.threshold
    p.status = "evaluated"
    p.outcome_detail = "avaliado com preços amostrados pela coleta (picos entre coletas podem não aparecer)"


def evaluate_due(db: Session, now=None) -> int:
    now = now or utcnow()
    due = db.scalars(
        select(Prediction).where(Prediction.status == "pending", Prediction.resolve_at <= now).limit(500)
    ).all()
    for p in due:
        evaluate_prediction(db, p, now)
    db.commit()
    return len(due)


def _brier(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    return round(sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs) / len(pairs), 5)


def compute_metrics(db: Session, target: str | None = None) -> list[dict]:
    out = []
    for tgt in ([target] if target else list(TARGETS)):
        preds = db.scalars(select(Prediction).where(Prediction.target == tgt)).all()
        ev = [p for p in preds if p.status == "evaluated"]
        pairs = [(p.probability, bool(p.outcome)) for p in ev]
        base_pairs = [(p.baseline_probability, bool(p.outcome)) for p in ev if p.baseline_probability is not None]
        model_on_base = [(p.probability, bool(p.outcome)) for p in ev if p.baseline_probability is not None]
        thresholds = []
        for th in (0.3, 0.5, 0.7):
            tp = sum(1 for p, y in pairs if p >= th and y)
            fp = sum(1 for p, y in pairs if p >= th and not y)
            fn = sum(1 for p, y in pairs if p < th and y)
            thresholds.append({
                "threshold": th, "signals": tp + fp, "true_positives": tp, "false_positives": fp,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            })
        bins = []
        for i in range(10):
            lo, hi = i / 10, (i + 1) / 10
            members = [(p, y) for p, y in pairs if lo <= p < hi or (i == 9 and p == 1.0)]
            if members:
                bins.append({
                    "bin_low": lo, "bin_high": hi, "count": len(members),
                    "mean_predicted": round(sum(p for p, _ in members) / len(members), 4),
                    "observed_rate": round(sum(1 for _, y in members if y) / len(members), 4),
                })
        by_liq = []
        for name, lo, hi in (("<20k", 0, 20_000), ("20k-100k", 20_000, 100_000), (">=100k", 100_000, float("inf"))):
            m = [(p.probability, bool(p.outcome)) for p in ev if lo <= (p.features or {}).get("liquidity_usd", 0) < hi]
            by_liq.append({"bucket": name, "count": len(m), "observed_rate": round(sum(1 for _, y in m if y) / len(m), 4) if m else None, "brier": _brier(m)})
        out.append({
            "target": tgt,
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "calibrated": False,
            "total": len(preds),
            "pending": sum(1 for p in preds if p.status == "pending"),
            "evaluated": len(ev),
            "unevaluable": sum(1 for p in preds if p.status == "unevaluable"),
            "observed_rate": round(sum(1 for _, y in pairs if y) / len(pairs), 4) if pairs else None,
            "brier_model": _brier(pairs),
            "brier_model_where_baseline": _brier(model_on_base),
            "brier_baseline": _brier(base_pairs),
            "baseline_samples": len(base_pairs),
            "thresholds": thresholds,
            "calibration_bins": bins,
            "by_liquidity": by_liq,
            "sufficient_sample": len(ev) >= 100,
            "notes": [
                "Coeficientes a priori, sem calibração; probabilidades não devem ser lidas como frequências reais.",
                "Retorno líquido hipotético (custos/slippage) ainda não calculado.",
            ],
        })
    return out
