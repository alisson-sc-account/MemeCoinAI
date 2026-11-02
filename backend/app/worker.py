"""Processo contínuo de coleta e análise.

Execução: `python -m app.worker` (um único processo por banco).
Não é adequado para funções serverless: precisa de processo de longa duração.
É o orquestrador: cada agente (ver `app/agents.py`) roda em sua própria thread, então RPC lento ou
descoberta demorada não atrasam o preço. Coleta e análise são separadas por uma fila com prioridade.
Limitadores globais por fonte dividem o orçamento de API. Cada job captura suas próprias falhas.
"""
import logging
import itertools
import signal
import threading
import time

from sqlalchemy import select

from app import agents, notify
from app.config import BACKEND_DIR, get_settings
from app.db import session_factory
from app.engine import burst, checks, outcomes
from app.engine.pipeline import analyze_tokens, sync_source_alerts
from app.engine.predict import evaluate_due
from app.ingest.service import apply_raw_retention, apply_snapshot_retention, compact_old_snapshots, discover, prune_inactive, refresh_tracked, scout, split_hot_cold
from app.logging_setup import setup_logging
from app.worker_lock import WorkerAlreadyRunning, WorkerLock
from app.models import Token
from app.sources import dexscreener, solana_rpc
from app.sources.dexscreener import MAX_ADDRESSES_PER_REQUEST
from app.sources.jupiter_tokens import RANKINGS

log = logging.getLogger("worker")
_running = True
_analysis_lock = threading.Lock()
ANALYSIS_AGENT = "analysis"
ANALYSIS_BATCH = 40
ANALYSIS_PAUSE = 0.5
_analysis_beat = [0.0]


def _stop(*_):
    global _running
    _running = False
    log.info("sinal de parada recebido; encerrando após o job atual")


def run_job(name: str, fn, interval: float = 60.0) -> None:
    t0 = time.perf_counter()
    db = session_factory()()
    error, items = None, 0
    try:
        result = fn(db)
        items = next((v for v in (result or {}).values() if isinstance(v, int)), 0) if isinstance(result, dict) else 0
        log.info("job=%s ok duração=%.1fs resultado=%s", name, time.perf_counter() - t0, result)
    except Exception as exc:
        db.rollback()
        error = f"{type(exc).__name__}: {exc}"[:300]
        log.exception("job=%s falhou", name)
    finally:
        try:
            if name != ANALYSIS_AGENT or error or time.monotonic() - _analysis_beat[0] > 10:
                _analysis_beat[0] = time.monotonic() if name == ANALYSIS_AGENT else _analysis_beat[0]
                agents.beat(db, name, interval, error, items, round((time.perf_counter() - t0) * 1000, 1))
        except Exception:
            db.rollback()
            log.warning("batimento de %s falhou", name)
        db.close()


