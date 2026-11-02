"""Negociações ao vivo: decodificação, mesma regra do disparo, carteiras, celular, cópia do banco e histórico."""
import base64
import struct
from datetime import timedelta

import httpx

from app import backup, config, notify, supervisor
from app.db import utcnow
from app.engine import burst
from app.engine.pipeline import analyze_token
from app.ingest.service import compact_old_snapshots, track_token
from app.live.chain import b58encode
from app.models import Alert, PairSnapshot, Signal
from app.tape import store
from app.tape.book import Book, Market
from app.tape.decode import PUMP_TRADE, QUICK_MARKS, SWAP_BUY, SWAP_SELL, Trade, decode_event, decode_logs
from tests.conftest import SOL_MINT

MINT, USER, POOL = bytes(range(32)), bytes(range(1, 33)), bytes(range(2, 34))


def pump(sol=2_000_000_000, tokens=1_000_000_000, buy=True):
    return PUMP_TRADE + MINT + struct.pack("<QQ", sol, tokens) + bytes([1 if buy else 0]) + USER + struct.pack("<qQQ", 1, 5, 5)


def swap(head, base=1_000_000_000, quote=2_000_000_000):
    fields = [1, base, 0, 0, 0, 0, 0, quote, 0, 0, 0, 0, 0, 0]
    return head + struct.pack("<14Q", *fields) + POOL + USER


def test_decode_pump_and_pumpswap():
    t = decode_event(pump())
    assert t.is_buy and t.sol == 2.0 and abs(t.price_native - 0.002) < 1e-12 and t.mint == b58encode(MINT) and t.user == b58encode(USER)
    assert decode_event(pump(buy=False)).is_buy is False
    b, s = decode_event(swap(SWAP_BUY)), decode_event(swap(SWAP_SELL))
    assert b.is_buy and not s.is_buy and b.pool == b58encode(POOL) and b.user == b58encode(USER) and abs(b.price_native - 0.002) < 1e-12
    assert decode_event(b"curto") is None and decode_event(b"\0" * 200) is None


def test_quick_marks_match_the_events_and_bad_lines_are_skipped():
    for raw, mark in zip((pump(), swap(SWAP_BUY), swap(SWAP_SELL)), QUICK_MARKS):
        assert base64.b64encode(raw).decode().startswith(mark)
    logs = ["Program log: x", "Program data: !!!", "Program data: " + base64.b64encode(pump()).decode()]
    assert len(decode_logs(logs)) == 1


def _market(**kw):
    return Market(**{"token_id": 1, "symbol": "A", "price_native": 0.001, "sol_usd": 100.0, "liquidity_usd": 20_000.0, "volume_h1": 1200.0, "price_change_h1": 10.0, **kw})


def _trade(price=0.001, buy=True, sol=2.0):
    return Trade(buy, sol, price, "W", mint="M")


def _pump_book(book, market, start=1000.0):
    found = None
    for i in range(12):
        found = book.add(market, _trade(price=0.001 * (1 + i * 0.01)), start + 62 + i) or found
    return found


def test_book_uses_the_same_burst_rule_and_fires_once():
    book = Book()
    market = _market()
    book.add(market, _trade(), 1000.0)
    found = _pump_book(book, market)
    assert found and found["strength"] in ("strong", "extreme") and found["evidence"]
    assert burst.detect(found["features"]) is not None  # a decisão é da regra congelada
    assert _pump_book(book, market, 1100.0) is None  # não repete dentro de 15 min


def test_book_quiet_cases():
    assert _pump_book_quiet(_market(liquidity_usd=4000.0)) is None
    assert _pump_book_quiet(_market(volume_h1=100_000.0)) is None  # volume normal para a moeda
    book = Book()
    market = _market()
    book.add(market, _trade(), 1000.0)
    for i in range(12):
        assert book.add(market, _trade(buy=False), 1062.0 + i) is None  # só vendas


def _pump_book_quiet(market):
    book = Book()
    book.add(market, _trade(), 1000.0)
    return _pump_book(book, market)


def test_no_alert_right_after_starting():
    book = Book()
    market = _market()
    for i in range(12):
        assert book.add(market, _trade(price=0.001 * (1 + i * 0.01)), 1000.0 + i) is None


def test_window_forgets_old_trades_and_flow_is_30_seconds():
    book = Book()
    market = _market()
    book.add(market, _trade(buy=False), 1000.0)
    book.add(market, _trade(), 1290.0)
    assert book.flow(1, 1300.0) == {"buy_usd": 200.0, "sell_usd": 0.0, "buys": 1, "sells": 0}
    book.add(market, _trade(), 1301.0)
    row = book.rows[1]
    assert row.sells == 0 and row.buys == 2 and abs(row.usd - 400.0) < 1e-9
    assert book.flow(99, 1300.0) is None


