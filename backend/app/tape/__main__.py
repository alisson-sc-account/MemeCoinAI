"""Processo das negociações ao vivo: `python -m app.tape` (um por banco, trava própria)."""
import asyncio
import json
import logging
import signal
import time

import websockets
from sqlalchemy import func, select, update

from app import agents
from app.api.views import latest_snapshots
from app.config import BACKEND_DIR, get_settings
from app.db import session_factory, utcnow
from app.engine import burst
from app.engine.alerts import AlertCandidate, upsert_alert
from app.live import service as live
from app.logging_setup import setup_logging
from app.models import Pair, SecurityReport, Token
from app.tape import store
from app.tape.book import Book, Market
from app.tape.decode import PUMP_PROGRAM, PUMPSWAP_PROGRAM, QUICK_MARKS, decode_logs
from app.worker_lock import WorkerAlreadyRunning, WorkerLock

log = logging.getLogger("tape")
URL = "wss://api.mainnet-beta.solana.com"
MARKET_REFRESH = 60.0
FLOW_EVERY = 2.0
POSITIONS_EVERY = 30.0
RESCORE_EVERY = 600.0
BEAT_EVERY = 30.0
NEW_TOKEN_TRADES = 8  # pump.fun fora da lista com 8 negociações em 5 min entra para acompanhar
NEW_TOKENS_PER_MINUTE = 30
SOL_QUOTES = {"SOL", "WSOL"}
_running = True


