"""Adaptador da Jupiter Price API v3 (pública, sem chave).

Endpoint usado (verificado em 2026-10-29 com requisições reais a cada 10 s):
- GET https://lite-api.jup.ag/price/v3?ids=mint1,mint2,...   até 50 mints por requisição

Resposta: objeto {mint: {usdPrice, liquidity, blockId, decimals, priceChange24h, createdAt}}.
Mints sem preço simplesmente não aparecem. `Cache-Control: max-age=5`: o preço muda
entre consultas de 10 s (o bloco `blockId` avança). `liquidity` é a liquidez somada de
todas as pools do token, por isso não é comparável à liquidez do par no DEX Screener.
Limite de uso não documentado na resposta de forma clara: a fast lane faz 1 requisição
a cada 10 s por bloco de 50 tokens e respeita HTTP 429 (o cliente recua sozinho).
"""
from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "jupiter_price"
MAX_IDS_PER_REQUEST = 50

_limiter = RateLimiter(1.0)


class JupiterPriceClient:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        # Poucas tentativas: uma cotação de 10 s atrás não vale esperar backoff longo.
        self.client = client or ResilientClient(s.jupiter_price_base_url, timeout=8.0, max_attempts=2)

    def prices(self, mints: list[str]) -> FetchResult:
        if not mints:
            return FetchResult(ok=True, data={})
        if len(mints) > MAX_IDS_PER_REQUEST:
            raise ValueError(f"máximo de {MAX_IDS_PER_REQUEST} mints por requisição")
        res = self.client.request("GET", "/price/v3", _limiter, params={"ids": ",".join(mints)})
        if res.ok and not isinstance(res.data, dict):
            res.ok, res.error = False, "formato inesperado (esperava objeto por mint)"
        return res


def parse_quote(item) -> dict | None:
    """Extrai preço/liquidez/bloco; devolve None se o preço não for um número positivo."""
    if not isinstance(item, dict):
        return None
    price = item.get("usdPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    liq = item.get("liquidity")
    block = item.get("blockId")
    return {"price_usd": float(price),
            "liquidity_usd": float(liq) if isinstance(liq, (int, float)) and not isinstance(liq, bool) else None,
            "block_id": block if isinstance(block, int) and not isinstance(block, bool) else None}
