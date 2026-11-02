"""Banco das negociações (`data/tape.db`): fluxo da moeda aberta, carteiras e disparos ao vivo."""
import sqlite3
import time
from pathlib import Path

from app.config import BACKEND_DIR

# Carteira boa: limiares fixos, sem calibração. Só apoio, não muda sinal.
SMART_MIN_POSITIONS = 5
SMART_MIN_WIN_RATE = 0.6
SMART_MIN_PROFIT_USD = 100.0
SMART_MAX_POSITIONS = 500  # acima disso é robô, não pessoa escolhendo moeda
KEEP_DAYS = 14
SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_positions (wallet TEXT, token_id INTEGER, bought_usd REAL, sold_usd REAL, first_buy REAL, last_ts REAL, PRIMARY KEY (wallet, token_id));
CREATE INDEX IF NOT EXISTS ix_wp_last ON wallet_positions (last_ts);
CREATE TABLE IF NOT EXISTS smart_wallets (wallet TEXT PRIMARY KEY, positions INTEGER, win_rate REAL, profit_usd REAL);
CREATE TABLE IF NOT EXISTS smart_buys (token_id INTEGER, wallet TEXT, ts REAL, usd REAL);
CREATE INDEX IF NOT EXISTS ix_sb ON smart_buys (token_id, ts);
CREATE TABLE IF NOT EXISTS flow (token_id INTEGER PRIMARY KEY, ts REAL, buy_usd REAL, sell_usd REAL, buys INTEGER, sells INTEGER);
CREATE TABLE IF NOT EXISTS tape_alerts (token_id INTEGER, ts REAL, price_usd REAL, strength TEXT, blocked TEXT);
"""


def tape_path() -> Path:
    return BACKEND_DIR / "data" / "tape.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or tape_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;" + SCHEMA)
    return con


def save_positions(con: sqlite3.Connection, batch: dict[tuple[str, int], list]) -> None:
    """`batch`: (carteira, moeda) -> [comprado, vendido, primeira compra, última negociação]."""
    con.executemany(
        """INSERT INTO wallet_positions VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (wallet, token_id) DO UPDATE SET
           bought_usd = bought_usd + excluded.bought_usd, sold_usd = sold_usd + excluded.sold_usd,
           first_buy = COALESCE(first_buy, excluded.first_buy), last_ts = excluded.last_ts""",
        [(w, t, v[0], v[1], v[2], v[3]) for (w, t), v in batch.items()],
    )
    con.commit()


def rescore(con: sqlite3.Connection, now: float | None = None) -> int:
    """Recalcula as carteiras boas. Só conta operação encerrada: vendeu ao menos metade do que comprou."""
    now = now or time.time()
    con.execute("DELETE FROM wallet_positions WHERE last_ts < ?", (now - KEEP_DAYS * 86400,))
    con.execute("DELETE FROM smart_buys WHERE ts < ?", (now - 86400,))
    con.execute("DELETE FROM smart_wallets")
    con.execute(
        """INSERT INTO smart_wallets
           SELECT wallet, COUNT(*), AVG(sold_usd > bought_usd), SUM(sold_usd - bought_usd) FROM wallet_positions
           WHERE bought_usd > 0 AND sold_usd >= bought_usd * 0.5 GROUP BY wallet
           HAVING COUNT(*) >= ? AND COUNT(*) <= ? AND AVG(sold_usd > bought_usd) >= ? AND SUM(sold_usd - bought_usd) >= ?""",
        (SMART_MIN_POSITIONS, SMART_MAX_POSITIONS, SMART_MIN_WIN_RATE, SMART_MIN_PROFIT_USD),
    )
    con.commit()
    return con.execute("SELECT COUNT(*) FROM smart_wallets").fetchone()[0]


def _read(path: Path | None = None) -> sqlite3.Connection | None:
    path = path or tape_path()
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return None


def read_flow(token_id: int, max_age: float = 5.0, now: float | None = None) -> dict | None:
    """Fluxo dos últimos 30 s. Só existe em moeda de pump.fun ou PumpSwap, aberta agora."""
    con = _read()
    if con is None:
        return None
    try:
        row = con.execute("SELECT ts, buy_usd, sell_usd, buys, sells FROM flow WHERE token_id = ?", (token_id,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if row is None or (now or time.time()) - row[0] > max_age:
        return None
    return {"buy_usd": row[1], "sell_usd": row[2], "buys": row[3], "sells": row[4]}


def smart_activity(token_id: int, minutes: int = 15, now: float | None = None) -> dict:
    empty = {"available": False, "wallets": 0, "usd": 0.0, "known_smart": 0, "minutes": minutes}
    con = _read()
    if con is None:
        return empty
    try:
        known = con.execute("SELECT COUNT(*) FROM smart_wallets").fetchone()[0]
        count, usd = con.execute("SELECT COUNT(DISTINCT wallet), COALESCE(SUM(usd), 0) FROM smart_buys WHERE token_id = ? AND ts >= ?",
                                 (token_id, (now or time.time()) - minutes * 60)).fetchone()
    except sqlite3.Error:
        return empty
    finally:
        con.close()
    return {"available": True, "wallets": count, "usd": round(usd, 2), "known_smart": known, "minutes": minutes}
