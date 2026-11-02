"""Coleta de mercado (Camada A): descoberta, watchlist e refresh periódico."""
import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import delete, func, null, select, text, update
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
from app.models import CollectorRun, Pair, PairSnapshot, Position, Signal, Token
from app.sources import dexscreener
from app.sources.dexscreener import MAX_ADDRESSES_PER_REQUEST, DexScreenerClient
from app.sources.geckoterminal import MAX_PAGES, GeckoTerminalClient, parse_pool
from app.sources.jupiter_tokens import RANKINGS, JupiterTokensClient
from app.sources.http import FetchResult

log = logging.getLogger(__name__)


@contextmanager
def collector_run(db: Session, source: str, job: str) -> Iterator[CollectorRun]:
    """Registra uma execução de coleta.

    O registro só é gravado no FIM: gravar no início abria uma transação de escrita
    no SQLite que ficava presa durante as chamadas de rede (RPC com espera por 429),
    bloqueando a API ("database is locked"). Os contadores ficam em memória até lá.
    """
    run = CollectorRun(source=source, job=job, started_at=utcnow(), status="running", requests=0,
                       items_received=0, items_stored=0, duplicates=0, errors=0, rate_limited=0)
    latencies: list[float] = []
    run._latencies = latencies  # type: ignore[attr-defined]
    try:
        yield run
    except Exception as exc:  # registra e propaga
        db.rollback()
        run.status = "error"
        run.errors += 1
        run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        raise
    finally:
        db.add(run)
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


def _store_snapshot(db: Session, pair: Pair, np: NormalizedPair, received_at: datetime, keep_raw: bool = False) -> bool:
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
            raw=np.raw if keep_raw or get_settings().store_raw_payload else None,
            **np.metrics,
        )
    )
    return True


