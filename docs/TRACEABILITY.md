# Rastreabilidade: fluxograma → código → testes

Fonte de verdade: exportação textual do fluxograma (143 blocos) colada pelo proprietário em 2026-10-29. O arquivo `Downloads/memecoinai_fluxograma_editavel.html` em disco contém só a versão original (53 blocos); as edições ficam no `localStorage` do navegador (`memecoinai-flow-v2`). O fluxograma não foi alterado.

Estados: **testado** (código + teste executado) · **implementado** (código, verificado manualmente) · **parcial** · **ausente** · **bloqueado** (custo/acesso) · **agrupado** (coberto por outro módulo).

Arquitetura escolhida: monólito modular (FastAPI + worker Python + SQLite + React), sem microsserviços. Vários blocos são cobertos por um só módulo.

## Fontes (blocos 1–36)

Registro completo com classe de custo em [`DATA_SOURCES.md`](DATA_SOURCES.md) e `backend/app/sources/registry.py`.

| Blocos | Estado | Código | Teste |
|---|---|---|---|
| 1 DEX Screener | testado (classe A, ligada) | `sources/dexscreener.py` | `test_flow.py`, `test_burst_discovery.py` |
| 12 Solana RPC | testado (A); holders bloqueados por 429 | `sources/solana_rpc.py`, `engine/checks.py` | `test_units.py` |
| 3, 10, 28, 29 GeckoTerminal, Jupiter, GoPlus, RugCheck | B: responderam sem chave, **não integradas** | `registry.py` | `test_ranking_registry.py` |
| 2 Birdeye | C: 401 sem chave | `registry.py` | idem |
| 4–9, 11, 13–27, 30–36 | C/D: não verificadas, exigem chave/plano ou fora do escopo | `registry.py` | idem |

## Infraestrutura de dados (37–46)

| Bloco | Estado | Código | Teste |
|---|---|---|---|
| 37 Adaptadores | parcial (2 fontes) | `sources/*.py` | `test_units.py` |
| 38 Normalizador | testado | `ingest/normalize.py` | `test_units.py` |
| 39 Limites/quotas | parcial: rate limit, backoff, `Retry-After`, `down` após 3 falhas; sem orçamento diário | `sources/http.py` | `test_units.py` |
| 40 Saúde/frescor | testado | `ingest/service.py::source_status`, `api/views.py::freshness`, `api/system.py::worker_status` | `test_flow.py`, `test_ranking_registry.py` |
| 41 Reconciliação | ausente (uma fonte de mercado) | — | — |
| 42 Fila de jobs | agrupado: agendador do worker + `collector_runs`; sem fila durável | `worker.py` | `test_db_contention.py` |
| 43 Identidade canônica | testado: rede + mint; par separado | `models.py`, `normalize.py` | `test_units.py` |
| 44 Orçamento/priorização | parcial: verificações de contrato priorizadas por oportunidade | `engine/checks.py::run_due_checks` | — |
| 45 Portão de qualidade | testado: ausente ≠ 0, `missing_fields` | `normalize.py`, `ranking.py` | `test_units.py`, `test_ranking_registry.py` |
| 46 Credenciais | implementado: nenhuma chave necessária; `.env` fora do Git | `config.py` | `test_ranking_registry.py` (inicia sem chaves) |

## Descoberta (47–55)

| Bloco | Estado | Código |
|---|---|---|
| 47 Descoberta DEX | testado (perfis, impulsionados, buscas rotacionadas); on-chain ausente | `ingest/service.py::discover` |
| 48 Launchpads | ausente (pump.fun só via dexId do DEX Screener) | — |
| 49 Ciclo de vida | parcial: idade do par e limpeza de inativos | `ingest/service.py::prune_inactive` |
| 50 Revisor inicial | testado | `engine/scoring.py` |
| 51 Watchlist/universo | testado | `tokens.is_tracked`, `POST /tokens/track`, `prune_inactive` |
| 52 Narrativa social | bloqueado (sem fonte social gratuita verificada) | — |
| 53 Fila de candidatos | testado | `engine/ranking.py`, `GET /opportunities` |
| 54 Backfill | ausente (fonte gratuita não fornece histórico) | — |
| 55 Recuperação de eventos | parcial: deduplicação de snapshots; sem replay por slot | `ingest/service.py` |

## Social (56–67)

Todos **bloqueados por acesso/custo**: nenhuma fonte social gratuita foi verificada. O ranking funciona sem esses dados e mostra "Sinais sociais (nenhuma fonte social gratuita ativa)" em `missing_data` (teste `test_good_market_without_social_or_holders_still_gets_positive_tier`).

## Carteiras e on-chain avançado (68–78)

| Bloco | Estado |
|---|---|
| 68–73, 75–77 Histórico de carteiras, smart money, fresh wallets, funding, grafo, bundles, criador, insiders, wash trading on-chain | ausentes: exigem histórico de transações (indexador) que o RPC público não oferece no volume necessário |
| 74 Distribuição de holders | implementado (`checks.py::parse_largest_accounts`), na prática **indisponível** (429): aparece como análise parcial |
| 78 Registro de evidências | parcial: `risk_checks` e evidência por fator em `analyses` |

## Mercado (79–89)

