"""Adaptador da API pública do DEX Screener (sem autenticação).

Endpoints usados (verificados em 2026-10-28 com requisições reais):
- GET /tokens/v1/{chainId}/{addr1,addr2,...}   até 30 endereços; pares dos tokens
- GET /latest/dex/search?q=...                  busca textual
- GET /token-profiles/latest/v1                 perfis recentes (descoberta)
- GET /token-boosts/latest/v1                   tokens impulsionados (descoberta)

Limites documentados pela fonte: 300 req/min para pares/tokens/busca e
60 req/min para profiles/boosts. As respostas têm Cache-Control max-age=60,
logo os dados podem ter até ~60 s de atraso. A fonte NÃO informa horário por
registro: `source_time` fica nulo e usamos `received_at`.
"""
from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "dexscreener"
MAX_ADDRESSES_PER_REQUEST = 30

_fast_limiter = RateLimiter(60 / 280)  # margem abaixo de 300/min
_slow_limiter = RateLimiter(60 / 55)  # margem abaixo de 60/min


class DexScreenerClient:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        self.client = client or ResilientClient(s.dexscreener_base_url, timeout=s.http_timeout_seconds)

    def tokens(self, chain_id: str, addresses: list[str]) -> FetchResult:
        if not addresses:
            return FetchResult(ok=True, data=[])
        if len(addresses) > MAX_ADDRESSES_PER_REQUEST:
            raise ValueError(f"máximo de {MAX_ADDRESSES_PER_REQUEST} endereços por requisição")
        res = self.client.request("GET", f"/tokens/v1/{chain_id}/{','.join(addresses)}", _fast_limiter)
        if res.ok and not isinstance(res.data, list):
            res.ok, res.error = False, "formato inesperado (esperava lista de pares)"
        return res

    def search(self, query: str) -> FetchResult:
        res = self.client.request("GET", "/latest/dex/search", _fast_limiter, params={"q": query})
        if res.ok:
            pairs = res.data.get("pairs") if isinstance(res.data, dict) else None
            if not isinstance(pairs, list):
                res.ok, res.error = False, "formato inesperado (sem campo pairs)"
            else:
                res.data = pairs
        return res

    def latest_profiles(self) -> FetchResult:
        return self._list("/token-profiles/latest/v1")

    def latest_boosts(self) -> FetchResult:
        return self._list("/token-boosts/latest/v1")

    def top_boosts(self) -> FetchResult:
        return self._list("/token-boosts/top/v1")

    def _list(self, path: str) -> FetchResult:
        res = self.client.request("GET", path, _slow_limiter)
        if res.ok and not isinstance(res.data, list):
            res.ok, res.error = False, "formato inesperado (esperava lista)"
        return res
