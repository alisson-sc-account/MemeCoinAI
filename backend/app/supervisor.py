"""Mantém o sistema de pé: `python -m app.supervisor`.

Abre todos os programas numa janela só e guarda a saída em `data/logs/`. Se um cair, reinicia e avisa no
celular. Se o coletor travar sem cair (agente de mercado sem bater há 5 min), reinicia também. Faz cópia
do banco ao ligar se a última for antiga, a cada 6 h e ao desligar.
"""
import argparse
import logging
import signal
import subprocess
import sys
import time
from datetime import timedelta

from app import backup, notify
from app.config import BACKEND_DIR
from app.db import session_factory, utcnow
from app.logging_setup import setup_logging
from app.models import ServiceHeartbeat

log = logging.getLogger("supervisor")
CHECK_SECONDS = 5.0
BACKUP_HOURS = 6.0
STALL_LIMIT = timedelta(minutes=5)
STARTUP_GRACE = 180.0
MAX_BACKOFF = 60.0
RESTART_WARN_EVERY = 300.0
LOG_MAX_BYTES = 50 * 1024 * 1024
_running = True


class Child:
    def __init__(self, name: str, args: list[str]):
        self.name, self.args = name, args
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.restarts = 0
        self.next_start = 0.0
        self.warned = 0.0

    def start(self) -> None:
        folder = BACKEND_DIR / "data" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.name}.log"
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            path.replace(path.with_suffix(".old.log"))
        with open(path, "ab") as out:
            self.proc = subprocess.Popen([sys.executable, *self.args], cwd=BACKEND_DIR, stdout=out, stderr=subprocess.STDOUT)
        self.started = time.monotonic()
        log.info("%s iniciado (PID %s)", self.name, self.proc.pid)

    def stop(self) -> None:
        """Encerra o processo e os filhos. No Windows o python do .venv abre um segundo processo: matar só o
        primeiro deixava o filho vivo, segurando a trava, e o reinício nunca acontecia."""
        if not self.proc or self.proc.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
        else:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def backoff(restarts: int) -> float:
    return min(MAX_BACKOFF, 2.0 ** restarts)


def collector_stalled(now=None) -> bool:
    db = session_factory()()
    try:
        hb = db.get(ServiceHeartbeat, "market_hot")
        return bool(hb and hb.last_tick_at and (now or utcnow()) - hb.last_tick_at > STALL_LIMIT)
    except Exception:
        log.exception("não consegui ler o batimento do coletor")
        return False
    finally:
        db.close()


def keep_awake(on: bool) -> None:
    """Impede o Windows de dormir por inatividade enquanto o sistema roda (tela pode apagar). Desfaz ao sair.
    Com o PC dormindo a coleta para e os dados envelhecem: foi o que deixou o coletor 12 h parado."""
    if sys.platform != "win32":
        return
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def _stop(*_):
    global _running
    _running = False


def _safe_backup() -> None:
    try:
        backup.make_backup()
    except Exception:
        log.exception("cópia do banco falhou")


def main() -> None:
    setup_logging()
    folder = BACKEND_DIR / "data" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(folder / "supervisor.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    keep_awake(True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    children = [
        Child("worker", ["-m", "app.worker"]), Child("live", ["-m", "app.live"]), Child("tape", ["-m", "app.tape"]),
        Child("safety", ["-m", "app.safety"]), Child("board", ["-m", "app.board"]),
        Child("api", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--workers", "2"]),  # 2 processos: uma tela pesada não trava as outras
    ]
    age = backup.newest_age_hours()
    if age is None or age > 1:
        _safe_backup()
    last_backup = time.monotonic()
    for c in children:
        c.start()
    print(f"\nMemeCoinAI rodando: abra http://127.0.0.1:{args.port}\nPara desligar e salvar: stop.bat ou Ctrl+C aqui.\n", flush=True)
    last_wall = time.time()
    try:
        while _running:
            now = time.monotonic()
            # Voltou de suspensão (relógio pulou): conexões e travas antigas podem estar mortas; reinicia tudo.
            if time.time() - last_wall > 120:
                log.warning("o computador voltou de uma suspensão: reiniciando os programas")
                for c in children:
                    c.stop()
                    c.next_start = 0.0
            last_wall = time.time()
            for c in children:
                if c.proc is not None and c.proc.poll() is None:
                    if now - c.started > 300:
                        c.restarts = 0
                    continue
                if c.proc is not None:
                    log.warning("%s parou (código %s)", c.name, c.proc.returncode)
                    c.next_start = now + backoff(c.restarts)
                    c.restarts += 1
                    c.proc = None
                    if now - c.warned > RESTART_WARN_EVERY:
                        c.warned = now
                        notify.send("MemeCoinAI: programa caiu", f"{c.name} parou e está sendo reiniciado.", priority="default")
                if now >= c.next_start:
                    c.start()
            worker = children[0]
            if worker.proc and now - worker.started > STARTUP_GRACE and collector_stalled():
                log.warning("coletor travado: reiniciando")
                worker.stop()
            if now - last_backup > BACKUP_HOURS * 3600:
                _safe_backup()
                last_backup = now
            time.sleep(CHECK_SECONDS)
    finally:
        for c in reversed(children):
            c.stop()
        keep_awake(False)
        _safe_backup()
        log.info("sistema desligado")


if __name__ == "__main__":
    main()
