"""Confirmação secundária por carteiras que costumam acertar (`smart-1`) — SÓ OBSERVAÇÃO.

Reaproveita o que o `tape` já grava em `data/tape.db` (nada novo é coletado):
- `smart_wallets`: carteiras com 5+ operações encerradas, 60%+ de acerto e US$ 100+ de lucro em 14 dias
  (heurística antiga de `tape.store.rescore`, NÃO validada estatisticamente);
- `smart_buys`: compras dessas carteiras, gravadas no instante da compra e só se a carteira JÁ era
  classificada como boa naquele momento — por isso ler `smart_buys` com `ts <= instante` não usa o futuro.

Não é habilidade comprovada: mede lucro bruto realizado aproximado (sem taxas, sem slippage), não separa
carteiras ligadas entre si nem cópia de operações. Por isso:
- nunca cria, bloqueia, rebaixa nem reforça sinal; nunca muda score, ranking, disparo ou segurança;
- falta de dado é `insufficient_data`, nunca penalidade;
- só pump.fun e PumpSwap têm compra ligada à carteira; o resto é `unsupported_source`.

Liga/desliga: `SMART_WALLET_SHADOW=false` desliga cálculo, exibição e registro (chave geral).
"""
import sqlite3
import time
from pathlib import Path

from app.tape import store as tape_store

RULES_VERSION = "smart-1"
SUPPORTED_DEX = {"pumpfun", "pumpswap"}
WINDOW_MINUTES = 15  # compra mais antiga que isso não confirma mais (expira)
MIN_KNOWN_SMART = 10  # com menos carteiras boas conhecidas, a amostra é pequena demais para dizer algo
MIN_WALLETS_CONFIRMED = 2
MAX_TOP_SHARE = 0.8
# Elite: as que acertam MUITO. Só elas podem reforçar um sinal de compra (com segurança limpa).
ELITE_MIN_POSITIONS, ELITE_MIN_WIN_RATE, ELITE_MIN_PROFIT_USD = 8, 0.75, 500.0  # uma carteira com 80%+ do valor é concentração, não confirmação de várias
SCHEMA = """
CREATE TABLE IF NOT EXISTS smart_confirmations (
    signal_id INTEGER PRIMARY KEY, token_id INTEGER, signal_ts REAL, recorded_ts REAL, state TEXT,
    wallets INTEGER, usd REAL, known_smart INTEGER, top_share REAL, rules_version TEXT);
"""


def _open(path: Path | None = None, write: bool = False) -> sqlite3.Connection | None:
    path = path or tape_store.tape_path()
    if not write and not path.exists():
        return None
    try:
        if write:
            con = tape_store.connect(path)
            con.executescript(SCHEMA)
            return con
        return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return None


def evaluate(token_id: int, dex_id: str | None, at: float | None = None, window_minutes: int = WINDOW_MINUTES,
             con: sqlite3.Connection | None = None) -> dict:
    """Estado da confirmação no instante `at` (epoch), usando só compras com `ts <= at`."""
    at = at or time.time()
    base = {"state": "insufficient_data", "wallets": 0, "usd": 0.0, "known_smart": 0, "top_share": None,
            "last_buy_age_seconds": None, "window_minutes": window_minutes, "rules_version": RULES_VERSION,
            "influences_signal": False, "elite_wallets": 0}
    if (dex_id or "").lower() not in SUPPORTED_DEX:
        return {**base, "state": "unsupported_source",
                "explanation": "Só pump.fun e PumpSwap ligam compra à carteira; esta moeda negocia em outra DEX."}
    own = con is None
    con = con or _open()
    if con is None:
        return {**base, "explanation": "Registro de negociações indisponível."}
    try:
        known = con.execute("SELECT COUNT(*) FROM smart_wallets").fetchone()[0]
        rows = con.execute("SELECT wallet, SUM(usd), MAX(ts) FROM smart_buys WHERE token_id = ? AND ts <= ? AND ts >= ? GROUP BY wallet",
                           (token_id, at, at - 86400)).fetchall()
        elite = con.execute(
            "SELECT COUNT(DISTINCT b.wallet) FROM smart_buys b JOIN smart_wallets w ON w.wallet = b.wallet "
            "WHERE b.token_id = ? AND b.ts <= ? AND b.ts >= ? AND w.positions >= ? AND w.win_rate >= ? AND w.profit_usd >= ?",
            (token_id, at, at - window_minutes * 60, ELITE_MIN_POSITIONS, ELITE_MIN_WIN_RATE, ELITE_MIN_PROFIT_USD)).fetchone()[0]
    except sqlite3.Error:
        return {**base, "explanation": "Registro de negociações indisponível."}
    finally:
        if own:
            con.close()
    base["known_smart"], base["elite_wallets"] = known, elite
    if known < MIN_KNOWN_SMART:
        return {**base, "explanation": f"Só {known} carteira(s) boa(s) conhecida(s): amostra pequena demais."}
    cut = at - window_minutes * 60
    recent = [(w, usd or 0.0, ts) for w, usd, ts in rows if ts >= cut]
    last = max((ts for _, _, ts in rows), default=None)
    base["last_buy_age_seconds"] = round(at - last, 1) if last else None
    if not recent:
        state = "expired" if rows else "no_confirmation"
        why = (f"Carteiras boas compraram nas últimas 24 h, mas nenhuma nos últimos {window_minutes} min." if rows
               else f"Nenhuma das {known} carteiras boas comprou nos últimos {window_minutes} min.")
        return {**base, "state": state, "explanation": why}
    total = sum(u for _, u, _ in recent)
    top = max(u for _, u, _ in recent) / total if total > 0 else 1.0
    n = len(recent)  # carteiras distintas: várias compras da mesma carteira contam uma vez
    state = "confirmed_secondary" if n >= MIN_WALLETS_CONFIRMED and top < MAX_TOP_SHARE else "weak_confirmation"
    why = f"{n} carteira(s) boa(s) distintas compraram US$ {total:,.0f} nos últimos {window_minutes} min"
    if n >= MIN_WALLETS_CONFIRMED and top >= MAX_TOP_SHARE:
        why += f"; uma delas tem {top * 100:.0f}% do valor (concentrado)"
    return {**base, "state": state, "wallets": n, "usd": round(total, 2), "top_share": round(top, 2),
            "explanation": why + ". Só apoio: não muda o sinal."}