def test_locate_rejects_inverted_pool_and_unknown():
    book = Book()
    market = _market()
    book.set_markets({"M": market}, {})
    assert book.locate(_trade()) is market
    assert book.locate(_trade(price=5.0)) is None
    assert book.locate(Trade(True, 1.0, 0.001, "W", mint="X")) is None


def test_smart_wallets_score_only_closed_and_real(tmp_path):
    con = store.connect(tmp_path / "t.db")
    now = 1_000_000.0
    batch = {}
    for t in range(6):
        batch[("boa", t)] = [100.0, 200.0, now, now]  # 6 ganhos, +600
    for t in range(6):
        batch[("ruim", t)] = [100.0, 50.0, now, now]  # 6 perdas
    for t in range(4):
        batch[("poucas", t)] = [100.0, 500.0, now, now]  # poucos casos
    for t in range(6):
        batch[("aberta", t)] = [100.0, 10.0, now, now]  # ainda não vendeu: não conta
    for t in range(600):
        batch[("robo", t)] = [10.0, 12.0, now, now]  # negociando tudo
    store.save_positions(con, batch)
    store.save_positions(con, {("boa", 0): [100.0, 200.0, now, now]})  # soma, não substitui
    assert store.rescore(con, now) == 1
    assert con.execute("SELECT wallet, positions, win_rate, profit_usd FROM smart_wallets").fetchone() == ("boa", 6, 1.0, 700.0)
    assert store.rescore(con, now + 15 * 86400) == 0  # histórico antigo expira
    con.close()


def test_read_helpers_are_honest_without_data():
    assert store.read_flow(1) is None and store.smart_activity(1)["available"] is False
    con = store.connect()
    con.execute("INSERT INTO flow VALUES (1, 1000, 5, 6, 1, 2)")
    con.execute("INSERT INTO smart_buys VALUES (1, 'w', 1000, 50)")
    con.execute("INSERT INTO smart_buys VALUES (1, 'w', 1001, 50)")
    con.commit()
    con.close()
    assert store.read_flow(1, now=1001.0)["sells"] == 2 and store.read_flow(1, now=1100.0) is None  # fluxo velho não vale
    assert store.smart_activity(1, now=1100.0) == {"available": True, "wallets": 1, "usd": 100.0, "known_smart": 0, "minutes": 15}


def test_live_alert_survives_late_collector_then_expires(db, fake_dex):
    from app.engine.alerts import AlertCandidate, upsert_alert
    token, _ = track_token(db, "solana", SOL_MINT)
    upsert_alert(db, AlertCandidate("pump_burst", "high", "Disparo", "r", {}, 0.5, utcnow(), rule_id="tape-burst-1"), token.id, None, None)
    db.commit()
    analyze_token(db, token, force=True)
    alert = db.query(Alert).filter(Alert.alert_type == "pump_burst").one()
    assert alert.status == "open"  # DEX Screener ainda não viu: o alerta continua
    alert.detected_at = utcnow() - timedelta(minutes=20)
    db.commit()
    analyze_token(db, token, force=True)
    db.refresh(alert)
    assert alert.status == "resolved"


# ---------------- Celular ----------------
def test_phone_sends_only_new_extreme_and_strong(db, fake_dex, monkeypatch, tmp_path):
    monkeypatch.setenv("NTFY_ENABLED", "true")
    config.get_settings.cache_clear()
    monkeypatch.setattr(notify, "topic_path", lambda: tmp_path / "topic.txt")
    notify.reset()
    sent = []

    def handler(request):
        sent.append((request.headers["Title"], request.content.decode(), request.headers.get("Click")))
        return httpx.Response(200, json={})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    token, _ = track_token(db, "solana", SOL_MINT)
    from app.engine.alerts import AlertCandidate, upsert_alert
    upsert_alert(db, AlertCandidate("pump_burst", "critical", "t", "antigo", {}, 0.5), token.id, None, None)
    db.commit()
    assert notify.run_once(db, client) == 0 and not sent  # ao ligar não repete aviso antigo
    db.query(Alert).update({"status": "resolved"})
    upsert_alert(db, AlertCandidate("pump_burst", "critical", "t", "novo", {}, 0.5), token.id, None, None)
    db.add(Signal(token_id=token.id, action="buy", strength="moderate", status="active", headline="fraca", reasons=[], risk_score=1, risk_level="low", opportunity_score=50, estimates=[], rules_version="sig-1"))
    db.add(Signal(token_id=token.id, action="buy", strength="strong", status="superseded", headline="forte", reasons=[], risk_score=1, risk_level="low", opportunity_score=70, estimates=[], rules_version="sig-1"))
    db.commit()
    assert notify.run_once(db, client) == 2
    assert [s[1] for s in sent] == ["novo", "forte"] and sent[0][2].endswith(SOL_MINT)
    assert notify.run_once(db, client) == 0
    notify._state["sent"] = notify.DAILY_CAP
    assert notify.send("t", "b", client=client) is False  # respeita o limite do serviço grátis
    assert (tmp_path / "topic.txt").read_text().startswith("memecoinai-") and len(notify.topic()) > 25


