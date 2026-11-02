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
    # 20 mil tokens não cabem nos 300/min do DEX Screener a cada ciclo: os quentes (com
    # sinal, posição, favorito ou mais volume) atualizam todo ciclo; os frios, em rodízio. Nenhuma fonte expõe "todos os tokens": o universo é o
    # que a descoberta encontra (perfis, impulsionados, buscas e GeckoTerminal).
    max_tracked_tokens: int = 20000
    # 30 s: a fonte usa cache de ~60 s, então metade das coletas pode repetir dados
    # (deduplicadas); em troca, a mudança aparece até 30 s mais cedo.
    refresh_interval_seconds: int = 30
    refresh_hot_tokens: int = 1500  # 50 req a cada 30 s
    refresh_requests_per_cycle: int = 75
    refresh_cold_requests_per_cycle: int = 70  # 140 req/min: 4200 moedas/min em rodízio
    discovery_interval_seconds: int = 60
    risk_check_interval_seconds: int = 30
    risk_checks_per_cycle: int = 15
    evaluation_interval_seconds: int = 120
    # Termos de busca usados para ampliar a descoberta (rotacionados a cada ciclo).
    discovery_queries: str = (
        "pump,sol,bonk,cat,dog,ai,moon,pepe,inu,meme,coin,baby,elon,trump,wif,"
        "gold,king,fun,god,bull,bear,rocket,degen,chad,frog,duck,bird,fish,money,new,"
        "shib,floki,monkey,ape,wolf,tiger,lion,panda,robot,agent,gpt,trade,cash,"
        "rich,based,mega,super,hyper,space,mars,galaxy,star,sun,fire,ice,dragon,ninja,"
        "pixel,game,meta,zero,alpha,labs,dao,bro,mom,dad,kid,girl,boy,cute,wojak"
    )
    discovery_queries_per_cycle: int = 30
    # GeckoTerminal: pools novas e em alta, sem o viés das listas pagas (máx. 10 páginas).
    geckoterminal_base_url: str = "https://api.geckoterminal.com/api/v2"
    geckoterminal_pages_per_cycle: int = 2  # com 5 páginas por minuto a fonte respondeu 429
    discovery_min_liquidity_usd: float = 3000.0
    # Deixa de monitorar tokens sem vida para liberar o orçamento de coleta.
    prune_after_hours: int = 3
    prune_min_liquidity_usd: float = 1500.0
    prune_min_volume_h24_usd: float = 1000.0
    dexscreener_base_url: str = "https://api.dexscreener.com"
    # Atualização rápida (`python -m app.live`): só os tokens com o quadro "Quando vender"
    # aberto e os que têm posição registrada. Fonte: Jupiter Price API v3 (sem chave;
    # cache de 5 s, até 50 tokens por requisição). O DEX Screener não serve para isso:
    # o cache dele segura o mesmo preço por ~30 s.
    live_interval_seconds: int = 10
    live_focus_ttl_seconds: int = 5  # moeda aberta: reservas lidas a cada ~1 s na blockchain
    live_focus_max_tokens: int = 10
    list_cache_seconds: float = 15.0  # listas de 10 mil tokens são calculadas no máximo a cada 15 s
    live_watch_ttl_seconds: int = 60  # quadro fechado há mais que isso: para de acompanhar
    live_max_tokens: int = 100
    live_retention_hours: int = 24
    solana_history_rpc_url: str = "https://solana-rpc.publicnode.com"  # só ~63 h de histórico: triagem de carteiras
    rugcheck_base_url: str = "https://api.rugcheck.xyz/v1"
    board_enabled: bool = True  # listas prontas em data/board.db (python -m app.board)
    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_enabled: bool = True  # aviso no celular, grátis e sem conta (app/notify.py)
    tape_alerts_enabled: bool = False  # em observação: na prova ficou bem abaixo do disparo pela coleta
    security_gate: bool = True  # compra forte exige verificação de segurança limpa
    jupiter_price_base_url: str = "https://lite-api.jup.ag"
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    http_timeout_seconds: float = 15.0

    # Frescor dos dados (segundos)
    fresh_max_age_seconds: int = 180
    delayed_max_age_seconds: int = 900

    # Retenção
    raw_payload_retention_days: int = 1  # aplicada sozinha pelo worker
    store_raw_payload: bool = False  # com 10 mil tokens o bruto custaria ~17 GB/dia
    snapshot_retention_days: int = 180  # mais histórico; depois de 15 dias fica 1 foto a cada 10 min

    # Fonte considerada indisponível após N falhas consecutivas
    source_failure_threshold: int = 3

    # Origem de quem chama o motor (para logs)
    log_level: str = "INFO"

    @property
    def chain_list(self) -> list[str]:
        return [c.strip() for c in self.chains.split(",") if c.strip()]

    @property
    def discovery_query_list(self) -> list[str]:
        """Termos configurados + combinações de duas letras: cada busca traz outros 30 pares."""
        words = [q.strip() for q in self.discovery_queries.split(",") if q.strip()]
        letters = "abcdefghijklmnopqrstuvwxyz"
        return words + [a + b for a in letters for b in letters]

    @property
    def cors_origin_list(self) -> list[str]:
        return [c.strip() for c in self.cors_origins.split(",") if c.strip()]

    @property
    def seed_username_list(self) -> list[str]:
        return [u.strip() for u in self.seed_usernames.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
