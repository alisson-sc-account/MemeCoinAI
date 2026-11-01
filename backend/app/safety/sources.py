"""Clientes da RugCheck e do RPC Solana para o subsistema de segurança.

Verificado em 2026-10-30: GET api.rugcheck.xyz/v1/tokens/{mint}/report responde sem chave, com
cabeçalho `x-rate-limit-limit: 15`. `topHolders` inclui a própria pool, que precisa ser excluída.
Carteira sem idade comprovada fica como "sem dado", nunca como nova nem como antiga (ver WalletRpc).
"""
import time

from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

RUGCHECK = "rugcheck"
SIGNATURE_LIMIT = 100
FULL_RPC_PAUSE = 60.0
AMM_TYPES = {"AMM", "LOCKER"}
# Tipos de pool em que `lpLockedPct` indica de fato quem pode retirar a liquidez.
LP_RELIABLE_MARKETS = ("pump_fun_amm", "raydium", "raydium_cpmm", "raydium_clmm")

_rugcheck_limiter = RateLimiter(4.5)
_screen_limiter = RateLimiter(0.25)
_full_limiter = RateLimiter(15.0)


class RugCheckClient:
    def __init__(self, client: ResilientClient | None = None):
        self.client = client or ResilientClient(get_settings().rugcheck_base_url, timeout=12.0, max_attempts=1)

    def report(self, mint: str) -> FetchResult:
        res = self.client.request("GET", f"/tokens/{mint}/report", _rugcheck_limiter)
        if res.ok and not isinstance(res.data, dict):
            res.ok, res.error = False, "formato inesperado"
        return res


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_report(data: dict) -> dict:
    """Extrai o que interessa. A pool e contas conhecidas de AMM saem da lista de donos."""
    markets = [m for m in data.get("markets") or [] if isinstance(m, dict)]
    known = data.get("knownAccounts") if isinstance(data.get("knownAccounts"), dict) else {}
    excluded = {a for a, info in known.items() if isinstance(info, dict) and info.get("type") in AMM_TYPES}
    for m in markets:
        excluded.add(m.get("pubkey"))
        for side in ("liquidityAAccount", "liquidityBAccount"):
            if isinstance(m.get(side), dict):
                excluded.add(m[side].get("owner"))
    holders = []
    for h in data.get("topHolders") or []:
        pct = _num(h.get("pct")) if isinstance(h, dict) else None
        if pct is not None and h.get("owner") and h["owner"] not in excluded and h.get("address") not in excluded:
            holders.append({"owner": h["owner"], "pct": round(pct, 3), "insider": bool(h.get("insider"))})
    lp = None
    if markets:
        main = max(markets, key=lambda m: (_num((m.get("lp") or {}).get("quoteUSD")) or 0))
        lp = {"type": main.get("marketType"), "locked_pct": _num((main.get("lp") or {}).get("lpLockedPct")),
              "reliable": str(main.get("marketType") or "").startswith(LP_RELIABLE_MARKETS)}
    supply = _num((data.get("token") or {}).get("supply")) if isinstance(data.get("token"), dict) else None
    networks = []
    for n in data.get("insiderNetworks") or []:
        if isinstance(n, dict):
            holding = _num(n.get("currentHolding"))
            networks.append({"size": n.get("size"), "type": n.get("type"),
                             "pct": round(holding / supply * 100, 2) if holding is not None and supply else None})
    return {"rugged": bool(data.get("rugged")), "mint_authority": data.get("mintAuthority"),
            "freeze_authority": data.get("freezeAuthority"), "holders": holders, "total_holders": data.get("totalHolders"),
            "lp": lp, "networks": networks, "insiders_detected": _num(data.get("graphInsidersDetected")) or 0,
            "risks": [{"name": r.get("name"), "level": r.get("level")} for r in data.get("risks") or [] if isinstance(r, dict)],
            "score_normalised": _num(data.get("score_normalised"))}


class WalletRpc:
    """Idade da carteira em duas etapas, porque nenhum RPC grátis faz tudo:

    1. Triagem no publicnode (rápido, sem chave, mas só ~63 h de histórico, medido em 2026-10-30):
       nenhuma transação na janela = carteira parada há mais tempo que isso, logo NÃO é nova;
       `SIGNATURE_LIMIT` ou mais = carteira muito ativa, começo desconhecido.
    2. Poucas transações na janela pode ser carteira nova OU velha que voltou. Só o RPC oficial tem o
       histórico completo, e ele responde 429 em poucas chamadas deste método: uma a cada ~15 s, e
       pausa pelo tempo que ele pedir. Sem confirmação fica desconhecida, nunca conta como nova.
    """

    def __init__(self, screen: ResilientClient | None = None, full: ResilientClient | None = None, clock=time.monotonic):
        s = get_settings()
        self.screen = screen or ResilientClient(s.solana_history_rpc_url, timeout=8.0, max_attempts=1)
        self.full = full or ResilientClient(s.solana_rpc_url, timeout=10.0, max_attempts=1)
        self._clock = clock
        self._full_paused_until = 0.0

    @staticmethod
    def _call(client: ResilientClient, limiter: RateLimiter, method: str, params: list) -> FetchResult:
        res = client.request("POST", "", limiter, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if res.ok:
            if isinstance(res.data, dict) and "result" in res.data:
                res.data = res.data["result"]
            else:
                res.ok, res.error = False, "RPC sem resultado"
        return res

    def profile(self, address: str) -> dict | None:
        """{first_seen_ts, signatures, complete, funder}. `complete` = resultado definitivo. None = RPC falhou."""
        params = [address, {"limit": SIGNATURE_LIMIT}]
        res = self._call(self.screen, _screen_limiter, "getSignaturesForAddress", params)
        if not res.ok or not isinstance(res.data, list):
            return None
        if not res.data:  # parada desde antes da janela: não é nova
            return {"first_seen_ts": None, "signatures": 0, "complete": True, "funder": None}
        candidate = {"first_seen_ts": None, "signatures": len(res.data), "complete": False, "funder": None}
        if len(res.data) >= SIGNATURE_LIMIT or self._clock() < self._full_paused_until:
            return candidate
        confirm = self._call(self.full, _full_limiter, "getSignaturesForAddress", params)
        if confirm.rate_limited or not confirm.ok or not isinstance(confirm.data, list) or not confirm.data:
            self._full_paused_until = self._clock() + FULL_RPC_PAUSE
            return candidate
        if len(confirm.data) >= SIGNATURE_LIMIT:
            return {**candidate, "signatures": len(confirm.data)}
        oldest = confirm.data[-1]
        out = {"first_seen_ts": oldest.get("blockTime"), "signatures": len(confirm.data), "complete": True, "funder": None}
        tx = self._call(self.screen, _screen_limiter, "getTransaction", [oldest.get("signature"), {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if tx.ok and isinstance(tx.data, dict):
            keys = ((tx.data.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
            payer = keys[0].get("pubkey") if keys and isinstance(keys[0], dict) else None
            out["funder"] = payer if payer != address else None
        return out
