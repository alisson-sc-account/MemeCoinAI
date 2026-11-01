"""Registro central das fontes do fluxograma e sua classificação de custo/acesso.

Classes (política de custo zero):
- A "GRATUITA E ATIVA": caminho público usado e testado neste projeto; limites registrados.
- B "GRATUITA, MAS CONDICIONAL": respondeu sem chave numa verificação pontual, mas limites,
  termos ou estabilidade não foram confirmados. Nunca ativada por padrão.
- C "DESABILITADA POR CUSTO/ACESSO": exige chave, plano, cadastro ou condição não verificada.
- D "INDISPONÍVEL": não há acesso válido neste ambiente.

Regra: só fontes da classe A podem estar habilitadas. `verified_on` só é preenchido
quando houve requisição real; o resto fica "não verificado".
"""
from dataclasses import asdict, dataclass

ACCESS_LABELS = {
    "A": "Gratuita e ativa",
    "B": "Gratuita, mas condicional",
    "C": "Desabilitada por custo/acesso",
    "D": "Indisponível",
}


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    role: str
    access_class: str
    enabled: bool
    integration: str  # "ativa e testada" | "não integrada"
    needs_key: bool | None
    verified_on: str | None
    verification: str
    limits: str
    fallback: str

    def as_dict(self) -> dict:
        return {**asdict(self), "access_label": ACCESS_LABELS[self.access_class]}


_NV = "não verificado"
_NOT = "não integrada"