def test_phone_off_sends_nothing(db):
    notify.reset()
    assert notify.run_once(db) == 0 and notify.send("t", "b") is False


# ---------------- Cópia do banco e sistema de pé ----------------
def test_backup_is_valid_and_keeps_last_copies(db, fake_dex, monkeypatch, tmp_path):
    import sqlite3
    track_token(db, "solana", SOL_MINT)
    monkeypatch.setattr(backup, "backup_dir", lambda: tmp_path / "b")
    assert backup.newest_age_hours() is None
    first = backup.make_backup()
    con = sqlite3.connect(first)
    assert con.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] == 1
    con.close()
    (tmp_path / "b").mkdir(exist_ok=True)
    for i in range(8):
        (tmp_path / "b" / f"memecoinai-2020010{i}-000000.db").write_bytes(b"x")
    backup.make_backup()
    assert len(list((tmp_path / "b").glob("*.db"))) == backup.KEEP
    assert backup.newest_age_hours() < 1


def test_supervisor_backoff_and_stall(db):
    from app import agents
    assert supervisor.backoff(0) == 1 and supervisor.backoff(3) == 8 and supervisor.backoff(20) == supervisor.MAX_BACKOFF
    assert supervisor.collector_stalled() is False  # nunca rodou não é travado
    agents.beat(db, "market_hot", 30, now=utcnow() - timedelta(minutes=10))
    assert supervisor.collector_stalled() is True
    agents.beat(db, "market_hot", 30)
    assert supervisor.collector_stalled() is False


def test_compaction_keeps_one_per_ten_minutes_and_recent_untouched(db, fake_dex):
    token, _ = track_token(db, "solana", SOL_MINT)
    pair = token.primary_pair_id
    db.query(PairSnapshot).delete()
    base = (utcnow() - timedelta(days=16)).replace(minute=0, second=0, microsecond=0)
    for i in range(6):
        db.add(PairSnapshot(pair_id=pair, source="t", received_at=base + timedelta(seconds=30 * i), normalizer_version="t", payload_hash=str(i), price_usd=1.0))
    for i in range(3):
        db.add(PairSnapshot(pair_id=pair, source="t", received_at=utcnow() - timedelta(seconds=30 * i), normalizer_version="t", payload_hash=f"n{i}", price_usd=1.0))
    db.commit()
    assert compact_old_snapshots(db) == 5
    assert db.query(PairSnapshot).count() == 4


def test_api_exposes_flow_smart_and_phone(auth_client, fake_dex, db, monkeypatch, tmp_path):
    API = "/api/v1"
    auth_client.post(f"{API}/tokens/track", json={"chain_id": "solana", "address": SOL_MINT})
    assert auth_client.get(f"{API}/tokens/solana/{SOL_MINT}/exit-plan").json()["flow"] is None
    assert auth_client.get(f"{API}/tokens/solana/{SOL_MINT}").json()["smart_wallets"]["available"] is False
    assert auth_client.get(f"{API}/system/phone").json() == {"enabled": False, "url": None}


def test_live_alert_is_only_recorded_while_under_observation(db, fake_dex):
    from app.tape.__main__ import _raise_alert
    token, _ = track_token(db, "solana", SOL_MINT)
    assert config.get_settings().tape_alerts_enabled is False
    _raise_alert(token.id, {"strength": "strong", "price_usd": 1.0, "reasons": ["r"], "evidence": {}})
    assert db.query(Alert).filter(Alert.alert_type == "pump_burst").count() == 0  # não incomoda você
    con = store.connect()
    assert con.execute("SELECT COUNT(*) FROM tape_alerts").fetchone()[0] == 1  # mas segue medindo
    con.close()
