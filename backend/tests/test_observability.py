"""Medições, fila de análise, GET sem escrita, transação repetida no tape e carteiras em modo observação."""
import base64
import inspect
import json
import threading
import time

from app import metrics, worker
from app.engine import pipeline, scoring, signals, smart_confirm
from app.models import LiveWatch
from app.tape import store
from app.tape.__main__ import Tape
from tests.conftest import SOL_MINT
from tests.test_tape import pump

API = "/api/v1"


# ---------------- Medições ----------------
def test_percentiles_only_with_enough_samples(tmp_path):
    for v in range(10):
        metrics.observe("x", v)
    t = metrics.summary()["timings_ms"]["x"]
    assert t["n"] == 10 and t["p50"] is None and t["p95"] is None and t["max"] == 9
    for v in range(200):
        metrics.observe("y", v)
    y = metrics.summary()["timings_ms"]["y"]
    assert y["p50"] is not None and y["p95"] is not None and y["p99"] is None  # 200 < 300


def test_sample_is_bounded_and_flush_is_readable():
    for v in range(metrics.SAMPLE_SIZE + 50):
        metrics.observe("z", v)
    metrics.incr("c", 3)
    metrics.gauge("g", 7)
    metrics.init("teste")
    metrics.flush()
    procs = metrics.read_all()
    mine = next(p for p in procs if p["process"] == "teste")
    assert mine["timings_ms"]["z"]["n"] == metrics.SAMPLE_SIZE
    assert mine["counters"]["c"] == 3 and mine["gauges"]["g"] == 7
    metrics._state["process"] = None


def test_metrics_endpoint_requires_login(client):
    assert client.get(f"{API}/system/metrics").status_code == 401
    client.post(f"{API}/auth/login", json={"username": "alisson", "password": "test-initial-pw"})
    auth_client = client
    auth_client.get(f"{API}/health")
    body = auth_client.get(f"{API}/system/metrics").json()
    assert "processes" in body and "note" in body


# ---------------- Fila de análise ----------------
def test_queue_coalesces_measures_wait_and_hot_first():
    clock = [100.0]
    q = worker.AnalysisQueue(clock=lambda: clock[0])
    q.add([1, 2], hot=False)
    clock[0] = 103.0
    q.add([2], hot=True)  # promovida: mantém a hora da 1ª entrada
    q.add([1], hot=False)  # já na fila: junta, não duplica
    q.add([3], hot=True)
    assert q.sizes() == (2, 1) and q.coalesced == 1
    assert q.oldest_age() == (3.0, 3.0)  # a mais antiga de cada fila entrou às 100
    clock[0] = 110.0
    hot_age, cold_age = q.oldest_age()
    assert hot_age == 10.0 and cold_age == 10.0
    assert q.take(10) == [2, 3, 1]  # quentes primeiro
    assert q.sizes() == (0, 0)
    waits = metrics.summary()["timings_ms"]
    assert waits["queue.wait.hot"]["max"] == 10_000.0 and waits["queue.wait.cold"]["n"] == 1


def test_cold_waits_for_hot_without_polling_and_never_forever():
    assert worker._hot_idle.is_set()
    t0 = time.monotonic()
    worker._yield_to_hot()  # quente parada: não espera nada
    assert time.monotonic() - t0 < 0.05
    worker._hot_busy.set()
    worker._hot_idle.clear()
    threading.Timer(0.2, lambda: (worker._hot_busy.clear(), worker._hot_idle.set())).start()
    t0 = time.monotonic()
    worker._yield_to_hot()
    assert 0.15 < time.monotonic() - t0 < 2.0  # acordou quando a quente terminou
    assert worker._hot_idle.is_set()


# ---------------- GET sem efeito colateral ----------------
def test_exit_plan_get_never_writes_and_watch_needs_login(client, fake_dex, db):
    assert client.post(f"{API}/tokens/solana/{SOL_MINT}/watch").status_code == 401
    client.post(f"{API}/auth/login", json={"username": "alisson", "password": "test-initial-pw"})
    auth_client = client
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    for _ in range(3):
        assert auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").status_code == 200
    assert db.query(LiveWatch).count() == 0
    assert auth_client.post(f"{API}/tokens/solana/{SOL_MINT}/watch").status_code == 204
    assert auth_client.post(f"{API}/tokens/solana/{SOL_MINT}/watch").status_code == 204  # repetido: ainda 1 linha
    assert db.query(LiveWatch).count() == 1


# ---------------- Tape ----------------
def _msg(signature):
    logs = ["Program data: " + base64.b64encode(pump()).decode()]
    return json.dumps({"params": {"result": {"value": {"signature": signature, "err": None, "logs": logs}}}})


def test_tape_ignores_the_same_transaction_twice():
    tape = Tape()
    tape.handle(_msg("sigA"), 1000.0, None)
    tape.handle(_msg("sigA"), 1000.1, None)  # chegou pelas 2 assinaturas (pump.fun e PumpSwap)
    tape.handle(_msg("sigB"), 1000.2, None)
    assert tape.seen == 2 and tape.duplicates == 1