def _load_markets() -> tuple[dict, dict]:
    db = session_factory()()
    try:
        rows = db.execute(select(Token.id, Token.address, Token.symbol, Token.primary_pair_id).where(Token.is_tracked.is_(True), Token.chain_id == "solana", Token.rugged_at.is_(None))).all()
        pair_ids = [r[3] for r in rows if r[3]]
        pairs = {p.id: p for p in db.scalars(select(Pair).where(Pair.id.in_(pair_ids)))}
        snaps = latest_snapshots(db, pair_ids)
        by_mint, by_pool, sol_prices = {}, {}, []
        for token_id, address, symbol, pair_id in rows:
            s, p = snaps.get(pair_id), pairs.get(pair_id)
            if not s or not p or (p.quote_symbol or "").upper() not in SOL_QUOTES:
                continue
            sol_usd = s.price_usd / s.price_native if s.price_usd and s.price_native else None
            if sol_usd:
                sol_prices.append(sol_usd)
            m = Market(token_id, symbol, s.price_native, sol_usd, s.liquidity_usd, s.volume_h1, s.price_change_h1)
            by_mint[address] = m
            by_pool[p.pair_address] = m
        if sol_prices:  # um par sem preço em dólar usa o preço típico do SOL
            typical = sorted(sol_prices)[len(sol_prices) // 2]
            for m in by_mint.values():
                m.sol_usd = m.sol_usd or typical
        return by_mint, by_pool
    finally:
        db.close()


def _raise_alert(token_id: int, found: dict) -> None:
    """Grava o disparo. Moeda com golpe ou perigo de segurança fica só no registro, sem alerta."""
    db = session_factory()()
    con = store.connect()
    try:
        report = db.get(SecurityReport, token_id)
        token = db.get(Token, token_id)
        blocked = "golpe" if token is None or token.rugged_at else "perigo" if report and report.verdict == "danger" else None
        # Com o alerta desligado segue registrando: é o que permite comparar e religar só se provar valor.
        con.execute("INSERT INTO tape_alerts VALUES (?, ?, ?, ?, ?)", (token_id, time.time(), found["price_usd"], found["strength"], blocked))
        con.commit()
        if blocked or not get_settings().tape_alerts_enabled:
            return
        extreme = found["strength"] == "extreme"
        cand = AlertCandidate("pump_burst", "critical" if extreme else "high",
                              "Disparo agora: alta forte em andamento" if extreme else "Disparo agora: volume e compras acelerando",
                              "; ".join(found["reasons"]), {**found["evidence"], "strength": found["strength"], "source": "tape",
                                                            "pattern_stats": burst.pattern_stats(db, utcnow())},
                              0.5, utcnow(), rule_id="tape-burst-1")
        upsert_alert(db, cand, token_id, token.primary_pair_id, None)
        db.commit()
        log.info("disparo ao vivo: %s %s", token.symbol, found["strength"])
    except Exception:
        db.rollback()
        log.exception("falha ao gravar disparo")
    finally:
        con.close()
        db.close()


def _add_new_tokens(mints: list[str]) -> int:
    s = get_settings()
    db = session_factory()()
    try:
        tracked = db.scalar(select(func.count()).select_from(Token).where(Token.is_tracked.is_(True))) or 0
        known = set(db.scalars(select(Token.address).where(Token.chain_id == "solana", Token.address.in_(mints))))
        # Moeda que saiu da lista por estar morta e voltou a ser negociada volta a ser acompanhada.
        db.execute(update(Token).where(Token.chain_id == "solana", Token.address.in_(known), Token.is_tracked.is_(False), Token.rugged_at.is_(None)).values(is_tracked=True))
        added = 0
        for mint in mints:
            if mint not in known and tracked + added < s.max_tracked_tokens:
                db.add(Token(chain_id="solana", address=mint, discovered_via="tape", first_seen_at=utcnow()))
                added += 1
        db.commit()
        return added
    finally:
        db.close()


def _focused_ids() -> list[int]:
    db = session_factory()()
    try:
        return [t.id for t in live.focused_tokens(db)]
    finally:
        db.close()


def _beat(interval: float, count: int, error: str | None) -> None:
    db = session_factory()()
    try:
        agents.beat(db, "tape", interval, error, count)
    finally:
        db.close()


class Tape:
    def __init__(self):
        self.book = Book()
        self.positions: dict[tuple[str, int], list] = {}
        self.smart: set[str] = set()
        self.untracked: dict[str, list[float]] = {}
        self.seen = 0
        self.matched = 0
        self.smart_rows: list[tuple] = []

    def handle(self, raw: str, now: float, loop) -> None:
        if not any(mark in raw for mark in QUICK_MARKS):
            return
        value = ((json.loads(raw).get("params") or {}).get("result") or {}).get("value") or {}
        if value.get("err"):
            return
        for trade in decode_logs(value.get("logs") or []):
            self.seen += 1
            market = self.book.locate(trade)
            if market is None:
                if trade.mint and trade.is_buy and trade.mint not in self.book.by_mint:
                    self.untracked.setdefault(trade.mint, []).append(now)
                continue
            self.matched += 1
            usd = trade.sol * market.sol_usd
            pos = self.positions.setdefault((trade.user, market.token_id), [0.0, 0.0, None, now])
            pos[3] = now
            if trade.is_buy:
                pos[0] += usd
                pos[2] = pos[2] or now
                if trade.user in self.smart:
                    self.smart_rows.append((market.token_id, trade.user, now, usd))
            else:
                pos[1] += usd
            found = self.book.add(market, trade, now)
            if found:
                loop.run_in_executor(None, _raise_alert, market.token_id, found)


async def _periodic(tape: Tape) -> None:
    loop = asyncio.get_running_loop()
    con = store.connect()
    next_market = next_positions = next_score = next_beat = next_new = 0.0
    last_seen = 0
    while _running:
        now = time.time()
        try:
            if now >= next_market:
                tape.book.set_markets(*await loop.run_in_executor(None, _load_markets))
                next_market = now + MARKET_REFRESH
            ids = await loop.run_in_executor(None, _focused_ids)
            flows = [(i, tape.book.flow(i, now)) for i in ids]
            con.executemany("INSERT OR REPLACE INTO flow VALUES (?, ?, ?, ?, ?, ?)",
                            [(i, now, f["buy_usd"], f["sell_usd"], f["buys"], f["sells"]) for i, f in flows if f])
            if tape.smart_rows:
                con.executemany("INSERT INTO smart_buys VALUES (?, ?, ?, ?)", tape.smart_rows)
                tape.smart_rows = []
            con.commit()
            if now >= next_positions and tape.positions:
                batch, tape.positions = tape.positions, {}
                store.save_positions(con, batch)
                next_positions = now + POSITIONS_EVERY
            if now >= next_score:
                count = store.rescore(con, now)
                tape.smart = {r[0] for r in con.execute("SELECT wallet FROM smart_wallets")}
                log.info("carteiras boas: %d", count)
                next_score = now + RESCORE_EVERY
            if now >= next_new:
                cut = now - 300
                hot = [m for m, ts in tape.untracked.items() if sum(t > cut for t in ts) >= NEW_TOKEN_TRADES][:NEW_TOKENS_PER_MINUTE]
                tape.untracked = {m: [t for t in ts if t > cut] for m, ts in tape.untracked.items() if m not in hot and ts[-1] > cut}
                if hot:
                    added = await loop.run_in_executor(None, _add_new_tokens, hot)
                    log.info("novas moedas pelas negociações: %d", added)
                next_new = now + 60
            if now >= next_beat:
                await loop.run_in_executor(None, _beat, BEAT_EVERY, tape.seen - last_seen, None if tape.seen > last_seen else "sem negociações recebidas")
                log.info("negociações: %d no período, %d de moedas acompanhadas", tape.seen - last_seen, tape.matched)
                last_seen = tape.seen
                next_beat = now + BEAT_EVERY
        except Exception:
            log.exception("falha na rotina periódica")
        await asyncio.sleep(FLOW_EVERY)
    con.close()


async def _stream(tape: Tape) -> None:
    loop = asyncio.get_running_loop()
    backoff = 5.0
    while _running:
        try:
            async with websockets.connect(URL, open_timeout=15, max_size=2**23, ping_interval=20) as ws:
                for i, program in enumerate((PUMP_PROGRAM, PUMPSWAP_PROGRAM)):
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": i + 1, "method": "logsSubscribe", "params": [{"mentions": [program]}, {"commitment": "processed"}]}))
                log.info("conectado ao fluxo de negociações")
                backoff = 5.0
                async for raw in ws:
                    if not _running:
                        return
                    tape.handle(raw, time.time(), loop)
        except Exception as exc:
            log.warning("fluxo caiu (%s); nova tentativa em %.0f s", type(exc).__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120.0)


async def _main() -> None:
    tape = Tape()
    await asyncio.gather(_stream(tape), _periodic(tape))


def _stop(*_):
    global _running
    _running = False


def main() -> None:
    setup_logging()
    lock = WorkerLock(BACKEND_DIR / "data" / "tape.lock")
    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        log.error("%s; já existe um leitor de negociações rodando", exc)
        raise SystemExit(1) from exc
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        asyncio.run(_main())
    finally:
        lock.release()


if __name__ == "__main__":
    main()
