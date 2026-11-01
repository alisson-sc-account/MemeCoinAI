"""Rótulos de retorno futuro por horizonte e estimativas empíricas.

1. `label_due(db)`: para cada análise cujo horizonte JÁ terminou, mede o preço
   máximo, mínimo e final observado em (t, t+h] e grava em `analysis_outcomes`.
   Como a coleta só grava snapshot quando o conteúdo muda, a ausência de
   snapshot com coleta funcionando significa preço inalterado; por isso a
   cobertura é verificada pelas execuções do coletor (`collector_runs`), não
   pela contagem de snapshots.
2. `estimate(db, opp, risk, as_of)`: distribuição empírica dos retornos de
   análises PASSADAS semelhantes (mesma faixa de oportunidade e de risco),
   usando apenas rótulos já conhecidos em `as_of` (sem vazamento).

Limitações: amostras de um mesmo token em instantes próximos são
correlacionadas (o "n" efetivo é menor que o exibido); preços amostrados a
cada coleta (~30-60 s) podem perder picos; retornos são brutos (sem taxas e
slippage).
"""
import bisect
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Analysis, AnalysisOutcome, CollectorRun, PairSnapshot

METHOD_VERSION = "out-1"
HORIZONS = {"15m": 900, "1h": 3600, "6h": 21600}
# Maior intervalo aceitável sem execução bem-sucedida do coletor dentro da janela.
MAX_COLLECTION_GAP = timedelta(minutes=5)
LABEL_LOOKBACK = timedelta(days=8)
MIN_SAMPLES = 30
ESTIMATE_LOOKBACK = timedelta(days=7)
_CACHE_TTL = 120.0


def _collection_gaps_ok(run_times: list[datetime], start: datetime, end: datetime) -> bool:
    """True se houve coleta bem-sucedida sem lacunas maiores que o limite em [start, end]."""
    i = bisect.bisect_left(run_times, start - MAX_COLLECTION_GAP)
    points = [start]
    while i < len(run_times) and run_times[i] <= end + MAX_COLLECTION_GAP:
        points.append(run_times[i])
        i += 1
    points.append(end)
    points.sort()
    if len(points) < 3:
        return False
    return all(b - a <= MAX_COLLECTION_GAP for a, b in zip(points, points[1:]))


def label_due(db: Session, now: datetime | None = None, limit: int = 2000) -> int:
    now = now or utcnow()
    runs = [
        r.finished_at
        for r in db.scalars(
            select(CollectorRun)
            .where(
                CollectorRun.source == "dexscreener",
                CollectorRun.job == "refresh",
                CollectorRun.status.in_(("ok", "partial")),
                CollectorRun.started_at >= now - LABEL_LOOKBACK - timedelta(hours=7),
            )
            .order_by(CollectorRun.finished_at)
        )
        if r.finished_at
    ]
    labeled = 0
    for name, secs in HORIZONS.items():
        h = timedelta(seconds=secs)
        done = select(AnalysisOutcome.analysis_id).where(AnalysisOutcome.horizon_seconds == secs)
        candidates = db.scalars(
            select(Analysis)
            .where(
                Analysis.computed_at <= now - h,
                Analysis.computed_at >= now - LABEL_LOOKBACK,
                Analysis.pair_id.is_not(None),
                Analysis.id.not_in(done),
            )
            .order_by(Analysis.computed_at)
            .limit(limit)
        ).all()
        for a in candidates:
            ref = (a.features or {}).get("price_usd")
            t0, t1 = a.computed_at, a.computed_at + h
            out = AnalysisOutcome(
                analysis_id=a.id, token_id=a.token_id, horizon_seconds=secs, analysis_time=t0,
                opportunity_score=a.opportunity_score, risk_score=a.risk_score, labeled_at=now,
            )
            if not ref or not _collection_gaps_ok(runs, t0, t1):
                out.status = "unevaluable"
            else:
                prices = db.scalars(
                    select(PairSnapshot.price_usd)
                    .where(
                        PairSnapshot.pair_id == a.pair_id,
                        PairSnapshot.received_at > t0,
                        PairSnapshot.received_at <= t1,
                        PairSnapshot.price_usd.is_not(None),
                    )
                    .order_by(PairSnapshot.received_at)
                ).all()
                # Sem snapshot novo com coleta ativa = preço não mudou.
                series = [ref, *prices]
                rets = [p / ref - 1 for p in series]
                out.status = "ok"
                out.max_return, out.min_return, out.end_return = max(rets), min(rets), rets[-1]
                out.observations = len(prices)
            db.add(out)
            labeled += 1
            if labeled % 200 == 0:
                db.commit()  # transações curtas: não segura a trava do SQLite por muito tempo
    db.commit()
    _cache.clear()
    return labeled