class AnalysisQueue:
    """Moedas à espera de análise: quentes saem primeiro, e a mesma moeda não entra duas vezes.

    Separar da coleta faz a rede não esperar a CPU. Uma moeda quente com dado novo passa na frente de
    centenas de frias, que é o que mantém o disparo rápido mesmo com milhares de moedas.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._hot: dict[int, None] = {}
        self._cold: dict[int, None] = {}

    def add(self, ids, hot: bool) -> None:
        with self._lock:
            for i in ids:
                if hot:
                    self._cold.pop(i, None)
                    self._hot[i] = None
                elif i not in self._hot:
                    self._cold[i] = None

    def take(self, n: int) -> list[int]:
        with self._lock:
            out = []
            for pool in (self._hot, self._cold):
                while pool and len(out) < n:
                    i = next(iter(pool))
                    del pool[i]
                    out.append(i)
            return out

    def sizes(self) -> tuple[int, int]:
        with self._lock:
            return len(self._hot), len(self._cold)


class Radar:
    """Moedas promovidas a quentes por um tempo porque apareceram nas listas de mais negociados."""

    def __init__(self, ttl: float = 900.0, clock=time.monotonic):
        self._lock, self._ttl, self._clock = threading.Lock(), ttl, clock
        self._until: dict[int, float] = {}

    def add(self, ids) -> None:
        with self._lock:
            until = self._clock() + self._ttl
            self._until.update({i: until for i in ids})

    def active(self) -> set[int]:
        with self._lock:
            now = self._clock()
            self._until = {i: u for i, u in self._until.items() if u > now}
            return set(self._until)


_queue = AnalysisQueue()
_radar = Radar()
_scout_turn = itertools.count()
_cold_ids: set[int] = set()


def job_market_hot(db):
    global _cold_ids
    hot, cold = split_hot_cold(db, _radar.active())
    budget = get_settings().refresh_cold_requests_per_cycle * MAX_ADDRESSES_PER_REQUEST
    _cold_ids = {t.id for t in cold[:budget]}  # o agente frio pega a mesma fatia, sem repetir as quentes
    touched = refresh_tracked(db, tokens=hot)
    _queue.add(touched, hot=True)
    sync_source_alerts(db, (dexscreener.SOURCE_NAME,))
    return {"tokens": len(hot), "new_data": len(touched)}


def job_market_cold(db):
    ids = _cold_ids
    tokens = list(db.scalars(select(Token).where(Token.id.in_(ids)))) if ids else []
    touched = refresh_tracked(db, tokens=tokens, job="refresh_cold")
    _queue.add(touched, hot=False)
    return {"tokens": len(tokens), "new_data": len(touched)}


def job_analysis(db):
    ids = _queue.take(ANALYSIS_BATCH)
    if not ids:
        return {"analyzed": 0}
    with _analysis_lock:
        analyzed = analyze_tokens(db, ids)
    return {"analyzed": analyzed, "hot_waiting": _queue.sizes()[0], "cold_waiting": _queue.sizes()[1]}


def job_scout(db):
    name = RANKINGS[next(_scout_turn) % 3 * 4 % len(RANKINGS)]  # as janelas de 5 min de cada lista
    ids, added = scout(db, name)
    _radar.add(ids)
    return {"promoted": len(ids), "added": added}


def job_notify(db):
    return {"sent": notify.run_once(db)}


def job_prune(db):
    return {"pruned": prune_inactive(db)}


def _discover_part(part):
    def job(db):
        return {"added": len(discover(db, parts=(part,)))}
    return job


def job_checks(db):
    ids = checks.run_due_checks(db, limit=get_settings().risk_checks_per_cycle)
    _queue.add(ids, hot=True)
    sync_source_alerts(db, (solana_rpc.SOURCE_NAME,))
    return {"checked": len(ids)}


def job_evaluate(db):
    result = {"evaluated": evaluate_due(db), "outcomes_labeled": outcomes.label_due(db)}
    burst.clear_cache()  # estatística do padrão de disparo usa os rótulos novos
    return result


def job_retention(db):
    return {"raw_cleared": apply_raw_retention(db), "snapshots_removed": apply_snapshot_retention(db), "compacted": compact_old_snapshots(db)}


def main() -> None:
    setup_logging()
    s = get_settings()
    lock = WorkerLock(BACKEND_DIR / "data" / "worker.lock")
    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        log.error("%s; encerrando para não duplicar a coleta", exc)
        raise SystemExit(1) from exc
    try:
        _run(s)
    finally:
        lock.release()


def _run(s) -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    schedule = [
        ("market_hot", job_market_hot, s.refresh_interval_seconds),
        ("market_cold", job_market_cold, s.refresh_interval_seconds),
        ("analysis", job_analysis, ANALYSIS_PAUSE),
        ("scout", job_scout, 20),
        ("notify", job_notify, 3),
        ("discover_lists", _discover_part("lists"), s.discovery_interval_seconds),
        ("discover_search", _discover_part("search"), s.discovery_interval_seconds),
        ("discover_gecko", _discover_part("gecko"), 90),
        ("discover_jupiter", _discover_part("jupiter"), s.discovery_interval_seconds),
        ("checks", job_checks, s.risk_check_interval_seconds),
        ("evaluate", job_evaluate, s.evaluation_interval_seconds),
        ("prune", job_prune, 300),
        ("retention", job_retention, 3600),
    ]
    log.info("worker iniciado; redes=%s; limite=%d tokens", s.chain_list, s.max_tracked_tokens)
    agents = [threading.Thread(target=_agent, args=job, name=job[0], daemon=True) for job in schedule]
    for t in agents:
        t.start()
    while _running:
        time.sleep(0.5)
    for t in agents:
        t.join(timeout=20)


def _agent(name: str, fn, interval: float) -> None:
    while _running:
        started = time.monotonic()
        run_job(name, fn, interval)
        while _running and time.monotonic() - started < interval:
            time.sleep(min(0.5, interval))


if __name__ == "__main__":
    main()