SOURCES: tuple[SourceInfo, ...] = (
    # --- Mercado / DEX --------------------------------------------------------------
    SourceInfo("dexscreener", "DEX Screener API", "Descoberta, preço, liquidez, volume, transações, perfis e impulsionados",
               "A", True, "ativa e testada", False, "2026-10-28",
               "Requisições reais a tokens/v1, search, token-profiles e token-boosts (latest/top)",
               "300 req/min (pares/busca), 60 req/min (perfis/boosts); cache de ~60 s; sem compradores únicos nem holders",
               "Última leitura válida com idade exibida"),
    SourceInfo("birdeye", "Birdeye API", "OHLCV, trades e overview", "C", False, _NOT, True, "2026-10-29",
               "Sem chave respondeu HTTP 401 (Unauthorized)", "exige chave/plano", "DEX Screener"),
    SourceInfo("geckoterminal", "GeckoTerminal API", "Descoberta de pools novas e em alta", "A", True, "ativa e testada", False, "2026-10-30",
               "Sem chave respondeu HTTP 200 em new_pools e trending_pools; página 11 responde 401", "30 req/min; até 10 páginas",
               "Descoberta pelo DEX Screener"),
    SourceInfo("dexfun", "dex.fun Partner API", "Streams de lançamentos e trades", "C", False, _NOT, True, None,
               "Fluxograma indica beta fechado com chave; " + _NV, "desconhecidos", "DEX Screener"),
    SourceInfo("bitquery_trades", "Bitquery · DEX Trades", "Trades históricos e agregações", "C", False, _NOT, True, None,
               _NV, "depende de plano", "Snapshots próprios"),
    SourceInfo("raydium", "Raydium APIs / SDK", "Estado de pools", "C", False, _NOT, None, None, _NV, "desconhecidos",
               "dexId/labels do DEX Screener"),
    SourceInfo("meteora", "Meteora APIs / SDK", "Pools e liquidez Meteora", "C", False, _NOT, None, None, _NV, "desconhecidos",
               "dexId/labels do DEX Screener"),
    SourceInfo("orca", "Orca Whirlpools SDK", "Pools concentrados", "C", False, _NOT, None, None, _NV, "desconhecidos",
               "dexId/labels do DEX Screener"),
    SourceInfo("pumpfun", "pump.fun / PumpSwap", "Lançamentos, bonding curve e migração", "C", False, _NOT, None, None,
               _NV, "desconhecidos", "Descoberta via DEX Screener"),
    SourceInfo("jupiter_price", "Jupiter Price API v3 (lite)", "Preço ao vivo do quadro \"Quando vender\" (atualização rápida, 10 s)",
               "A", True, "ativa e testada", False, "2026-10-29",
               "Sem chave: lite-api.jup.ag/price/v3 respondeu 200 e o preço mudou a cada consulta de 10 s (cache de 5 s)",
               "até 50 tokens por requisição; limite exato não documentado (respeita HTTP 429)",
               "Preço do coletor (DEX Screener, ~30–60 s)"),
    SourceInfo("solana_pool", "Reservas da pool na Solana (RPC público)", "Preço a cada ~1 s da moeda aberta",
               "A", True, "ativa e testada", False, "2026-10-30",
               "getMultipleAccounts a 1 req/s respondeu 200; razão das reservas conferida em pump.fun e Raydium CPMM; PumpSwap exige calibração",
               "só pools de produto constante; RPC público limita por IP", "Cotação de 10 s (Jupiter)"),
    SourceInfo("jupiter_tokens", "Listas de tokens da Jupiter", "Descoberta: mais negociados, em alta e recentes",
               "A", True, "ativa e testada", False, "2026-10-30", "/tokens/v2/recent e /toptraded/1h responderam 200 sem chave",
               "5 chamadas por 10 s somando as APIs lite", "Descoberta pelo DEX Screener e GeckoTerminal"),
    SourceInfo("rugcheck_security", "RugCheck (relatório público)", "Liquidez travada, maiores donos, insiders",
               "A", True, "ativa e testada", False, "2026-10-30", "/v1/tokens/{mint}/report respondeu 200 sem chave",
               "x-rate-limit-limit 15; lista de donos inclui a pool (excluída aqui)", "Veredito \"Sem dados\": nunca aprova sem verificar"),
    SourceInfo("publicnode_rpc", "RPC Solana publicnode", "Triagem de carteiras (carteira nova, parada ou muito ativa)",
               "A", True, "ativa e testada", False, "2026-10-30", "20 chamadas de getSignaturesForAddress seguidas responderam 200 sem chave",
               "guarda só ~63 h de histórico: não prova idade sozinho", "Carteira fica como idade desconhecida"),
    SourceInfo("jupiter_quote", "Jupiter Quote API (lite)", "Cotação e impacto de preço (somente leitura)", "B", False, _NOT,
               False, "2026-10-29", "Sem chave respondeu HTTP 200 em lite-api.jup.ag/swap/v1/quote",
               "limites e termos não confirmados; cotação não garante execução", "Estimativa x*y=k para pools de produto constante"),
    SourceInfo("market_streams", "Streams de mercado", "Eventos de trade em tempo real", "D", False, _NOT, True, None,
               "Exige provedor contratado", "—", "Polling a cada 30 s"),
    # --- On-chain / RPC -------------------------------------------------------------
    SourceInfo("solana_rpc", "Solana RPC público (mainnet-beta)", "Autoridades do mint, Token-2022, supply, maiores contas",
               "A", True, "ativa e testada", False, "2026-10-28",
               "getAccountInfo funciona; getTokenLargestAccounts respondeu 429 de forma constante",
               "limites não documentados por método; holders ficam 'indisponível'", "RPC próprio opcional via SOLANA_RPC_URL"),
    SourceInfo("rpc_secondary", "RPC secundário de contingência", "Failover e comparação", "D", False, _NOT, None, None,
               "Nenhum configurado", "—", "Somente o RPC público"),
    SourceInfo("helius", "Helius Enhanced APIs / Webhooks", "Transações parseadas e webhooks", "C", False, _NOT, True, None,
               _NV + "; exige conta e chave", "depende do plano", "RPC público"),
    SourceInfo("yellowstone", "Yellowstone gRPC / Geyser", "Stream de baixa latência", "D", False, _NOT, True, None,
               "Exige provedor compatível", "—", "Polling"),
    SourceInfo("quicknode", "QuickNode Streams / RPC", "RPC e streams alternativos", "C", False, _NOT, True, None,
               _NV + "; exige conta", "depende do plano", "RPC público"),
    SourceInfo("shyft", "Shyft APIs", "Dados parseados", "C", False, _NOT, True, None, _NV, "depende do plano", "RPC público"),
    SourceInfo("solscan", "Solscan API", "Explorador de transações e carteiras", "C", False, _NOT, True, None, _NV,
               "depende do plano", "—"),
    SourceInfo("dune", "Dune API / queries", "Análises históricas", "C", False, _NOT, True, None, _NV, "créditos/plano", "—"),
    # --- Social --------------------------------------------------------------------
    SourceInfo("x_filtered_stream", "X API · Filtered Stream", "Posts por regra", "C", False, _NOT, True, None,
               _NV + "; acesso exige credencial e plano", "—", "Ranking sem dados sociais (cobertura reduzida)"),
    SourceInfo("x_recent_search", "X API · Recent Search", "Busca recente", "C", False, _NOT, True, None, _NV, "—",
               "Ranking sem dados sociais"),
    SourceInfo("x_full_archive", "X API · Full-Archive Search", "Backfill histórico", "C", False, _NOT, True, None, _NV, "—",
               "Ranking sem dados sociais"),
    SourceInfo("reddit", "Reddit API", "Discussões de comunidades", "C", False, _NOT, True, None,
               _NV + "; exige app OAuth e termos", "—", "—"),
    SourceInfo("telegram", "Telegram Bot API", "Canais com acesso autorizado", "C", False, _NOT, True, None,
               _NV + "; exige bot e acesso a cada canal", "—", "—"),
    SourceInfo("rss_web", "Busca web / RSS / notícias", "Notícias e anúncios públicos", "C", False, _NOT, False, None,
               _NV, "por site", "—"),
    SourceInfo("social_alt", "Fontes sociais alternativas", "Integrações opcionais", "C", False, _NOT, None, None, _NV, "—", "—"),
    SourceInfo("trends", "Tendências e comunidades", "Temas emergentes", "C", False, _NOT, None, None, _NV, "—", "—"),
    # --- Segurança / carteiras ------------------------------------------------------
    SourceInfo("goplus", "GoPlus Solana Token Security", "Verificações de segurança do token", "B", False, _NOT, False,
               "2026-10-29", "Sem chave respondeu HTTP 200 em /api/v1/solana/token_security", "limites e termos não confirmados",
               "Verificação própria via RPC (mint/freeze/Token-2022)"),
    SourceInfo("rugcheck", "RugCheck", "Indicadores de risco e distribuição", "B", False, _NOT, False, "2026-10-29",
               "Sem chave respondeu HTTP 200 em /v1/tokens/{mint}/report/summary", "limites e termos não confirmados",
               "Verificação própria via RPC"),
    SourceInfo("bubblemaps", "Bubblemaps", "Relações entre holders", "C", False, _NOT, True, None, _NV, "—", "—"),
    SourceInfo("gmgn", "GMGN wallet / trader data", "Atividade de carteiras", "C", False, _NOT, None, None, _NV, "—", "—"),
    SourceInfo("nansen", "Nansen Smart Money", "Rótulos de carteiras", "C", False, _NOT, True, None, _NV + "; plano pago",
               "—", "—"),
    SourceInfo("bitquery_wallet", "Bitquery · Wallet analytics", "Histórico de carteiras", "C", False, _NOT, True, None, _NV,
               "depende de plano", "—"),
    SourceInfo("explorers", "Exploradores / wallet history", "Histórico complementar", "C", False, _NOT, None, None, _NV,
               "—", "—"),
    SourceInfo("jito", "Jito / prioridade de transação", "Contexto de execução", "C", False, _NOT, None, None,
               "Fora do escopo: o sistema não executa transações", "—", "—"),
    SourceInfo("token_lists", "Listas de tokens / verificações", "Metadados de listas", "C", False, _NOT, None, None, _NV,
               "—", "—"),
)


def registry() -> list[dict]:
    return [s.as_dict() for s in SOURCES]


def validate_policy() -> list[str]:
    """Retorna violações da política de custo zero (lista vazia = ok)."""
    problems = []
    for s in SOURCES:
        if s.enabled and s.access_class != "A":
            problems.append(f"{s.key}: habilitada com classe {s.access_class}")
        if s.enabled and s.needs_key:
            problems.append(f"{s.key}: habilitada mas exige chave")
        if s.access_class == "A" and not s.verified_on:
            problems.append(f"{s.key}: classe A sem verificação registrada")
    return problems
