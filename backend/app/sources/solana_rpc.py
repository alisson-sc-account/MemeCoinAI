"""Adaptador JSON-RPC Solana para verificações técnicas do mint SPL.

Métodos usados:
- getAccountInfo (jsonParsed): mintAuthority, freezeAuthority, supply, decimals,
  programa (Token ou Token-2022) e extensões Token-2022.
- getTokenLargestAccounts: 20 maiores CONTAS de token (não proprietários).

O RPC público (api.mainnet-beta.solana.com) tem limites rígidos e não
documentados por método; em 2026-10-28 getTokenLargestAccounts retornou 429.
Configure SOLANA_RPC_URL com um provedor próprio para cobertura confiável.
"""
from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "solana_rpc"
_limiter = RateLimiter(1.5)


class SolanaRpcClient:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        self.client = client or ResilientClient(
            s.solana_rpc_url, timeout=s.http_timeout_seconds, max_attempts=2, backoff_base=2.0
        )
        self._id = 0

    def _call(self, method: str, params: list) -> FetchResult:
        self._id += 1
        res = self.client.request(
            "POST", "", _limiter, json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        )
        if not res.ok:
            return res
        if not isinstance(res.data, dict):
            res.ok, res.error = False, "resposta JSON-RPC inválida"
            return res
        if "error" in res.data:
            err = res.data["error"] or {}
            res.ok = False
            res.error = f"RPC error {err.get('code')}: {err.get('message')}"
            res.rate_limited = err.get("code") == 429
            return res
        res.data = res.data.get("result")
        return res

    def get_mint_account(self, mint: str) -> FetchResult:
        return self._call("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}])

    def get_token_largest_accounts(self, mint: str) -> FetchResult:
        return self._call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
