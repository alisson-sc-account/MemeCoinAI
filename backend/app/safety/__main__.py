"""Processo de segurança: `python -m app.safety` (um por banco, trava própria).

Verifica uma moeda por vez, na ordem de `service.next_target`, respeitando o limite da RugCheck.
"""
import logging
import signal
import time

from app.config import BACKEND_DIR
from app.db import session_factory
from app.logging_setup import setup_logging
from app.safety import service
from app.safety.sources import RugCheckClient, WalletRpc
from app.worker_lock import WorkerAlreadyRunning, WorkerLock

log = logging.getLogger("security")
IDLE_SECONDS = 2.0
_running = True


def _stop(*_):
    global _running
    _running = False


def main() -> None:
    setup_logging()
    lock = WorkerLock(BACKEND_DIR / "data" / "security.lock")
    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        log.error("%s; já existe uma verificação de segurança rodando", exc)
        raise SystemExit(1) from exc
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    client, rpc = RugCheckClient(), WalletRpc()
    log.info("verificação de segurança iniciada")
    try:
        while _running:
            db = session_factory()()
            try:
                target = service.next_target(db)
                if target:
                    report = service.scan(db, target[0], target[1], client, rpc)
                    log.info("%s: %s", target[0].symbol or target[0].address[:8], report.verdict)
                service.beat(db, (report.facts.get("rugcheck_error") if target else None))
            except Exception:
                db.rollback()
                log.exception("falha na verificação de segurança")
            finally:
                db.close()
            if not target:
                time.sleep(IDLE_SECONDS)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
