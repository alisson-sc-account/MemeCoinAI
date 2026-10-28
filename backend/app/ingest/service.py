"""Coleta de mercado (Camada A): descoberta, watchlist e refresh periódico."""
import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.ingest.normalize import (
    NORMALIZER_VERSION,
    NormalizationError,
    NormalizedPair,
    normalize_address,
    normalize_pair,
)
from app.models import CollectorRun, Pair, PairSnapshot, Token
from app.sources import dexscreener
from app.sources.dexscreener import MAX_ADDRESSES_PER_REQUEST, DexScreenerClient
from app.sources.http import FetchResult

log = logging.getLogger(__name__)


@contextmanager
def collector_run(db: Session, source: str, job: str) -> Iterator[CollectorRun]:
    run = CollectorRun(source=source, job=job, started_at=utcnow())
    db.add(run)
    db.flush()
    latencies: list[float] = []
    run._latencies = latencies  # type: ignore[attr-defined]
    try:
        yield run
    except Exception as exc:  # registra e propaga
        run.status = "error"
        run.errors += 1
        run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        run.finished_at = utcnow()
        if latencies:
            run.latency_ms_avg = sum(latencies) / len(latencies)
        if run.status == "running":
            if run.errors and run.items_received == 0:
                run.status = "error"
            elif run.errors:
                run.status = "partial"
            else:
                run.status = "ok"
        db.commit()


def record_fetch(run: CollectorRun, res: FetchResult) -> None:
    run.requests += res.attempts or 1
    run._latencies.extend(res.latencies)  # type: ignore[attr-defined]
    if res.rate_limited:
        run.rate_limited += 1
    if not res.ok:
        run.errors += 1
        run.error_message = (res.error or "erro desconhecido")[:2000]


def _upsert_pair(db: Session, np: NormalizedPair, token: Token, now: datetime) -> Pair:
    pair = db.scalar(
        select(Pair).where(Pair.chain_id == np.chain_id, Pair.pair_address == np.pair_address)
    )
    if pair is None:
        pair = Pair(
            chain_id=np.chain_id,
            pair_address=np.pair_address,
            base_token_id=token.id,
            first_seen_at=now,
        )
        db.add(pair)
    pair.dex_id = np.dex_id
    pair.labels = np.labels
    pair.quote_address = np.quote_address
    pair.quote_symbol = np.quote_symbol
    pair.url = np.url
    pair.pair_created_at = np.pair_created_at
    pair.last_seen_at = now
    db.flush()
    return pair


def _store_snapshot(db: Session, pair: Pair, np: NormalizedPair, received_at: datetime) -> bool:
    """Grava snapshot. Retorna False se idêntico ao último (resposta em cache)."""
    last_hash = db.scalar(
        select(PairSnapshot.payload_hash)
        .where(PairSnapshot.pair_id == pair.id)
        .order_by(PairSnapshot.received_at.desc())
        .limit(1)
    )
    if last_hash == np.payload_hash:
        return False
    db.add(
        PairSnapshot(
            pair_id=pair.id,
            source=dexscreener.SOURCE_NAME,
            source_time=None,
            received_at=received_at,
            stored_at=utcnow(),
            normalizer_version=NORMALIZER_VERSION,
            payload_hash=np.payload_hash,
            missing_fields=np.missing_fields,
            raw=np.raw,
            **np.metrics,
        )
    )
    return True


def ingest_pairs(
    db: Session, run: CollectorRun, raw_pairs: list, tokens_by_key: dict[tuple[str, str], Token], received_at: datetime
) -> set[int]:
    """Normaliza e persiste pares cujo token-base está em `tokens_by_key`.

    Retorna ids dos tokens que receberam dados novos.
    """
    touched: set[int] = set()
    best_liq: dict[int, tuple[float, int]] = {}
    for raw in raw_pairs:
        run.items_received += 1
        try:
            np = normalize_pair(raw)
        except NormalizationError as exc:
            run.errors += 1
            run.error_message = str(exc)
            continue
        token = tokens_by_key.get((np.chain_id, np.base_address))
        if token is None:
            # Par em que o token monitorado é o quote: preço não é do nosso token.
            continue
        pair = _upsert_pair(db, np, token, received_at)
        token.symbol = np.base_symbol or token.symbol
        token.name = np.base_name or token.name
        if np.links:
            token.links = np.links
        if np.image_url:
            token.image_url = np.image_url
        token.last_refreshed_at = received_at
        if _store_snapshot(db, pair, np, received_at):
            run.items_stored += 1
            touched.add(token.id)
        else:
            run.duplicates += 1
        liq = np.metrics.get("liquidity_usd") or 0.0
        if token.id not in best_liq or liq > best_liq[token.id][0]:
            best_liq[token.id] = (liq, pair.id)
    for token_id, (_, pair_id) in best_liq.items():
        tok = db.get(Token, token_id)
        tok.primary_pair_id = pair_id
    db.flush()
    return touched


