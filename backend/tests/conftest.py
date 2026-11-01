"""Fixtures de teste.

As respostas do DEX Screener aqui são SIMULADAS (formato copiado de uma resposta
real de 2026-10-28) e servem apenas para testes automatizados.
"""
import copy
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, db as dbmod
from app.sources.http import ResilientClient

SOL_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
SOL_PAIR = "5zpyutJu9ee6jFymDGoK7F6S5Kczqtc9FomP3ueKuyA9"
WSOL = "So11111111111111111111111111111111111111112"

PAIR_TEMPLATE = {
    "chainId": "solana",
    "dexId": "raydium",
    "url": f"https://dexscreener.com/solana/{SOL_PAIR.lower()}",
    "pairAddress": SOL_PAIR,
    "labels": ["CPMM"],
    "baseToken": {"address": SOL_MINT, "name": "Test Token", "symbol": "TEST"},
    "quoteToken": {"address": WSOL, "name": "Wrapped SOL", "symbol": "SOL"},
    "priceNative": "0.00000003106",
    "priceUsd": "0.000003187",
    "txns": {"m5": {"buys": 8, "sells": 16}, "h1": {"buys": 192, "sells": 469},
             "h6": {"buys": 7921, "sells": 9130}, "h24": {"buys": 10564, "sells": 12201}},
    "volume": {"h24": 736714.2, "h6": 641193.05, "h1": 15708.34, "m5": 705.49},
    "priceChange": {"m5": 0.35, "h1": 0.38, "h6": 4.28, "h24": 4.23},
    "liquidity": {"usd": 318553.22, "base": 69045887349, "quote": 960.09442},
    "fdv": 283215250,
    "marketCap": 283215250,
    "pairCreatedAt": 1671980424000,
    "info": {"imageUrl": "https://example.invalid/img.png",
             "socials": [{"url": "https://twitter.com/test", "type": "twitter"}]},
}


def make_pair(**overrides) -> dict:
    p = copy.deepcopy(PAIR_TEMPLATE)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k].update(v)
        else:
            p[k] = v
    return p


class FakeDex:
    """Transporte HTTP simulado para o DEX Screener (somente testes)."""

    def __init__(self):
        self.pairs: list[dict] = [make_pair()]
        self.fail = False
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.fail:
            return httpx.Response(503, json={"error": "down"})
        if request.url.path.startswith("/tokens/v1/"):
            addrs = request.url.path.split("/")[-1].split(",")
            return httpx.Response(200, json=[p for p in self.pairs if p["baseToken"]["address"] in addrs])
        if request.url.path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    def client(self):
        from app.sources.dexscreener import DexScreenerClient

        rc = ResilientClient("https://api.dexscreener.com", transport=httpx.MockTransport(self.handler),
                             sleep=lambda s: None)
        return DexScreenerClient(client=rc)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEED_INITIAL_PASSWORD", "test-initial-pw")
    # Fixa o que o backend/.env do desenvolvedor poderia alterar, para os testes
    # não dependerem da configuração local da máquina.
    monkeypatch.setenv("CHAINS", "solana")
    monkeypatch.setenv("MAX_TRACKED_TOKENS", "600")
    monkeypatch.setenv("LIST_CACHE_SECONDS", "0")
    monkeypatch.setenv("BOARD_ENABLED", "false")  # teste calcula na requisição; o painel tem teste próprio
    monkeypatch.setenv("SECURITY_GATE", "false")  # só o teste da trava liga
    monkeypatch.setenv("FRESH_MAX_AGE_SECONDS", "180")
    monkeypatch.setenv("DELAYED_MAX_AGE_SECONDS", "900")
    config.get_settings.cache_clear()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(config.BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")  # testa as migrações reais
    engine = dbmod.make_engine(url)
    dbmod.set_engine(engine)
    from app.api.auth import reset_login_limiter

    reset_login_limiter()
    # Caches em memória do motor não podem vazar de um banco de teste para outro.
    from app.engine import accuracy, burst, outcomes

    accuracy.clear_cache()
    burst.clear_cache()
    outcomes._cache.clear()
    # Rate limiters globais não devem atrasar os testes.
    from app.sources import dexscreener, solana_rpc

    from app.engine import checks
    from app.ingest import service as svc
    from app.sources.http import FetchResult

    checks._holders_paused_until = 0.0

    class _NoGecko:  # teste nunca chama rede; a descoberta pelo GeckoTerminal tem teste próprio
        def pools(self, *_):
            return FetchResult(ok=True, data=[])

    monkeypatch.setattr(svc, "GeckoTerminalClient", _NoGecko)

    class _NoJupiter:
        def listing(self, *_):
            return FetchResult(ok=True, data=[])

    monkeypatch.setattr(svc, "JupiterTokensClient", _NoJupiter)
    for lim in (dexscreener._fast_limiter, dexscreener._slow_limiter, solana_rpc._limiter):
        monkeypatch.setattr(lim, "min_interval", 0)
    yield engine
    engine.dispose()
    config.get_settings.cache_clear()


@pytest.fixture
def db(isolated_db):
    s = dbmod.session_factory()()
    yield s
    s.close()


@pytest.fixture
def fake_dex(monkeypatch):
    fake = FakeDex()
    import app.ingest.service as svc

    monkeypatch.setattr(svc, "DexScreenerClient", fake.client)
    return fake


@pytest.fixture
def client(isolated_db):
    from app.cli import cmd_seed_users
    from app.main import create_app

    cmd_seed_users([])
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def auth_client(client):
    r = client.post("/api/v1/auth/login", json={"username": "alisson", "password": "test-initial-pw"})
    assert r.status_code == 200, r.text
    return client


def wait():
    time.sleep(0.01)
