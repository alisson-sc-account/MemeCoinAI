"""Regressão: coletor não pode segurar a trava de escrita do SQLite durante a rede.

Erro real observado em 2026-10-29: `sqlite3.OperationalError: database is locked`
na API (`UPDATE user_sessions`) enquanto o worker fazia chamadas lentas ao RPC.
"""
import sqlite3

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.ingest.service import collector_run
from app.models import CollectorRun


def _db_path(engine) -> str:
    return engine.url.database


def test_collector_run_does_not_hold_write_lock(db, isolated_db):
    other = sqlite3.connect(_db_path(isolated_db), timeout=0.2)
    with collector_run(db, "solana_rpc", "token_checks") as run:
        run.items_received += 1  # simula trabalho / espera de rede dentro do bloco
        # Outra conexão (a API) precisa conseguir escrever agora, sem esperar o fim do bloco.
        other.execute("CREATE TABLE IF NOT EXISTS probe (x INTEGER)")
        other.execute("INSERT INTO probe VALUES (1)")
        other.commit()
    other.close()
    saved = db.query(CollectorRun).filter_by(job="token_checks").one()
    assert saved.status == "ok" and saved.items_received == 1 and saved.finished_at is not None


def test_collector_run_records_error(db):
    try:
        with collector_run(db, "dexscreener", "refresh"):
            raise RuntimeError("falha simulada")
    except RuntimeError:
        pass
    saved = db.query(CollectorRun).filter_by(job="refresh").one()
    assert saved.status == "error" and "falha simulada" in saved.error_message


def test_api_returns_503_when_database_is_busy(isolated_db, monkeypatch, tmp_path):
    from app import config
    from app.main import create_app

    # Sem build do frontend, para a rota "catch-all" do SPA não capturar a rota de teste.
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(tmp_path / "sem-build"))
    config.get_settings.cache_clear()
    app = create_app()

    @app.get("/api/v1/_teste_banco_ocupado")
    def busy():
        raise OperationalError("UPDATE x", {}, sqlite3.OperationalError("database is locked"))

    r = TestClient(app).get("/api/v1/_teste_banco_ocupado")
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_busy"
    assert r.headers["retry-after"] == "2"
