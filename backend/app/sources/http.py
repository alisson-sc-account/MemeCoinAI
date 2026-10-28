"""Cliente HTTP resiliente compartilhado pelos adaptadores de fonte.

- Espaçamento mínimo entre requisições (limite de uso por fonte).
- Retries com backoff exponencial para erros transitórios (timeout, 5xx, 429).
- Nunca entra em loop infinito: número máximo de tentativas fixo.
- Mede latência e devolve um resultado explícito em vez de levantar exceção.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    ok: bool
    data: Any = None
    status_code: int | None = None
    latency_ms: float | None = None
    error: str | None = None
    rate_limited: bool = False
    attempts: int = 0
    latencies: list[float] = field(default_factory=list)


class RateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class ResilientClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        max_attempts: int = 3,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "MemeCoinAI/0.1"},
        )
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self._sleep = sleep

    def request(
        self,
        method: str,
        path: str,
        limiter: RateLimiter | None = None,
        **kwargs,
    ) -> FetchResult:
        result = FetchResult(ok=False)
        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt
            if limiter:
                limiter.wait()
            t0 = time.perf_counter()
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                result.latencies.append((time.perf_counter() - t0) * 1000)
                result.error = f"{type(exc).__name__}: {exc}"
                log.warning("http error %s %s (tentativa %d): %s", method, path, attempt, result.error)
                self._backoff(attempt)
                continue
            elapsed = (time.perf_counter() - t0) * 1000
            result.latencies.append(elapsed)
            result.latency_ms = elapsed
            result.status_code = resp.status_code
            if resp.status_code == 429:
                result.rate_limited = True
                result.error = "rate limited (HTTP 429)"
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                self._backoff(attempt, retry_after)
                continue
            if resp.status_code >= 500:
                result.error = f"HTTP {resp.status_code}"
                self._backoff(attempt)
                continue
            if resp.status_code >= 400:
                result.error = f"HTTP {resp.status_code}"
                return result  # erro do cliente não é transitório
            try:
                result.data = resp.json()
            except ValueError:
                result.error = "resposta não é JSON válido"
                return result
            result.ok = True
            result.error = None
            return result
        return result

    def _backoff(self, attempt: int, retry_after: float | None = None) -> None:
        if attempt >= self.max_attempts:
            return
        delay = retry_after if retry_after is not None else self.backoff_base * (2 ** (attempt - 1))
        self._sleep(min(delay, 30.0))

    def close(self) -> None:
        self._client.close()


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