def refresh_tracked(db: Session, client: DexScreenerClient | None = None) -> set[int]:
    client = client or DexScreenerClient()
    touched: set[int] = set()
    tokens = db.scalars(select(Token).where(Token.is_tracked.is_(True))).all()
    by_chain: dict[str, list[Token]] = defaultdict(list)
    for t in tokens:
        by_chain[t.chain_id].append(t)
    with collector_run(db, dexscreener.SOURCE_NAME, "refresh") as run:
        for chain_id, chain_tokens in by_chain.items():
            for i in range(0, len(chain_tokens), MAX_ADDRESSES_PER_REQUEST):
                batch = chain_tokens[i : i + MAX_ADDRESSES_PER_REQUEST]
                res = client.tokens(chain_id, [t.address for t in batch])
                record_fetch(run, res)
                if not res.ok:
                    continue
                keys = {(t.chain_id, t.address): t for t in batch}
                touched |= ingest_pairs(db, run, res.data, keys, utcnow())
                db.commit()
    return touched


def track_token(
    db: Session, chain_id: str, address: str, discovered_via: str = "watchlist", client: DexScreenerClient | None = None
) -> tuple[Token | None, FetchResult]:
    """Adiciona um token ao monitoramento após confirmar na fonte que ele existe."""
    client = client or DexScreenerClient()
    address = normalize_address(chain_id, address)
    with collector_run(db, dexscreener.SOURCE_NAME, "track") as run:
        res = client.tokens(chain_id, [address])
        record_fetch(run, res)
        if not res.ok:
            return None, res
        bases = [
            p for p in res.data
            if isinstance(p, dict)
            and normalize_address(chain_id, (p.get("baseToken") or {}).get("address", "")) == address
        ]
        if not bases:
            return None, res
        token = db.scalar(select(Token).where(Token.chain_id == chain_id, Token.address == address))
        if token is None:
            token = Token(chain_id=chain_id, address=address, discovered_via=discovered_via, first_seen_at=utcnow())
            db.add(token)
            db.flush()
        token.is_tracked = True
        ingest_pairs(db, run, bases, {(chain_id, address): token}, utcnow())
    return token, res


def discover(db: Session, client: DexScreenerClient | None = None) -> list[Token]:
    """Adiciona tokens recentes (profiles/boosts) das redes configuradas.

    Viés conhecido: profiles e boosts são listas pagas/autodeclaradas pelo
    projeto; não representam todo o mercado. Registrado em `discovered_via`.
    """
    s = get_settings()
    client = client or DexScreenerClient()
    chains = set(s.chain_list)
    added: list[Token] = []
    with collector_run(db, dexscreener.SOURCE_NAME, "discover") as run:
        tracked = db.scalar(select(func.count()).select_from(Token).where(Token.is_tracked.is_(True))) or 0
        capacity = max(0, s.max_tracked_tokens - tracked)
        for via, fetch in (("dexscreener_profiles", client.latest_profiles), ("dexscreener_boosts", client.latest_boosts)):
            res = fetch()
            record_fetch(run, res)
            if not res.ok:
                continue
            for item in res.data:
                run.items_received += 1
                if capacity <= 0:
                    break
                chain_id, addr = item.get("chainId"), item.get("tokenAddress")
                if chain_id not in chains or not addr:
                    continue
                addr = normalize_address(chain_id, addr)
                exists = db.scalar(select(Token.id).where(Token.chain_id == chain_id, Token.address == addr))
                if exists:
                    run.duplicates += 1
                    continue
                tok = Token(chain_id=chain_id, address=addr, discovered_via=via, first_seen_at=utcnow())
                db.add(tok)
                db.flush()
                added.append(tok)
                run.items_stored += 1
                capacity -= 1
    return added


def source_status(db: Session, source: str) -> dict:
    """Estado derivado das últimas execuções de uma fonte."""
    s = get_settings()
    runs = db.scalars(
        select(CollectorRun)
        .where(CollectorRun.source == source, CollectorRun.status != "running")
        .order_by(CollectorRun.started_at.desc())
        .limit(20)
    ).all()
    if not runs:
        return {
            "source": source, "status": "unknown", "last_success_at": None, "last_error_at": None,
            "last_error": None, "consecutive_failures": 0, "latency_ms_avg": None, "rate_limited_recent": 0,
        }
    consecutive = 0
    for r in runs:
        if r.status == "error":
            consecutive += 1
        else:
            break
    last_ok = next((r for r in runs if r.status in ("ok", "partial")), None)
    last_err = next((r for r in runs if r.status in ("error", "partial") and r.error_message), None)
    lat = [r.latency_ms_avg for r in runs[:5] if r.latency_ms_avg is not None]
    if consecutive >= s.source_failure_threshold:
        status = "down"
    elif consecutive > 0 or runs[0].status == "partial":
        status = "degraded"
    else:
        status = "ok"
    return {
        "source": source,
        "status": status,
        "last_success_at": last_ok.finished_at if last_ok else None,
        "last_error_at": last_err.finished_at if last_err else None,
        "last_error": last_err.error_message if last_err else None,
        "consecutive_failures": consecutive,
        "latency_ms_avg": sum(lat) / len(lat) if lat else None,
        "rate_limited_recent": sum(r.rate_limited for r in runs[:5]),
    }
