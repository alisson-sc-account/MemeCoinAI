"""Processo contínuo de coleta e análise.

Execução: `python -m app.worker` (um único processo por banco).
Não é adequado para funções serverless: precisa de processo de longa duração.
Cada job captura suas próprias falhas; uma fonte fora do ar não derruba o loop.
"""
import logging
import signal
import time

from app.config import get_settings
from app.db import session_factory
from app.engine import checks
from app.engine.pipeline import analyze_tokens, sync_source_alerts
from app.engine.predict import evaluate_due
from app.ingest.service import discover, refresh_tracked
from app.logging_setup import setup_logging
from app.sources import dexscreener, solana_rpc

log = logging.getLogger("worker")
_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("sinal de parada recebido; encerrando após o job atual")


def run_job(name: str, fn) -> None:
    t0 = time.perf_counter()
    db = session_factory()()
    try:
        result = fn(db)
        log.info("job=%s ok duração=%.1fs resultado=%s", name, time.perf_counter() - t0, result)
    except Exception:
        db.rollback()
        log.exception("job=%s falhou", name)
    finally:
        db.close()


def job_discover(db):
    added = discover(db)
    return {"added": len(added)}


def job_refresh(db):
    touched = refresh_tracked(db)
    analyzed = analyze_tokens(db, touched)
    sync_source_alerts(db, (dexscreener.SOURCE_NAME,))
    return {"tokens_with_new_data": len(touched), "analyses_persisted": analyzed}


def job_checks(db):
    ids = checks.run_due_checks(db, limit=2)
    analyzed = analyze_tokens(db, ids)
    sync_source_alerts(db, (solana_rpc.SOURCE_NAME,))
    return {"checked": len(ids), "analyses_persisted": analyzed}


def job_evaluate(db):
    return {"evaluated": evaluate_due(db)}


def main() -> None:
    setup_logging()
    s = get_settings()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    schedule = [
        ("discover", job_discover, s.discovery_interval_seconds),
        ("refresh", job_refresh, s.refresh_interval_seconds),
        ("checks", job_checks, s.risk_check_interval_seconds),
        ("evaluate", job_evaluate, s.evaluation_interval_seconds),
    ]
    last_run = {name: 0.0 for name, _, _ in schedule}
    log.info("worker iniciado; redes=%s", s.chain_list)
    while _running:
        now = time.monotonic()
        for name, fn, interval in schedule:
            if not _running:
                break
            if now - last_run[name] >= interval:
                run_job(name, fn)
                last_run[name] = time.monotonic()
        time.sleep(1)


if __name__ == "__main__":
    main()
