"""Build do frontend servido pela API (hospedagem única, custo zero)."""
from fastapi.testclient import TestClient

from app import config


def test_spa_served_with_fallback_and_api_isolated(tmp_path, monkeypatch, isolated_db):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nao servir", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))
    config.get_settings.cache_clear()
    from app.main import create_app

    c = TestClient(create_app())
    assert "id=root" in c.get("/").text
    assert "id=root" in c.get("/tokens/solana/abc").text  # rota do cliente
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert "nao servir" not in c.get("/../secret.txt").text
    r = c.get("/api/v1/inexistente")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    # A API continua acessível com o SPA montado (status "degraded" aqui é esperado: sem worker no teste).
    h = c.get("/api/v1/health")
    assert h.status_code == 200 and h.json()["database"] == "ok"


def test_no_frontend_build_means_no_catch_all(isolated_db, monkeypatch, tmp_path):
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(tmp_path / "nao-existe"))
    config.get_settings.cache_clear()
    from app.main import create_app

    c = TestClient(create_app())
    assert c.get("/").status_code == 404
