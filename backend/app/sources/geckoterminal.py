"""Adaptador da API pública do GeckoTerminal (sem chave), usado só na descoberta.

Verificado em 2026-10-30: /networks/{rede}/new_pools e /trending_pools respondem 200 com
20 pools por página; a página 11 responde 401 (máximo de 10 páginas sem chave).
Traz pools novas sem o viés das listas pagas do DEX Screener. Limite: 30 req/min.
"""
from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "geckoterminal"
MAX_PAGES = 10

_limiter = RateLimiter(60 / 28)  # margem abaixo de 30/min


class GeckoTerminalClient:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        self.client = client or ResilientClient(s.geckoterminal_base_url, timeout=s.http_timeout_seconds, max_attempts=2)

    def pools(self, network: str, kind: str, page: int) -> FetchResult:
        """`kind`: "new_pools" ou "trending_pools". Devolve a lista bruta de pools."""
        res = self.client.request("GET", f"/networks/{network}/{kind}", _limiter, params={"page": page})
        if res.ok:
            data = res.data.get("data") if isinstance(res.data, dict) else None
            if isinstance(data, list):
                res.data = data
            else:
                res.ok, res.error = False, "formato inesperado (sem campo data)"
        return res


def parse_pool(pool, network: str) -> tuple[str, float | None] | None:
    """(mint do token-base, liquidez em US$) de uma pool; None se o formato não bater."""
    if not isinstance(pool, dict):
        return None
    base_id = (((pool.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id")
    prefix = f"{network}_"
    if not isinstance(base_id, str) or not base_id.startswith(prefix):
        return None
    try:
        liq = float((pool.get("attributes") or {}).get("reserve_in_usd"))
    except (TypeError, ValueError):
        liq = None
    return base_id[len(prefix):], liq
