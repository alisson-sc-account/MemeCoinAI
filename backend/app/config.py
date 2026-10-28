"""Configuração carregada de variáveis de ambiente (e opcionalmente de backend/.env).

Nenhum segredo real fica no código. Veja `.env.example` na raiz do backend.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "development"
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'memecoinai.db').as_posix()}"

    # Sessões
    session_cookie_name: str = "mcai_session"
    session_ttl_hours: int = 72
    # Em produção (HTTPS) deve ser True.
    session_cookie_secure: bool = False

    # Usuários iniciais (somente para o comando `seed-users`). A senha NUNCA é versionada.
    seed_usernames: str = "natan,alisson"
    seed_initial_password: str | None = None

    # Origens permitidas para CORS (somente desenvolvimento; em produção sirva o
    # frontend na mesma origem).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Build estático do frontend servido pela própria API (mesma origem, hospedagem única).
    frontend_dist_dir: str = str(BACKEND_DIR.parent / "frontend" / "dist")

    # Coleta
    chains: str = "solana"
    max_tracked_tokens: int = 150
    refresh_interval_seconds: int = 60
    discovery_interval_seconds: int = 300
    risk_check_interval_seconds: int = 30
    evaluation_interval_seconds: int = 300
    dexscreener_base_url: str = "https://api.dexscreener.com"
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    http_timeout_seconds: float = 15.0

    # Frescor dos dados (segundos)
    fresh_max_age_seconds: int = 180
    delayed_max_age_seconds: int = 900

    # Retenção
    raw_payload_retention_days: int = 3
    snapshot_retention_days: int = 90

    # Fonte considerada indisponível após N falhas consecutivas
    source_failure_threshold: int = 3

    # Origem de quem chama o motor (para logs)
    log_level: str = "INFO"

    @property
    def chain_list(self) -> list[str]:
        return [c.strip() for c in self.chains.split(",") if c.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [c.strip() for c in self.cors_origins.split(",") if c.strip()]

    @property
    def seed_username_list(self) -> list[str]:
        return [u.strip() for u in self.seed_usernames.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
