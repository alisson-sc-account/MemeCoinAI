"""Livro das negociações recentes por moeda. Sem rede e sem banco: regra pura, fácil de testar.

O Disparo usa a mesma função `burst.detect` do resto do sistema, só que com os 5 minutos reais em vez
do dado do DEX Screener, que chega com ~30 a 60 s de atraso. O volume da última hora e a liquidez ainda
vêm da última coleta: a negociação ao vivo não cobre outras pools.
"""
from collections import deque
from dataclasses import dataclass, field

from app.engine import burst
from app.tape.decode import Trade

WINDOW_SECONDS = 300.0
FLOW_SECONDS = 30.0
COOLDOWN_SECONDS = 900.0
MIN_HISTORY_SECONDS = 60.0  # recém-ligado: janela curta demais para comparar
MAX_PRICE_GAP = 10.0  # preço 10x diferente da coleta: pool invertida ou decimais diferentes


@dataclass
class Market:
    token_id: int
    symbol: str | None
    price_native: float | None
    sol_usd: float | None
    liquidity_usd: float | None
    volume_h1: float | None
    price_change_h1: float | None


@dataclass
class Row:
    trades: deque = field(default_factory=deque)  # (t, usd, is_buy, price_native)
    buys: int = 0
    sells: int = 0
    usd: float = 0.0


class Book:
    def __init__(self):
        self.by_mint: dict[str, Market] = {}
        self.by_pool: dict[str, Market] = {}
        self.rows: dict[int, Row] = {}
        self.last_alert: dict[int, float] = {}
        self.started_at: float | None = None

    def set_markets(self, by_mint: dict[str, Market], by_pool: dict[str, Market]) -> None:
        self.by_mint, self.by_pool = by_mint, by_pool

    def locate(self, trade: Trade) -> Market | None:
        market = self.by_mint.get(trade.mint) if trade.mint else self.by_pool.get(trade.pool)
        if market is None or not market.sol_usd:
            return None
        if market.price_native:
            gap = trade.price_native / market.price_native
            if gap > MAX_PRICE_GAP or gap < 1 / MAX_PRICE_GAP:
                return None
        return market

    def add(self, market: Market, trade: Trade, now: float) -> dict | None:
        """Registra a negociação. Devolve os dados do disparo se ele começou agora."""
        if self.started_at is None:
            self.started_at = now
        row = self.rows.setdefault(market.token_id, Row())
        usd = trade.sol * market.sol_usd
        row.trades.append((now, usd, trade.is_buy, trade.price_native))
        row.usd += usd
        if trade.is_buy:
            row.buys += 1
        else:
            row.sells += 1
        while row.trades and now - row.trades[0][0] > WINDOW_SECONDS:
            _, old_usd, old_buy, _ = row.trades.popleft()
            row.usd -= old_usd
            if old_buy:
                row.buys -= 1
            else:
                row.sells -= 1
        if not trade.is_buy or now - self.started_at < MIN_HISTORY_SECONDS:
            return None
        if now - self.last_alert.get(market.token_id, -COOLDOWN_SECONDS) < COOLDOWN_SECONDS:
            return None
        features = self.features(market, row)
        found = burst.detect(features)
        if not found:
            return None
        self.last_alert[market.token_id] = now
        return {**found, "features": features, "price_usd": trade.price_native * market.sol_usd}

    @staticmethod
    def features(market: Market, row: Row) -> dict:
        first = row.trades[0][3]
        last = row.trades[-1][3]
        # A hora contém os 5 min: uma moeda parada que acorda não pode ter hora menor que os 5 min.
        hour = max(market.volume_h1 or 0.0, row.usd)
        return {"available": True, "liquidity_usd": market.liquidity_usd, "volume_accel_m5": row.usd / (hour / 12) if hour else None,
                "price_change_m5": (last / first - 1) * 100, "txns_m5": row.buys + row.sells, "buys_m5": row.buys, "sells_m5": row.sells,
                "price_change_h1": market.price_change_h1}

    def flow(self, token_id: int, now: float) -> dict | None:
        """Quem está mandando nos últimos 30 s."""
        row = self.rows.get(token_id)
        if row is None:
            return None
        buy, sell, buys, sells = 0.0, 0.0, 0, 0
        for t, usd, is_buy, _ in reversed(row.trades):
            if now - t > FLOW_SECONDS:
                break
            if is_buy:
                buy, buys = buy + usd, buys + 1
            else:
                sell, sells = sell + usd, sells + 1
        return {"buy_usd": round(buy, 2), "sell_usd": round(sell, 2), "buys": buys, "sells": sells}