def ingest_pairs(
    db: Session, run: CollectorRun, raw_pairs: list, tokens_by_key: dict[tuple[str, str], Token], received_at: datetime,
    keep_raw: bool = False,
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
        if _store_snapshot(db, pair, np, received_at, keep_raw):
            run.items_stored += 1
            touched.add(token.id)
        else:
            run.duplicates += 1
        token.heat = max(token.heat if token.id in best_liq else 0.0, np.metrics.get("volume_h1") or 0.0)
        liq = np.metrics.get("liquidity_usd") or 0.0
        if token.id not in best_liq or liq > best_liq[token.id][0]:
            best_liq[token.id] = (liq, pair.id)
    for token_id, (_, pair_id) in best_liq.items():
        tok = db.get(Token, token_id)
        tok.primary_pair_id = pair_id
    db.flush()
    return touched


COMPACT_AFTER_DAYS = 15
NEW_TOKENS_PER_CYCLE = 300  # novatos em massa não podem empurrar as moedas quentes para fora


def split_hot_cold(db: Session, boosted: set[int] | None = None) -> tuple[list[Token], list[Token]]:
    """Quentes: posições, sinais de compra/venda, radar, novatos e mais volume. Frios: o resto, do mais antigo."""
    s = get_settings()
    tokens = db.scalars(select(Token).where(Token.is_tracked.is_(True))).all()
    urgent = set(db.scalars(select(Position.token_id)).all()) | (boosted or set())
    urgent |= set(db.scalars(select(Signal.token_id).where(Signal.status == "active", Signal.action.in_(("buy", "sell")))).all())
    first = [t for t in tokens if t.id in urgent]
    chosen = {t.id for t in first}
    new = [t for t in tokens if t.id not in chosen and t.last_refreshed_at is None][:NEW_TOKENS_PER_CYCLE]
    first += new
    chosen |= {t.id for t in new}
    rest = sorted((t for t in tokens if t.id not in chosen), key=lambda t: t.heat or 0.0, reverse=True)
    room = max(0, s.refresh_hot_tokens - len(first))
    # Sem data (novato além da cota) conta como o mais antigo.
    cold = sorted(rest[room:], key=lambda t: t.last_refreshed_at.timestamp() if t.last_refreshed_at else 0.0)
    return first + rest[:room], cold


def _refresh_selection(db: Session) -> list[Token]:
    s = get_settings()
    hot, cold = split_hot_cold(db)
    return (hot + cold)[: s.refresh_requests_per_cycle * MAX_ADDRESSES_PER_REQUEST]


def refresh_tracked(db: Session, client: DexScreenerClient | None = None, tokens: list[Token] | None = None, job: str = "refresh") -> set[int]:
    client = client or DexScreenerClient()
    touched: set[int] = set()
    tokens = _refresh_selection(db) if tokens is None else tokens
    by_chain: dict[str, list[Token]] = defaultdict(list)
    for t in tokens:
        by_chain[t.chain_id].append(t)
    with collector_run(db, dexscreener.SOURCE_NAME, job) as run:
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
        ingest_pairs(db, run, bases, {(chain_id, address): token}, utcnow(), keep_raw=True)
    return token, res


def _add_token(db: Session, run: CollectorRun, chains: set[str], chain_id: str | None, address: str | None, via: str) -> Token | None:
    if not chain_id or chain_id not in chains or not address:
        return None
    address = normalize_address(chain_id, address)
    if db.scalar(select(Token.id).where(Token.chain_id == chain_id, Token.address == address)):
        run.duplicates += 1
        return None
    tok = Token(chain_id=chain_id, address=address, discovered_via=via, first_seen_at=utcnow())
    db.add(tok)
    db.flush()
    run.items_stored += 1
    return tok


DISCOVERY_PARTS = ("lists", "search", "gecko", "jupiter")


def scout(db: Session, name: str, client: JupiterTokensClient | None = None) -> tuple[set[int], int]:
    """Radar: moedas das listas de "mais negociados agora". Devolve (ids para promover, novas adicionadas)."""
    s = get_settings()
    res = (client or JupiterTokensClient()).listing(name)
    if not res.ok:
        log.warning("radar %s: %s", name, res.error)
        return set(), 0
    mints = [i.get("id") for i in res.data if isinstance(i, dict) and i.get("id") and (i.get("liquidity") or 0) >= s.discovery_min_liquidity_usd]
    known = dict(db.execute(select(Token.address, Token.id).where(Token.chain_id == "solana", Token.address.in_(mints))).all()) if mints else {}
    ids, added = set(known.values()), 0
    tracked = db.scalar(select(func.count()).select_from(Token).where(Token.is_tracked.is_(True))) or 0
    for mint in mints:
        if mint not in known and tracked + added < s.max_tracked_tokens:
            tok = Token(chain_id="solana", address=mint, discovered_via="jupiter_scout", first_seen_at=utcnow())
            db.add(tok)
            db.flush()
            ids.add(tok.id)
            added += 1
    db.commit()
    return ids, added


def discover(db: Session, client: DexScreenerClient | None = None, parts: tuple[str, ...] = DISCOVERY_PARTS) -> list[Token]:
    """Descobre tokens novos nas redes configuradas.

    Três origens, todas gratuitas e com cobertura parcial (a fonte NÃO expõe um
    endpoint com todos os tokens):
    - perfis recentes e impulsionados (listas autodeclaradas/pagas pelo projeto);
    - buscas por termos comuns, rotacionadas a cada ciclo (até 30 pares cada).
    A origem fica registrada em `discovered_via`, e o viés está documentado.
    """
    s = get_settings()
    client = client or DexScreenerClient()
    chains = set(s.chain_list)
    added: list[Token] = []
    with collector_run(db, dexscreener.SOURCE_NAME, "discover") as run:
        tracked = db.scalar(select(func.count()).select_from(Token).where(Token.is_tracked.is_(True))) or 0
        capacity = max(0, s.max_tracked_tokens - tracked)
        if capacity <= 0:
            return added

        for via, fetch in () if "lists" not in parts else (
            ("dexscreener_profiles", client.latest_profiles),
            ("dexscreener_boosts", client.latest_boosts),
            ("dexscreener_boosts_top", client.top_boosts),
        ):
            if capacity <= 0:
                break
            res = fetch()
            record_fetch(run, res)
            if not res.ok:
                continue
            for item in res.data:
                run.items_received += 1
                if capacity <= 0:
                    break
                tok = _add_token(db, run, chains, item.get("chainId"), item.get("tokenAddress"), via)
                if tok:
                    added.append(tok)
                    capacity -= 1
            db.commit()  # libera a trava de escrita antes da próxima chamada de rede

        # Buscas rotacionadas: a cada ciclo usa um bloco diferente de termos.
        queries = s.discovery_query_list
        if "search" in parts and queries and capacity > 0:
            per_cycle = max(1, s.discovery_queries_per_cycle)
            offset = (db.scalar(select(func.count()).select_from(CollectorRun).where(CollectorRun.job == "discover")) or 0) * per_cycle
            for i in range(per_cycle):
                if capacity <= 0:
                    break
                res = client.search(queries[(offset + i) % len(queries)])
                record_fetch(run, res)
                if not res.ok:
                    continue
                for pair in res.data:
                    run.items_received += 1
                    if capacity <= 0:
                        break
                    base = (pair or {}).get("baseToken") or {}
                    tok = _add_token(db, run, chains, pair.get("chainId"), base.get("address"), "dexscreener_search")
                    if tok:
                        added.append(tok)
                        capacity -= 1
                db.commit()  # idem: uma transação curta por busca

        # GeckoTerminal: pools novas/em alta. Pool quase sem liquidez não gasta vaga.
        if "gecko" in parts and capacity > 0 and s.geckoterminal_pages_per_cycle > 0:
            gecko = GeckoTerminalClient()
            pages = min(s.geckoterminal_pages_per_cycle, MAX_PAGES)
            for chain in chains:
                for kind in ("trending_pools", "new_pools"):
                    for page in range(1, pages + 1):
                        if capacity <= 0:
                            break
                        res = gecko.pools(chain, kind, page)
                        if not res.ok:  # fonte auxiliar: falha dela não marca o DEX Screener como degradado
                            log.warning("geckoterminal %s p%d: %s", kind, page, res.error)
                            break
                        for pool in res.data:
                            run.items_received += 1
                            parsed = parse_pool(pool, chain)
                            if capacity <= 0 or not parsed or (parsed[1] or 0) < s.discovery_min_liquidity_usd:
                                continue
                            tok = _add_token(db, run, chains, chain, parsed[0], f"geckoterminal_{kind}")
                            if tok:
                                added.append(tok)
                                capacity -= 1
                        db.commit()

        # Listas da Jupiter: mais negociados, em alta e recém-criados (só Solana).
        if "jupiter" in parts and capacity > 0 and "solana" in chains:
            jupiter = JupiterTokensClient()
            offset = (db.scalar(select(func.count()).select_from(CollectorRun).where(CollectorRun.job == "discover")) or 0)
            for name in ("recent", RANKINGS[offset % len(RANKINGS)]):
                if capacity <= 0:
                    break
                res = jupiter.listing(name)
                if not res.ok:
                    log.warning("jupiter tokens %s: %s", name, res.error)
                    continue
                for item in res.data:
                    run.items_received += 1
                    if capacity <= 0 or not isinstance(item, dict) or (item.get("liquidity") or 0) < s.discovery_min_liquidity_usd:
                        continue
                    tok = _add_token(db, run, chains, "solana", item.get("id"), "jupiter_tokens")
                    if tok:
                        added.append(tok)
                        capacity -= 1
                db.commit()
    return added


def apply_raw_retention(db: Session, batch: int = 5000) -> int:
    """Apaga só o payload bruto antigo (dados normalizados ficam). Transações curtas por bloco."""
    cut = utcnow() - timedelta(days=get_settings().raw_payload_retention_days)
    total = 0
    while True:
        ids = db.scalars(select(PairSnapshot.id).where(PairSnapshot.raw.is_not(None), PairSnapshot.received_at < cut).limit(batch)).all()
        if not ids:
            return total
        db.execute(update(PairSnapshot).where(PairSnapshot.id.in_(ids)).values(raw=null()))
        db.commit()
        total += len(ids)


def prune_inactive(db: Session) -> int:
    """Para de monitorar tokens sem vida, liberando orçamento de coleta.

    Nunca remove tokens adicionados à mão (`watchlist`). O histórico é mantido:
    apenas `is_tracked` passa a falso, e o token volta se for adicionado de novo.
    """
    s = get_settings()
    cutoff = utcnow() - timedelta(hours=s.prune_after_hours)
    candidates = db.scalars(
        select(Token).where(
            Token.is_tracked.is_(True), Token.discovered_via != "watchlist", Token.first_seen_at < cutoff
        )
    ).all()
    if not candidates:
        return 0
    protected = set(db.scalars(select(Position.token_id)).all())
    pair_ids = [t.primary_pair_id for t in candidates if t.primary_pair_id]
    snaps = {}
    if pair_ids:
        sub = (
            select(PairSnapshot.pair_id, func.max(PairSnapshot.received_at).label("mx"))
            .where(PairSnapshot.pair_id.in_(pair_ids))
            .group_by(PairSnapshot.pair_id)
            .subquery()
        )
        snaps = {
            r.pair_id: r
            for r in db.scalars(
                select(PairSnapshot).join(sub, (PairSnapshot.pair_id == sub.c.pair_id) & (PairSnapshot.received_at == sub.c.mx))
            )
        }
    pruned = 0
    for t in candidates:
        if t.id in protected:
            continue
        snap = snaps.get(t.primary_pair_id) if t.primary_pair_id else None
        if snap is None:
            dead = True  # nenhum par encontrado pela fonte desde que entrou
        else:
            liq, vol = snap.liquidity_usd, snap.volume_h24
            dead = (liq is not None and liq < s.prune_min_liquidity_usd) and (vol is not None and vol < s.prune_min_volume_h24_usd)
        if dead:
            t.is_tracked = False
            pruned += 1
    db.commit()
    return pruned


def apply_snapshot_retention(db: Session, batch: int = 5000) -> int:
    """Apaga snapshots além da retenção, exceto de moedas com posição."""
    cut = utcnow() - timedelta(days=get_settings().snapshot_retention_days)
    keep = set(db.scalars(select(Position.token_id)).all())
    keep_pairs = select(Pair.id).where(Pair.base_token_id.in_(keep))
    total = 0
    while True:
        ids = db.scalars(select(PairSnapshot.id).where(PairSnapshot.received_at < cut, PairSnapshot.pair_id.not_in(keep_pairs)).limit(batch)).all()
        if not ids:
            return total
        db.execute(delete(PairSnapshot).where(PairSnapshot.id.in_(ids)))
        db.commit()
        total += len(ids)


def compact_old_snapshots(db: Session, batch: int = 5000) -> int:
    """Depois de 15 dias guarda 1 foto a cada 10 min: mais meses de histórico no mesmo disco."""
    if db.get_bind().dialect.name != "sqlite":
        return 0
    cut = utcnow() - timedelta(days=COMPACT_AFTER_DAYS)
    params = {"cut": cut.strftime("%Y-%m-%d %H:%M:%S"), "floor": (cut - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), "n": batch}
    total = 0
    while True:
        ids = db.scalars(text(
            """SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY pair_id, CAST(strftime('%s', received_at) AS INTEGER) / 600 ORDER BY received_at) AS rn
               FROM pair_snapshots WHERE received_at < :cut AND received_at >= :floor) WHERE rn > 1 LIMIT :n"""), params).all()
        if not ids:
            return total
        db.execute(delete(PairSnapshot).where(PairSnapshot.id.in_(ids)))
        db.commit()
        total += len(ids)


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
