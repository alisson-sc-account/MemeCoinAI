"""Listas do site prontas em segundo plano: `python -m app.board`.

Calcular a lista de milhares de moedas dentro da requisição deixava as telas em vários segundos e
disputava CPU com o preço da moeda aberta. Este processo calcula sozinho e grava um banco separado
(`data/board.db`), trocado de uma vez. A API só lê, com filtro e ordem por índice. Se este processo
parar, as listas envelhecem e, depois de `BOARD_MAX_AGE`, a API volta a calcular como antes.
"""
import json
import logging
import os
import signal
import sqlite3
import time
from pathlib import Path

from app import agents
from app.config import BACKEND_DIR, get_settings
from app.db import session_factory, utcnow
from app.logging_setup import setup_logging
from app.worker_lock import WorkerAlreadyRunning, WorkerLock

log = logging.getLogger("board")
BOARD_MAX_AGE = 120.0
PAUSE_SECONDS = 5.0
OPP_COLUMNS = ("tier_order", "score", "score_change", "liquidity_usd", "volume_h24", "price_change_h1", "risk_score", "pair_age_hours")
TOKEN_SORTS = ("opportunity_score", "risk_score", "liquidity_usd", "volume_h24", "volume_h1", "price_change_h1", "price_change_h24", "market_cap",
               "pair_age_hours", "first_seen_at", "observed_at")
_running = True


def board_path() -> Path:
    return BACKEND_DIR / "data" / "board.db"


def _sortable(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return _sortable(value)


def write_board(path: Path, rows: list[dict], items: list, sort_fields: dict, dashboard_json: str, tier_order: dict) -> None:
    """Monta um arquivo novo e troca de uma vez: quem está lendo nunca vê lista pela metade."""
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(f"""
        PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE opportunities (tier TEXT, {", ".join(f"{c} REAL" for c in OPP_COLUMNS)}, payload TEXT);
        CREATE TABLE tokens (chain_id TEXT, risk_level TEXT, freshness_status TEXT, min_filter_liq REAL, min_filter_vol REAL, age REAL,
                             {", ".join(f"s_{c}" for c in TOKEN_SORTS)}, payload TEXT);
    """)
    con.executemany(
        f"INSERT INTO opportunities VALUES ({','.join('?' * (len(OPP_COLUMNS) + 2))})",
        [(r["tier"], tier_order[r["tier"]], *[r.get(c) for c in OPP_COLUMNS[1:]], json.dumps(r, default=_json_default)) for r in rows],
    )
    con.executemany(
        f"INSERT INTO tokens VALUES ({','.join('?' * (len(TOKEN_SORTS) + 7))})",
        [(i.token.chain_id, i.scores.risk_level if i.scores else None, i.freshness.status, i.market.liquidity_usd if i.market else None,
          i.market.volume_h24 if i.market else None, i.pair_age_hours, *[_sortable(sort_fields[c](i)) for c in TOKEN_SORTS], i.model_dump_json()) for i in items],
    )
    con.executescript("""
        CREATE INDEX ix_opp_tier ON opportunities (tier_order, score DESC);
        CREATE INDEX ix_tok_opp ON tokens (s_opportunity_score DESC);
    """)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [("generated_ts", str(time.time())), ("dashboard", dashboard_json)])
    con.commit()
    con.close()
    for attempt in range(20):  # no Windows a troca falha enquanto alguém lê: tenta de novo logo depois
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    raise PermissionError(f"não consegui trocar {path}")


def read_connection(path: Path | None = None, max_age: float = BOARD_MAX_AGE) -> sqlite3.Connection | None:
    """Conexão só de leitura, se o painel existir e estiver recente. None = a API calcula como antes."""
    if not get_settings().board_enabled:
        return None
    path = path or board_path()
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
        row = con.execute("SELECT value FROM meta WHERE key='generated_ts'").fetchone()
        if row and time.time() - float(row[0]) <= max_age:
            con.row_factory = sqlite3.Row
            return con
        con.close()
    except (sqlite3.Error, ValueError):
        log.warning("painel ilegível; calculando na requisição")
    return None


def build_once() -> int:
    from app.api.opportunities import _build_rows
    from app.api.system import build_dashboard
    from app.api.tokens import SORT_FIELDS
    from app.api.views import tracked_list_items
    from app.engine.ranking import TIER_ORDER

    t0 = time.perf_counter()
    db = session_factory()()
    try:
        rows = _build_rows(db)
        items = tracked_list_items(db)
        dashboard = build_dashboard(db)
        write_board(board_path(), rows, items, SORT_FIELDS, dashboard.model_dump_json(), TIER_ORDER)
        agents.beat(db, "board", PAUSE_SECONDS, items=len(rows), duration_ms=round((time.perf_counter() - t0) * 1000, 1), now=utcnow())
        return len(rows)
    finally:
        db.close()


def _stop(*_):
    global _running
    _running = False


def main() -> None:
    setup_logging()
    lock = WorkerLock(BACKEND_DIR / "data" / "board.lock")
    try:
        lock.acquire()
    except WorkerAlreadyRunning as exc:
        log.error("%s; já existe um painel rodando", exc)
        raise SystemExit(1) from exc
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("painel iniciado")
    try:
        while _running:
            t0 = time.perf_counter()
            try:
                n = build_once()
                log.info("painel: %d moedas em %.1f s", n, time.perf_counter() - t0)
            except Exception:
                log.exception("falha ao montar o painel")
            time.sleep(PAUSE_SECONDS)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