| Bloco | Estado | Código |
|---|---|---|
| 79 Trades e preço | parcial: snapshots com contagem de transações (não trades individuais) | `ingest/service.py::refresh_tracked` |
| 80 Candles OHLCV | ausente: gráfico mostra snapshots próprios | `components/PriceChart.tsx` |
| 81 Momentum | testado | `engine/features.py`, `engine/burst.py` |
| 82 Gráfico artificial | ausente | — |
| 83 Compradores/vendedores | parcial: proporção de transações (não carteiras únicas) | `features.py` |
| 84 Liquidez/slippage | parcial: só pools x*y=k | `engine/slippage.py` |
| 85 Regime de mercado | ausente | — |
| 86 Padrões históricos | testado (versão simples por faixas de score) | `engine/outcomes.py`, `burst.py::pattern_stats` |
| 87 Força relativa | testado | `engine/ranking.py` |
| 88 Anomalias | parcial: disparo (`burst-1`), fatores A3/A4 | `burst.py`, `scoring.py` |
| 89 Supply/mcap/FDV | parcial: valores do DEX Screener, origem identificada | `MarketOut` |

## Risco (90–99)

| Bloco | Estado | Código |
|---|---|---|
| 90 Rugpull | parcial: combinação de fatores | `scoring.py` |
| 91 Mint/freeze | testado | `checks.py::parse_mint_account` |
| 92 LP removível | ausente (só queda de liquidez observada) | — |
| 93 Concentração | parcial/indisponível (contas, não clusters) | `scoring.py` (C1) |
| 94 Rug/manipulação | parcial (A1–A4, L2) | `scoring.py` |
| 95 Execução | parcial | `slippage.py`, fatores de liquidez |
| 96 Classificador de evidências | parcial: severidade + confiança por fator | `scoring.py` |
| 97 Bloqueios críticos | testado | `ranking.py::HARD_VETO_FACTORS` |
| 98 Expiração/rechecagem | implementado: recheck de 1 h, auto-resolução de alertas | `checks.py`, `alerts.py` |
| 99 Falsos positivos | ausente (há `/signals/performance` como base) | — |

## Banco (100–109)

Todos em SQLite com migrações Alembic (`0001`–`0003`). 100 `tokens`/`pairs` · 101 `pair_snapshots` (parcial: sem trades) · 102 posts sociais **ausente** · 103 carteiras **ausente** · 104 `risk_checks` + fatores · 105 `analyses.features` versionadas · 106 `signals`, `predictions`, `analysis_outcomes` · 107 `collector_runs` (parcial: sem auditoria de configuração) · 108 cache: deduplicação + caches em memória (parcial) · 109 payload bruto com retenção de 3 dias.

## Decisão (110–121)

| Bloco | Estado | Código | Teste |
|---|---|---|---|
| 110 Features | parcial: janelas 5m/1h/6h/24h da fonte (não 15s/1m) | `features.py` | `test_units.py` |
| 111 Cobertura/confiança | testado | `scoring.py`, `ranking.py` | `test_ranking_registry.py` |
| 112 Ranking contínuo | testado | `GET /opportunities` | idem |
| 113 Níveis | testado | `ranking.py` | idem |
| 114 Motor central | implementado (sem social, carteiras e regime) | `signals.py::decide`, `ranking.py::classify` | `test_signals.py` |
| 115 Portão proporcional | testado | `signals.py::decide`, vetos | `test_ranking_registry.py` |
| 116 Dimensionador | testado | `signals.py::allocation` | `test_signals.py` |
| 117 Card de ação | parcial: sem alvo/stop numérico | `features/signals.tsx`, `features/buynow.tsx` | `signals.test.tsx` |
| 118 Explicador | testado | `reasons_for/against`, fatores | idem |
| 119 SEM SINAL CONFIÁVEL | testado (exceção, não padrão) | `ranking.py` | idem |
| 120 Reavaliação | testado: histerese de 5 pontos | `signals.py` | `test_hysteresis_keeps_buy_on_small_drop` |
| 121 Prioridade | parcial: token aberto não acelera a coleta | `checks.py` | — |

## Validação (122–131)

122 backtester **parcial** (rótulos sem vazamento, sem divisão treino/teste de regras) · 123 paper trading **ausente** · 124 calibração **implementado sem amostra** (`predict.py::compute_metrics`) · 125 métricas **parcial** · 126 experimentos **ausente** · 127 aprendizado **ausente** (versões registradas) · 128 biblioteca de padrões **ausente** · 129 drift **ausente** · 130 replay **parcial** (features e versão por análise) · 131 benchmark **parcial** (taxa-base nas previsões).

## Interface e alertas (132–143)

| Bloco | Estado | Código |
|---|---|---|
| 132 Orquestrador de alertas | testado (deduplicação, escalada, auto-resolução) | `engine/alerts.py` |
| 133 API | testado | `backend/app/api/*` |
| 134 Push/WebSocket | não: polling de 30 s (fallback previsto) | — |
| 135–138 Quatro abas | testado: Dashboard, Compre agora, Alertas, Configurações | `App.tsx`, `features/buynow.tsx` |
| 139 Detalhe do token | implementado (sem holders/clusters/social/candles) | `App.tsx::TokenDetailPage` |
| 140 Saúde do sistema | implementado dentro do Dashboard/Configurações + `/system` | `WorkerStatusCard`, `SourcesRegistry` |
| 141 Notificações | implementado: modal, som, notificação do navegador | `features/signals.tsx`, `sound.ts` |
| 142 Autenticação | testado (cookie httpOnly, Argon2, 127.0.0.1) | `api/auth.py` |
| 143 Monitoramento global | testado: worker independente da aba + trava de instância única | `worker.py`, `worker_lock.py` |