def record_signals(signals: list[tuple[int, int, str | None, float]], path: Path | None = None, now: float | None = None) -> int:
    """Grava o estado no instante de cada sinal de compra: (signal_id, token_id, dex_id, epoch do sinal).

    Repetir o mesmo sinal não duplica (chave = signal_id). Retorna quantos foram gravados agora.
    """
    if not signals:
        return 0
    con = _open(path, write=True)
    if con is None:
        return 0
    now = now or time.time()
    try:
        done = {r[0] for r in con.execute(
            f"SELECT signal_id FROM smart_confirmations WHERE signal_id IN ({','.join('?' * len(signals))})", [s[0] for s in signals])}
        rows = []
        for sid, tid, dex, ts in signals:
            if sid in done:
                continue
            c = evaluate(tid, dex, at=ts, con=con)
            rows.append((sid, tid, ts, now, c["state"], c["wallets"], c["usd"], c["known_smart"], c["top_share"], RULES_VERSION))
        con.executemany("INSERT OR IGNORE INTO smart_confirmations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.commit()
        return len(rows)
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def last_recorded_signal_id(path: Path | None = None) -> int:
    con = _open(path)
    if con is None:
        return 0
    try:
        return con.execute("SELECT COALESCE(MAX(signal_id), 0) FROM smart_confirmations").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def recorded(path: Path | None = None, limit: int = 5000) -> list[dict]:
    con = _open(path)
    if con is None:
        return []
    try:
        rows = con.execute("SELECT signal_id, token_id, signal_ts, state, wallets, usd FROM smart_confirmations "
                           "ORDER BY signal_id DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [{"signal_id": r[0], "token_id": r[1], "signal_ts": r[2], "state": r[3], "wallets": r[4], "usd": r[5]} for r in rows]


# ---------------- Ligação com o banco principal ----------------
def shadow_job(db, now: float | None = None, batch: int = 500) -> int:
    """Registra o estado das carteiras no instante de cada sinal de compra novo (roda no `evaluate`).

    Só sinais das últimas 23 h: `smart_buys` guarda 24 h, então o instante do sinal ainda é reconstruível.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.config import get_settings
    from app.models import Pair, Signal, Token

    if not get_settings().smart_wallet_shadow:
        return 0
    now = now or time.time()
    since = datetime.fromtimestamp(now, UTC) - timedelta(hours=23)
    rows = db.execute(
        select(Signal.id, Signal.token_id, Pair.dex_id, Signal.created_at)
        .join(Token, Token.id == Signal.token_id).outerjoin(Pair, Pair.id == Token.primary_pair_id)
        .where(Signal.id > last_recorded_signal_id(), Signal.action == "buy", Signal.created_at >= since)
        .order_by(Signal.id).limit(batch)
    ).all()
    return record_signals([(sid, tid, dex, created.timestamp()) for sid, tid, dex, created in rows], now=now)


def shadow_report(db, horizon_seconds: int = 3600) -> dict:
    """Compara o resultado dos sinais de compra por estado das carteiras. Retorno bruto, sem custos."""
    from sqlalchemy import select

    from app.models import AnalysisOutcome, Signal

    recs = recorded()
    by_signal = {r["signal_id"]: r for r in recs}
    groups: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    for r in recs:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    ids = list(by_signal)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for sid, end in db.execute(
            select(Signal.id, AnalysisOutcome.end_return).join(AnalysisOutcome, AnalysisOutcome.analysis_id == Signal.analysis_id)
            .where(Signal.id.in_(chunk), AnalysisOutcome.horizon_seconds == horizon_seconds, AnalysisOutcome.status == "ok",
                   AnalysisOutcome.end_return.is_not(None))
        ):
            groups.setdefault(by_signal[sid]["state"], []).append(end)
    out = []
    for state, n in sorted(counts.items()):
        vals = sorted(groups.get(state, []))
        m = len(vals)
        out.append({"state": state, "signals": n, "with_outcome": m,
                    "mean_return": round(sum(vals) / m, 4) if m else None,
                    "median_return": round(vals[m // 2], 4) if m else None,
                    "share_positive": round(sum(v > 0 for v in vals) / m, 3) if m else None,
                    "small_sample": m < 30})
    return {"rules_version": RULES_VERSION, "horizon_seconds": horizon_seconds, "groups": out,
            "note": "Só observação. Retorno bruto no horizonte (sem taxas nem slippage). Amostra < 30 não permite conclusão."}
