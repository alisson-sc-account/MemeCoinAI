"""Acertos dos sinais de subida (COMPRAR) e de queda (VENDER) — `acc-1`.

Cada sinal é julgado pelo preço de referência gravado NO MOMENTO em que foi emitido
(`Signal.reference_price_usd`, `Signal.created_at`) contra o preço observado ao fim
do horizonte (15 min, 1 h, 6 h):
- COMPRAR ("deve subir") acerta se o preço final ficou ACIMA da referência.
- VENDER ("deve descer") acerta se o preço final ficou ABAIXO da referência.

Só conta depois que o horizonte terminou (antes disso: "pendente"). Sem coleta
contínua na janela o resultado é "inavaliável" — nunca é contado como acerto nem erro.
Sem snapshot novo com coleta ativa = preço inalterado (como em `outcomes.py`).
Retornos são brutos: sem taxas nem slippage.

Níveis (mesma correspondência da aba "Compre agora"): COMPRAR forte = Compra
prioritária; COMPRAR moderado = Compra possível; AGUARDAR = Observar; VENDER = Venda.
"Observar" não é previsão: entra só como REFERÊNCIA, julgado como se fosse compra
("o preço subiu mesmo assim?"). Se um nível de compra acerta menos que Observar,
o sinal está pior que não fazer nada.
"""
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.engine.outcomes import HORIZONS, _collection_gaps_ok
from app.models import CollectorRun, PairSnapshot, Signal, Token

RULES_VERSION = "acc-1"
LOOKBACK = timedelta(days=14)
MAX_SIGNALS = 1000  # por grupo (previsões e referência), para Observar não engolir os demais
_CACHE_TTL = 30.0
_cache: tuple[float, list[dict]] | None = None


TIERS = ("priority_buy", "possible_buy", "watch", "sell")
TIER_LABELS = {"priority_buy": "Compra prioritária", "possible_buy": "Compra possível",
               "watch": "Observar (referência)", "sell": "Venda (queda)"}


def tier_of(action: str, strength: str) -> str:
    if action == "buy":
        return "priority_buy" if strength == "strong" else "possible_buy"
    return "sell" if action == "sell" else "watch"


def judge(action: str, end_return: float) -> bool:
    """Compra e Observar: acerta se subiu. Venda: acerta se caiu."""
    return end_return < 0 if action == "sell" else end_return > 0


def _evaluate_one(db: Session, sig: Signal, pair_id: int | None, runs: list[datetime], now: datetime) -> dict:
    results = {}
    for name, secs in HORIZONS.items():
        t0, t1 = sig.created_at, sig.created_at + timedelta(seconds=secs)
        if t1 > now:
            results[name] = {"status": "pending", "resolves_at": t1}
            continue
        if not pair_id or not sig.reference_price_usd or not _collection_gaps_ok(runs, t0, t1):
            results[name] = {"status": "unevaluable", "resolves_at": t1}
            continue
        prices = db.scalars(
            select(PairSnapshot.price_usd)
            .where(PairSnapshot.pair_id == pair_id, PairSnapshot.received_at > t0,
                   PairSnapshot.received_at <= t1, PairSnapshot.price_usd.is_not(None))
            .order_by(PairSnapshot.received_at)
        ).all()
        ref = sig.reference_price_usd
        rets = [p / ref - 1 for p in [ref, *prices]]
        end = rets[-1]
        results[name] = {
            "status": "hit" if judge(sig.action, end) else "miss", "resolves_at": t1,
            "end_return": round(end, 4), "max_return": round(max(rets), 4), "min_return": round(min(rets), 4),
            "end_price_usd": ref * (1 + end),
        }
    return results


def evaluate_signals(db: Session, now: datetime | None = None, use_cache: bool = True) -> list[dict]:
    """Lista (mais recente primeiro) dos sinais de compra/venda com o resultado por horizonte."""
    global _cache
    if use_cache and _cache and time.monotonic() - _cache[0] < _CACHE_TTL:
        return _cache[1]
    now = now or utcnow()
    def recent(actions: tuple[str, ...]) -> list[Signal]:
        return list(db.scalars(
            select(Signal)
            .where(Signal.action.in_(actions), Signal.created_at >= now - LOOKBACK)
            .order_by(Signal.created_at.desc())
            .limit(MAX_SIGNALS)
        ))

    signals = sorted(recent(("buy", "sell")) + recent(("hold",)), key=lambda s: s.created_at, reverse=True)
    tokens = {t.id: t for t in db.scalars(select(Token).where(Token.id.in_({s.token_id for s in signals})))} if signals else {}
    runs = [
        r for r in db.scalars(
            select(CollectorRun.finished_at)
            .where(CollectorRun.source == "dexscreener", CollectorRun.job == "refresh",
                   CollectorRun.status.in_(("ok", "partial")), CollectorRun.finished_at.is_not(None),
                   CollectorRun.started_at >= now - LOOKBACK - timedelta(hours=7))
            .order_by(CollectorRun.finished_at)
        )
    ]
    items = []
    for s in signals:
        tok = tokens.get(s.token_id)
        if tok is None:
            continue
        items.append({"signal": s, "token": tok, "tier": tier_of(s.action, s.strength),
                      "results": _evaluate_one(db, s, tok.primary_pair_id, runs, now)})
    _cache = (time.monotonic(), items)
    return items


def _group(item: dict, key: str) -> bool:
    action = item["signal"].action
    if key == "all":  # só previsões reais (subida e queda); Observar fica de fora
        return action in ("buy", "sell")
    if key in ("buy", "sell"):
        return action == key
    return item["tier"] == key


def summarize(items: list[dict]) -> dict:
    """Contagem por horizonte: subida, queda, todas as previsões e cada nível."""
    out = {}
    for name in HORIZONS:
        block = {}
        for action in ("buy", "sell", "all", *TIERS):
            rows = [i["results"][name] for i in items if _group(i, action)]
            hits = sum(1 for r in rows if r["status"] == "hit")
            misses = sum(1 for r in rows if r["status"] == "miss")
            judged = hits + misses
            block[action] = {
                "hits": hits, "misses": misses, "evaluated": judged,
                "pending": sum(1 for r in rows if r["status"] == "pending"),
                "unevaluable": sum(1 for r in rows if r["status"] == "unevaluable"),
                "hit_rate": round(hits / judged, 4) if judged else None,
            }
        out[name] = block
    return out


def clear_cache() -> None:
    global _cache
    _cache = None
