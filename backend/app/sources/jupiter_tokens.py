"""Listas públicas de tokens da Jupiter (sem chave), usadas só na descoberta.

Verificado em 2026-10-30: /tokens/v2/recent devolve 30 tokens novos e
/tokens/v2/{toptraded|toporganicscore|toptrending}/{janela}?limit=100 devolve 100.
Limite observado: 5 chamadas por 10 s, somando todas as APIs lite da Jupiter.
"""
from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "jupiter_tokens"
RANKINGS = [f"{kind}/{window}" for kind in ("toptraded", "toporganicscore", "toptrending") for window in ("5m", "1h", "6h", "24h")]

_limiter = RateLimiter(5.0)


class JupiterTokensClient:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        self.client = client or ResilientClient(s.jupiter_price_base_url, timeout=s.http_timeout_seconds, max_attempts=1)

    def listing(self, name: str) -> FetchResult:
        path, params = ("/tokens/v2/recent", None) if name == "recent" else (f"/tokens/v2/{name}", {"limit": 100})
        res = self.client.request("GET", path, _limiter, params=params)
        if res.ok and not isinstance(res.data, list):
            res.ok, res.error = False, "formato inesperado (esperava lista)"
        return res
