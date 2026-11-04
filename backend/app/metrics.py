"""Medições leves de tempo e contagem, por processo, sem dependência nova.

Cada processo guarda em memória as últimas `SAMPLE_SIZE` medições de cada nome (amostra limitada, nunca cresce)
e, no máximo a cada `FLUSH_SECONDS`, grava um resumo em `data/metrics/<processo>.json` (troca atômica do arquivo).
A API lê esses arquivos em `/system/metrics`. Percentis só aparecem com amostra suficiente:
p50/p90 com 20+ medições, p95 com 100+, p99 com 300+; abaixo disso vêm como null.

Durações usam relógio monotônico dentro do processo; idades entre processos usam UTC do banco.
Nada aqui pode derrubar quem mede: qualquer erro ao gravar é ignorado.
"""
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

from app.config import BACKEND_DIR

SAMPLE_SIZE = 500
FLUSH_SECONDS = 10.0
_lock = threading.Lock()
_samples: dict[str, deque] = {}
_counters: dict[str, int] = {}
_gauges: dict[str, float] = {}
_state = {"process": None, "started": time.time(), "flushed": 0.0, "folder": None}


def folder() -> Path:
    return _state["folder"] or BACKEND_DIR / "data" / "metrics"


def set_folder(path: Path | None) -> None:
    """Usado pelos testes para não gravar no `data/` real."""
    _state["folder"] = path


def init(process: str) -> None:
    _state["process"] = process


def _process() -> str:
    if _state["process"]:
        return _state["process"]
    name = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "proc"
    return f"{name}-{os.getpid()}"


def observe(name: str, value: float) -> None:
    with _lock:
        d = _samples.get(name)
        if d is None:
            d = _samples[name] = deque(maxlen=SAMPLE_SIZE)
        d.append(float(value))
    _maybe_flush()


def incr(name: str, n: int = 1) -> None:
    with _lock:
        _counters[name] = _counters.get(name, 0) + n
    _maybe_flush()


def gauge(name: str, value: float) -> None:
    with _lock:
        _gauges[name] = float(value)
    _maybe_flush()


def _pct(sorted_vals: list[float], q: float, min_n: int) -> float | None:
    if len(sorted_vals) < min_n:
        return None
    return round(sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))], 1)


def summary() -> dict:
    with _lock:
        samples = {k: sorted(v) for k, v in _samples.items()}
        counters, gauges = dict(_counters), dict(_gauges)
    timings = {}
    for k, v in samples.items():
        if v:
            timings[k] = {"n": len(v), "p50": _pct(v, 0.50, 20), "p90": _pct(v, 0.90, 20), "p95": _pct(v, 0.95, 100),
                          "p99": _pct(v, 0.99, 300), "max": round(v[-1], 1), "mean": round(sum(v) / len(v), 1)}
    return {"process": _process(), "pid": os.getpid(), "started_at": _state["started"], "updated_at": time.time(),
            "sample_size": SAMPLE_SIZE, "timings_ms": timings, "counters": counters, "gauges": gauges}


def _maybe_flush(force: bool = False) -> None:
    now = time.monotonic()
    if not force and now - _state["flushed"] < FLUSH_SECONDS:
        return
    _state["flushed"] = now
    try:
        out = folder()
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{_process()}.json"
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(summary()), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


def flush() -> None:
    _maybe_flush(force=True)


def read_all(max_age_seconds: float = 3600.0) -> list[dict]:
    """Resumos gravados pelos processos (só os atualizados há menos de `max_age_seconds`)."""
    out = []
    path = folder()
    if not path.exists():
        return out
    now = time.time()
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if now - data.get("updated_at", 0) <= max_age_seconds:
            data["age_seconds"] = round(now - data["updated_at"], 1)
            out.append(data)
    return out


def reset() -> None:
    with _lock:
        _samples.clear()
        _counters.clear()
        _gauges.clear()
    _state["flushed"] = 0.0


class timer:
    """`with metrics.timer("nome"):` mede em ms com relógio monotônico."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        observe(self.name, (time.perf_counter() - self.t0) * 1000)
        return False
