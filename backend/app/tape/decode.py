"""Decodifica os eventos de negociação das linhas `Program data:` dos logs da Solana."""
import base64
import binascii
import struct
from dataclasses import dataclass

from app.live.chain import b58encode

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_TRADE = bytes.fromhex("bddb7fd34ee661ee")
SWAP_BUY = bytes.fromhex("67f4521f2cf57777")
SWAP_SELL = bytes.fromhex("3e2f370aa503dc2a")
LINE_PREFIX = "Program data: "
# Início em base64 dos 3 eventos: evita decodificar JSON de milhares de transações que não são negociação.
QUICK_MARKS = ("vdt/007mYe", "Z/RSHyz1d3", "Pi83CqUD3C")
TOKEN_DECIMALS, SOL_DECIMALS = 6, 9


@dataclass(frozen=True)
class Trade:
    is_buy: bool
    sol: float
    price_native: float  # preço em SOL
    user: str
    mint: str | None = None  # pump.fun informa a moeda
    pool: str | None = None  # PumpSwap informa a pool


def _price(sol_raw: int, token_raw: int) -> float | None:
    if not sol_raw or not token_raw:
        return None
    return (sol_raw / 10 ** SOL_DECIMALS) / (token_raw / 10 ** TOKEN_DECIMALS)


def decode_event(raw: bytes) -> Trade | None:
    head = raw[:8]
    if head == PUMP_TRADE and len(raw) >= 113:
        sol, tokens = struct.unpack_from("<QQ", raw, 40)
        price = _price(sol, tokens)
        return Trade(raw[56] == 1, sol / 10 ** SOL_DECIMALS, price, b58encode(raw[57:89]), mint=b58encode(raw[8:40])) if price else None
    if head in (SWAP_BUY, SWAP_SELL) and len(raw) >= 184:
        base, = struct.unpack_from("<Q", raw, 16)
        quote, = struct.unpack_from("<Q", raw, 64)
        price = _price(quote, base)
        return Trade(head == SWAP_BUY, quote / 10 ** SOL_DECIMALS, price, b58encode(raw[152:184]), pool=b58encode(raw[120:152])) if price else None
    return None


def decode_logs(logs: list[str]) -> list[Trade]:
    out = []
    for line in logs:
        if line.startswith(LINE_PREFIX):
            try:
                trade = decode_event(base64.b64decode(line[len(LINE_PREFIX):]))
            except (binascii.Error, struct.error, ValueError):
                continue
            if trade:
                out.append(trade)
    return out