def test_tape_signature_memory_is_bounded(monkeypatch):
    from app.tape import __main__ as tape_main

    monkeypatch.setattr(tape_main, "SEEN_SIGNATURES", 3)
    tape = Tape()
    for i in range(10):
        tape._seen_before(f"s{i}")
    assert len(tape._recent) == 3


# ---------------- Carteiras em modo observação ----------------
def _smart_db(path, known=12, buys=()):
    con = store.connect(path)
    con.executemany("INSERT INTO smart_wallets VALUES (?, ?, ?, ?)", [(f"W{i}", 5, 0.7, 200.0) for i in range(known)])
    con.executemany("INSERT INTO smart_buys VALUES (?, ?, ?, ?)", buys)
    con.commit()
    return con


def test_confirmation_states(tmp_path):
    now = 10_000.0
    path = tmp_path / "tape.db"
    _smart_db(path, buys=[(1, "W1", now - 60, 100.0), (1, "W1", now - 30, 50.0), (1, "W2", now - 20, 120.0),
                          (2, "W1", now - 60, 100.0),
                          (3, "W1", now - 60, 1000.0), (3, "W2", now - 50, 10.0),
                          (4, "W1", now - 3 * 3600, 100.0)])
    con = smart_confirm._open(path)
    ev = lambda tid, dex="pumpswap": smart_confirm.evaluate(tid, dex, at=now, con=con)  # noqa: E731
    c = ev(1)
    assert c["state"] == "confirmed_secondary" and c["wallets"] == 2 and c["usd"] == 270.0  # W1 conta uma vez
    assert c["influences_signal"] is False
    assert ev(2)["state"] == "weak_confirmation"  # 1 carteira só
    assert ev(3)["state"] == "weak_confirmation"  # 2 carteiras, mas 99% do valor numa só
    assert ev(4)["state"] == "expired"  # comprou há 3 h: não confirma mais
    assert ev(5)["state"] == "no_confirmation"
    assert ev(1, "raydium")["state"] == "unsupported_source"
    con.close()


def test_confirmation_has_no_look_ahead(tmp_path):
    path = tmp_path / "tape.db"
    _smart_db(path, buys=[(1, "W1", 1000.0, 100.0), (1, "W2", 1010.0, 100.0)])
    con = smart_confirm._open(path)
    assert smart_confirm.evaluate(1, "pumpfun", at=1005.0, con=con)["wallets"] == 1  # a compra das 1010 é futura
    assert smart_confirm.evaluate(1, "pumpfun", at=1010.0, con=con)["wallets"] == 2
    con.close()


def test_confirmation_is_honest_without_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "tape_path", lambda: tmp_path / "nao_existe.db")
    assert smart_confirm.evaluate(1, "pumpswap")["state"] == "insufficient_data"
    path = tmp_path / "poucas.db"
    _smart_db(path, known=3, buys=[(1, "W1", 100.0, 50.0), (1, "W2", 100.0, 50.0)])
    con = smart_confirm._open(path)
    assert smart_confirm.evaluate(1, "pumpswap", at=110.0, con=con)["state"] == "insufficient_data"  # amostra pequena
    con.close()


def test_record_is_idempotent_and_point_in_time(tmp_path):
    path = tmp_path / "tape.db"
    _smart_db(path, buys=[(1, "W1", 1000.0, 100.0), (1, "W2", 1001.0, 100.0), (1, "W3", 5000.0, 100.0)])
    assert smart_confirm.record_signals([(7, 1, "pumpswap", 1002.0)], path=path) == 1
    assert smart_confirm.record_signals([(7, 1, "pumpswap", 9999.0)], path=path) == 0  # mesmo sinal: não regrava
    con = smart_confirm._open(path)
    assert con.execute("SELECT state, wallets FROM smart_confirmations WHERE signal_id = 7").fetchone() == ("confirmed_secondary", 2)
    con.close()


def test_signal_engine_never_reads_wallets():
    """Garantia estrutural: o caminho do sinal não usa a confirmação por carteiras."""
    for mod in (pipeline, signals, scoring):
        src = inspect.getsource(mod)
        assert "smart_confirm" not in src and "smart_buys" not in src and "smart_activity" not in src


def test_exit_plan_shows_confirmation_and_switch_turns_it_off(auth_client, fake_dex, monkeypatch):
    from app import config

    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()
    assert j["smart_confirmation"]["state"] == "unsupported_source"  # par de teste é raydium
    assert j["smart_confirmation"]["influences_signal"] is False
    monkeypatch.setenv("SMART_WALLET_SHADOW", "false")
    config.get_settings.cache_clear()
    j = auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()
    assert j["smart_confirmation"] is None


def test_shadow_job_switch_and_report(db, monkeypatch):
    from app import config

    assert smart_confirm.shadow_job(db) == 0  # sem sinais de compra
    rep = smart_confirm.shadow_report(db)
    assert rep["groups"] == [] and "observação" in rep["note"]
    monkeypatch.setenv("SMART_WALLET_SHADOW", "false")
    config.get_settings.cache_clear()
    assert smart_confirm.shadow_job(db) == 0
