"""Preço em tempo real lido direto das reservas da pool na Solana (RPC público, sem chave).

É a única fonte grátis que muda de verdade a cada ~1 s: DEX Screener segura o preço por
~30 s e a Jupiter limita a 5 chamadas por 10 s (cache de 5 s).

Suporta pools de produto constante: pump.fun (curva), PumpSwap, Raydium CPMM e Raydium AMM v4.
O par de reservas é verificado (o mint de um dos cofres precisa ser o token); o resto cai na
cotação de 10 s. A razão bruta das reservas nem sempre é o preço exibido pelas fontes (decimais,
reservas virtuais), por isso o preço é CALIBRADO: k = preço de referência / razão, e depois só
a variação das reservas move o preço. Reservas quase vazias são recusadas, nunca mostradas.
"""
import base64
import struct
from dataclasses import dataclass

from app.config import get_settings
from app.sources.http import FetchResult, RateLimiter, ResilientClient

SOURCE_NAME = "solana_pool"
WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MIN_QUOTE_RAW = 1_000_000  # abaixo disso a pool está vazia: razão sem sentido
PUMP_CURVE_OWNER = "6EF8rrec"
VAULT_OFFSETS = {"pAMMBay6": (139, 171), "CPMMoo8L": (72, 104), "675kPX9M": (336, 368)}  # dono da pool (início)
MAX_ACCOUNTS = 100

_limiter = RateLimiter(0.25)
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def _decode(account: dict | None) -> bytes | None:
    try:
        return base64.b64decode(account["data"][0])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def parse_curve(raw: bytes | None) -> dict | None:
    """Curva do pump.fun: [8 disc][virtual_token][virtual_sol][real_token][real_sol][supply][complete]."""
    if not raw or len(raw) < 49 or raw[48] != 0:  # complete: migrou, a curva não é mais o preço
        return None
    virtual_token, virtual_sol, _, real_sol = struct.unpack("<4Q", raw[8:40])
    if not virtual_token or virtual_sol < MIN_QUOTE_RAW:
        return None
    return {"ratio": virtual_sol / virtual_token, "quote_raw": real_sol, "quote_mint": WSOL}


def parse_vaults(a: bytes | None, b: bytes | None, token: str) -> dict | None:
    """Cofres (contas de token): [32 mint][32 dono][8 quantidade]."""
    if not a or not b or len(a) < 72 or len(b) < 72:
        return None
    vaults = [(b58encode(x[:32]), struct.unpack("<Q", x[64:72])[0]) for x in (a, b)]
    base = next((v for v in vaults if v[0] == token), None)
    quote = next((v for v in vaults if v[0] != token), None)
    if base is None or quote is None or not base[1] or quote[1] < MIN_QUOTE_RAW:
        return None
    return {"ratio": quote[1] / base[1], "quote_raw": quote[1], "quote_mint": quote[0]}


@dataclass
class PoolRef:
    kind: str  # "curve" | "vaults"
    accounts: list[str]


class SolanaPoolReader:
    def __init__(self, client: ResilientClient | None = None):
        s = get_settings()
        self.client = client or ResilientClient(s.solana_rpc_url, timeout=4.0, max_attempts=1)

    def _accounts(self, addresses: list[str]) -> FetchResult:
        body = {"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                "params": [addresses, {"encoding": "base64", "commitment": "processed"}]}
        res = self.client.request("POST", "", _limiter, json=body)
        if res.ok:
            value = ((res.data or {}).get("result") or {}).get("value") if isinstance(res.data, dict) else None
            if isinstance(value, list):
                res.data = value
            else:
                res.ok, res.error = False, "RPC sem resultado"
        return res

    def resolve(self, pair_address: str, token: str) -> PoolRef | None:
        """Descobre onde estão as reservas de uma pool. None = não suportada: usa a cotação de 10 s."""
        res = self._accounts([pair_address])
        account = res.data[0] if res.ok and res.data else None
        if not account:
            return None
        owner, raw = str(account.get("owner", "")), _decode(account)
        if owner.startswith(PUMP_CURVE_OWNER):
            return PoolRef("curve", [pair_address]) if parse_curve(raw) else None
        offsets = next((o for prefix, o in VAULT_OFFSETS.items() if owner.startswith(prefix)), None)
        if offsets is None or raw is None or len(raw) < offsets[1] + 32:
            return None
        vaults = [b58encode(raw[o:o + 32]) for o in offsets]
        check = self._accounts(vaults)
        if not check.ok or len(check.data) != 2 or not all(check.data):
            return None
        return PoolRef("vaults", vaults) if parse_vaults(_decode(check.data[0]), _decode(check.data[1]), token) else None

    def read(self, pools: dict[int, tuple[PoolRef, str]]) -> tuple[dict[int, dict], str | None]:
        """Lê todas as pools numa só chamada. Devolve {token_id: reservas} e o erro, se houver."""
        addresses = [a for ref, _ in pools.values() for a in ref.accounts][:MAX_ACCOUNTS]
        if not addresses:
            return {}, None
        res = self._accounts(addresses)
        if not res.ok:
            return {}, res.error or "falha no RPC"
        by_address = dict(zip(addresses, res.data))
        out = {}
        for token_id, (ref, token) in pools.items():
            raws = [_decode(by_address.get(a)) for a in ref.accounts]
            parsed = parse_curve(raws[0]) if ref.kind == "curve" else parse_vaults(raws[0], raws[1], token) if len(raws) == 2 else None
            if parsed:
                out[token_id] = parsed
        return out, None


def liquidity_usd(reserves: dict, sol_usd: float | None) -> float | None:
    """Liquidez em US$: lado da cotação em dobro. Só para pools em SOL ou USDC."""
    if reserves["quote_mint"] == WSOL and sol_usd:
        return reserves["quote_raw"] / 1e9 * sol_usd * 2
    if reserves["quote_mint"] == USDC:
        return reserves["quote_raw"] / 1e6 * 2
    return None
