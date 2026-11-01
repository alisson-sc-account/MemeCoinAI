"""Processo da atualização rápida: `python -m app.live` (um por banco, trava própria).

Ritmo fixo de `live_interval_seconds` (10 s) medido pelo relógio, não "10 s depois do
fim do ciclo anterior", para não escorregar. Entre um ciclo e outro, a cada ~1 s,
cota na hora qualquer quadro que acabou de abrir, para não esperar o próximo ciclo.
A moeda aberta tem pista própria: a cada ~1 s lê as reservas da pool na blockchain.
"""
import logging
import signal
import time

from app.config import BACKEND_DIR, get_settings
from app.db import session_factory
from app.live import service
from app.live.jupiter import JupiterPriceClient
from app.logging_setup import setup_logging
from app.worker_lock import WorkerAlreadyRunning, WorkerLock

log = logging.getLogger("live")
PRUNE_EVERY = 600.0
_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("sinal de parada recebido; encerrando a atualização rápida")


def _with_session(fn):
    db = session_factory()()
    try:
        return fn(db)
    except Exception:
        db.rollback()
        log.exception("atualização rápida: falha no passo %s", getattr(fn, "__name__", "?"))
        return None
    finally:
        db.close()


def main() -> None:
    setup_logging()
    lock = WorkerLock(BACKEND_DIR / "data" / "live.lock")
    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        log.error("%s; já existe uma atualização rápida rodando", exc)
        raise SystemExit(1) from exc
    try:
        _run()
    finally:
        lock.release()


def _run() -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    s = get_settings()
    interval = float(s.live_interval_seconds)
    client = JupiterPriceClient()
    _with_session(lambda db: service.beat(db, interval=s.live_interval_seconds, started=True))
    log.info("atualização rápida iniciada: a cada %.0f s, fonte %s", interval, client.client._client.base_url)
    known: set[int] = set()
    focus = service.FocusLane()
    next_focus = time.monotonic()
    next_full = time.monotonic()
    next_prune = time.monotonic() + PRUNE_EVERY
    while _running:
        now = time.monotonic()
        if now >= next_full:
            def full(db):
                tokens = service.watched_tokens(db)
                known.clear()
                known.update(t.id for t in tokens)
                return service.tick(db, client, tokens)
            r = _with_session(full)
            if r and (r["watched"] or r["errors"]):
                log.info("ciclo rápido: %s", r)
            next_full += interval
            if next_full <= time.monotonic():  # atrasou (fonte lenta): recomeça o ritmo a partir de agora
                next_full = time.monotonic() + interval
        else:
            def fresh(db):
                new = [t for t in service.watched_tokens(db) if t.id not in known]
                if not new:
                    return None
                known.update(t.id for t in new)
                return service.tick(db, client, new, record=False)
            r = _with_session(fresh)
            if r:
                log.info("quadro novo cotado na hora: %s", r)
        if now >= next_focus:
            def fast(db):
                tokens = service.focused_tokens(db)
                return focus.tick(db, tokens) if tokens else None
            r = _with_session(fast)
            # RPC negou: recua um pouco em vez de insistir.
            next_focus = time.monotonic() + (3.0 if r and r["error"] else 1.0)
            if r and r["error"]:
                log.warning("leitura na blockchain: %s", r["error"])
        if now >= next_prune:
            _with_session(service.prune)
            next_prune = now + PRUNE_EVERY
        time.sleep(min(0.25, max(0.05, next_full - time.monotonic())))


if __name__ == "__main__":
    main()