def opportunity_bucket(score: float) -> int:
    return 0 if score < 20 else 1 if score < 40 else 2 if score < 60 else 3


def risk_bucket(score: float) -> int:
    return 0 if score < 50 else 1


_cache: dict[tuple, tuple[float, list]] = {}


def _samples(db: Session, secs: int, as_of: datetime) -> list[tuple[float, float, float, float, float]]:
    key = (secs, as_of.replace(second=0, microsecond=0))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    rows = db.execute(
        select(
            AnalysisOutcome.opportunity_score, AnalysisOutcome.risk_score, AnalysisOutcome.end_return,
            AnalysisOutcome.max_return, AnalysisOutcome.min_return,
        ).where(
            AnalysisOutcome.horizon_seconds == secs,
            AnalysisOutcome.status == "ok",
            # Rótulo só é conhecido depois de t+h: evita vazamento ao reavaliar o passado.
            AnalysisOutcome.analysis_time <= as_of - timedelta(seconds=secs),
            AnalysisOutcome.analysis_time >= as_of - ESTIMATE_LOOKBACK,
        )
    ).all()
    data = [tuple(r) for r in rows]
    # Só o minuto atual interessa: sem isto, cada minuto deixava uma cópia dos rótulos na memória.
    for old in [k for k in _cache if (k[1] if k[0] == "estimate" else k[-1]) != key[-1]]:
        del _cache[old]
    _cache[key] = (time.monotonic(), data)
    return data


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        raise ValueError("vazio")
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def summarize(rows: list[tuple]) -> dict:
    ends = sorted(r[2] for r in rows)
    maxs = sorted(r[3] for r in rows)
    n = len(rows)
    return {
        "n": n,
        "end_p25": round(_quantile(ends, 0.25), 4),
        "end_median": round(_quantile(ends, 0.5), 4),
        "end_p75": round(_quantile(ends, 0.75), 4),
        "max_median": round(_quantile(maxs, 0.5), 4),
        "p_up_10": round(sum(1 for r in rows if r[3] >= 0.10) / n, 4),
        "p_up_20": round(sum(1 for r in rows if r[3] >= 0.20) / n, 4),
        "p_up_50": round(sum(1 for r in rows if r[3] >= 0.50) / n, 4),
        "p_down_20": round(sum(1 for r in rows if r[4] <= -0.20) / n, 4),
        "p_end_positive": round(sum(1 for r in rows if r[2] > 0) / n, 4),
    }


def estimate(db: Session, opportunity_score: float, risk_score: float, as_of: datetime | None = None) -> list[dict]:
    """Estimativas por horizonte. `basis`: similar | general | insufficient."""
    as_of = as_of or utcnow()
    ob, rb = opportunity_bucket(opportunity_score), risk_bucket(risk_score)
    # Mesmo minuto e mesma faixa = mesmos rótulos e mesmo resultado: varrer tudo a cada moeda
    # consumia 70% do tempo da análise e atrasava o disparo.
    memo_key = ("estimate", as_of.replace(second=0, microsecond=0), ob, rb)
    hit = _cache.get(memo_key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return [dict(e) for e in hit[1]]
    out = []
    for name, secs in HORIZONS.items():
        rows = _samples(db, secs, as_of)
        similar = [r for r in rows if opportunity_bucket(r[0]) == ob and risk_bucket(r[1]) == rb]
        entry = {"horizon": name, "horizon_seconds": secs, "method_version": METHOD_VERSION}
        if len(similar) >= MIN_SAMPLES:
            entry.update(basis="similar", **summarize(similar))
        elif len(rows) >= MIN_SAMPLES:
            entry.update(basis="general", **summarize(rows))
        else:
            entry.update(basis="insufficient", n=len(rows), needed=MIN_SAMPLES)
        out.append(entry)
    _cache[memo_key] = (time.monotonic(), out)
    return [dict(e) for e in out]
