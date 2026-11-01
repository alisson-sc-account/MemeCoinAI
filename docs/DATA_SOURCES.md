# Fontes de dados e custo

Gerado a partir de `backend/app/sources/registry.py` (fonte única; a tela **Configurações → Fontes de dados e custo** mostra a mesma lista).

Classes: **A** gratuita e ativa · **B** respondeu sem chave numa verificação pontual, mas limites/termos não confirmados (desligada) · **C** exige chave/plano ou não verificada (desligada) · **D** sem acesso neste ambiente.

Regra testada (`tests/test_ranking_registry.py`): só fontes A podem estar ligadas, nenhuma ligada exige chave, e o sistema inicia sem nenhuma chave.

| Fonte | Papel | Classe | Ligada | Integração | Verificação | Limites conhecidos | Alternativa |
|---|---|---|---|---|---|---|---|
| DEX Screener API | Descoberta, preço, liquidez, volume, transações, perfis e impulsionados | A (Gratuita e ativa) | sim | ativa e testada | 2026-10-28: Requisições reais a tokens/v1, search, token-profiles e token-boosts (latest/top) | 300 req/min (pares/busca), 60 req/min (perfis/boosts); cache de ~60 s; sem compradores únicos nem holders | Última leitura válida com idade exibida |
| Birdeye API | OHLCV, trades e overview | C (Desabilitada por custo/acesso) | não | não integrada | 2026-10-29: Sem chave respondeu HTTP 401 (Unauthorized) | exige chave/plano | DEX Screener |
| GeckoTerminal API | Pools, preço e OHLCV complementares | B (Gratuita, mas condicional) | não | não integrada | 2026-10-29: Sem chave respondeu HTTP 200 em /networks/solana/tokens/{mint}/pools | limites e termos não confirmados | DEX Screener |
| dex.fun Partner API | Streams de lançamentos e trades | C (Desabilitada por custo/acesso) | não | não integrada | Fluxograma indica beta fechado com chave; não verificado | desconhecidos | DEX Screener |
| Bitquery · DEX Trades | Trades históricos e agregações | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | depende de plano | Snapshots próprios |
| Raydium APIs / SDK | Estado de pools | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | desconhecidos | dexId/labels do DEX Screener |
| Meteora APIs / SDK | Pools e liquidez Meteora | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | desconhecidos | dexId/labels do DEX Screener |
| Orca Whirlpools SDK | Pools concentrados | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | desconhecidos | dexId/labels do DEX Screener |
| pump.fun / PumpSwap | Lançamentos, bonding curve e migração | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | desconhecidos | Descoberta via DEX Screener |
| Jupiter Price API v3 (lite) | Preço ao vivo do quadro "Quando vender" (atualização rápida, 10 s) | A (Gratuita) | não | ativa e testada | 2026-10-29: sem chave, lite-api.jup.ag/price/v3 respondeu 200 e o preço mudou a cada consulta de 10 s (cache de 5 s) | até 50 tokens por requisição; limite exato não documentado (respeita HTTP 429) | Preço do coletor (DEX Screener, ~30–60 s) |
| Jupiter Quote API (lite) | Cotação e impacto de preço (somente leitura) | B (Gratuita, mas condicional) | não | não integrada | 2026-10-29: Sem chave respondeu HTTP 200 em lite-api.jup.ag/swap/v1/quote | limites e termos não confirmados; cotação não garante execução | Estimativa x*y=k para pools de produto constante |
| Streams de mercado | Eventos de trade em tempo real | D (Indisponível) | não | não integrada | Exige provedor contratado | — | Polling a cada 30 s |
| Solana RPC público (mainnet-beta) | Autoridades do mint, Token-2022, supply, maiores contas | A (Gratuita e ativa) | sim | ativa e testada | 2026-10-28: getAccountInfo funciona; getTokenLargestAccounts respondeu 429 de forma constante | limites não documentados por método; holders ficam 'indisponível' | RPC próprio opcional via SOLANA_RPC_URL |
| RPC secundário de contingência | Failover e comparação | D (Indisponível) | não | não integrada | Nenhum configurado | — | Somente o RPC público |
| Helius Enhanced APIs / Webhooks | Transações parseadas e webhooks | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; exige conta e chave | depende do plano | RPC público |
| Yellowstone gRPC / Geyser | Stream de baixa latência | D (Indisponível) | não | não integrada | Exige provedor compatível | — | Polling |
| QuickNode Streams / RPC | RPC e streams alternativos | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; exige conta | depende do plano | RPC público |
| Shyft APIs | Dados parseados | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | depende do plano | RPC público |
| Solscan API | Explorador de transações e carteiras | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | depende do plano | — |
| Dune API / queries | Análises históricas | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | créditos/plano | — |
| X API · Filtered Stream | Posts por regra | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; acesso exige credencial e plano | — | Ranking sem dados sociais (cobertura reduzida) |
| X API · Recent Search | Busca recente | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | Ranking sem dados sociais |
| X API · Full-Archive Search | Backfill histórico | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | Ranking sem dados sociais |
| Reddit API | Discussões de comunidades | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; exige app OAuth e termos | — | — |
| Telegram Bot API | Canais com acesso autorizado | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; exige bot e acesso a cada canal | — | — |
| Busca web / RSS / notícias | Notícias e anúncios públicos | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | por site | — |
| Fontes sociais alternativas | Integrações opcionais | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |
| Tendências e comunidades | Temas emergentes | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |
| GoPlus Solana Token Security | Verificações de segurança do token | B (Gratuita, mas condicional) | não | não integrada | 2026-10-29: Sem chave respondeu HTTP 200 em /api/v1/solana/token_security | limites e termos não confirmados | Verificação própria via RPC (mint/freeze/Token-2022) |
| RugCheck | Indicadores de risco e distribuição | B (Gratuita, mas condicional) | não | não integrada | 2026-10-29: Sem chave respondeu HTTP 200 em /v1/tokens/{mint}/report/summary | limites e termos não confirmados | Verificação própria via RPC |
| Bubblemaps | Relações entre holders | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |
| GMGN wallet / trader data | Atividade de carteiras | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |
| Nansen Smart Money | Rótulos de carteiras | C (Desabilitada por custo/acesso) | não | não integrada | não verificado; plano pago | — | — |
| Bitquery · Wallet analytics | Histórico de carteiras | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | depende de plano | — |
| Exploradores / wallet history | Histórico complementar | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |
| Jito / prioridade de transação | Contexto de execução | C (Desabilitada por custo/acesso) | não | não integrada | Fora do escopo: o sistema não executa transações | — | — |
| Listas de tokens / verificações | Metadados de listas | C (Desabilitada por custo/acesso) | não | não integrada | não verificado | — | — |

## O que funciona sem nenhuma chave

- **DEX Screener** (classe A): descoberta, preço, liquidez, volume, contagem de transações, perfis e impulsionados.
- **RPC público Solana** (classe A): autoridades de mint/freeze e extensões Token-2022. A consulta de maiores contas (`getTokenLargestAccounts`) responde 429 de forma constante: a concentração de holders aparece como **indisponível** e reduz a cobertura, sem bloquear o ranking.

## Quando uma fonte atinge o limite

`app/sources/http.py`: timeout em toda chamada, retry só para erros transitórios (429, 5xx, rede), backoff exponencial respeitando `Retry-After`, limite máximo de tentativas, nunca loop infinito. Fonte com 3 falhas seguidas vira `down`, gera alerta de sistema e a interface marca os dados como atrasados. Nada tenta pagar ou mudar de plano.
