# Arquitetura — MemeCoinAI

Estado (2026-10-29): **backend, motor e interface implementados e testados** (98 testes backend, 24 frontend), verificados com dados reais. Interface com exatamente quatro abas: Dashboard, Compre agora, Alertas e Configurações. Rastreabilidade bloco a bloco em [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md); fontes e custo em [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

## Visão geral

```
                ┌──────────────────────── worker (processo contínuo) ─────────────────────────┐
DEX Screener ──▶│ sources/dexscreener ─▶ ingest/normalize ─▶ ingest/service ─▶ pair_snapshots │
Solana RPC   ──▶│ sources/solana_rpc  ─▶ engine/checks ─────────────────────▶ risk_checks     │
                │                     engine/features ─▶ engine/scoring ─▶ analyses           │
                │                     engine/alerts (dedup) ─▶ alerts                          │
                │                     engine/predict ─▶ predictions ─▶ avaliação posterior     │
                └───────────────────────────────┬──────────────────────────────────────────────┘
                                                │ banco (SQLite dev / PostgreSQL prod)
                ┌───────────────────────────────┴────────────────┐
                │ API FastAPI /api/v1 (sessão em cookie httpOnly) │◀── frontend (React, Codex)
                └────────────────────────────────────────────────┘
```

API e worker são **processos separados** que compartilham apenas o banco. Se uma fonte cair, a API continua respondendo e marca os dados como `delayed`/`stale` (ver Frescor).

## Módulos (backend/app)

| Responsabilidade lógica | Módulo | Notas |
|---|---|---|
| API/backend | `main.py`, `api/*` | FastAPI; OpenAPI em `/api/v1/openapi.json`; exportado em `docs/openapi.json` |
| Autenticação/autorização | `api/auth.py`, `api/deps.py`, `security.py` | Argon2id; sessão opaca (SHA-256 no banco); cookie httpOnly SameSite=Lax |
| Coleta de mercado | `ingest/service.py` | descoberta, watchlist, refresh em lotes de 30 endereços |
| Adaptadores de fonte | `sources/dexscreener.py`, `sources/solana_rpc.py`, `sources/http.py` | retry/backoff, limite de taxa, latência |
| Normalização | `ingest/normalize.py` | versão `dexs-1`; ausente = `None`, nunca 0 |
| Persistência | `models.py`, `db.py`, `migrations/` | SQLAlchemy 2 + Alembic; datas UTC (`UTCDateTime`) |
| Indicadores | `engine/features.py` | features com corte temporal `as_of` (sem vazamento) |
| Antifraude/risco | `engine/checks.py`, `engine/scoring.py` | regras versionadas `risk-1` |
| Oportunidade | `engine/scoring.py` | `opp-1` |
| Slippage/saída | `engine/slippage.py` | só pools de produto constante |
| Alertas | `engine/alerts.py` | `alerts-1`, deduplicação por regra+token |
| Previsão e avaliação | `engine/predict.py` | `heuristic-logit` v1 **não calibrado** + baseline de taxa-base |
| Execução periódica | `worker.py` | loop único, jobs isolados |
| Logs | `logging_setup.py` | nunca registra senhas/tokens |
| Inteligência de carteiras | — | **não iniciado** (Fase 7; depende de RPC/indexador com cota) |
| Dados sociais | — | somente links declarados na fonte; **sem métricas sociais** |
| Interface web | `frontend/` | **testado**: 4 abas; build servido por `main.py::_mount_frontend` |
| Níveis de oportunidade | `engine/ranking.py`, `api/opportunities.py` | `rank-1`: vetos, qualidade da decisão, score/confiança/cobertura separados |
| Registro de fontes | `sources/registry.py` | 36 fontes do fluxograma com classe A/B/C/D; só A ligadas |
| Instância única do worker | `worker_lock.py` | trava de arquivo do SO em `backend/data/worker.lock` |

## Fluxo de dados

1. **Descoberta** (`discover`, a cada 300 s): `token-profiles/latest/v1` e `token-boosts/latest/v1` do DEX Screener, filtrados pelas redes de `CHAINS`, até `MAX_TRACKED_TOKENS`. Viés: listas pagas/autodeclaradas (registrado em `tokens.discovered_via`).
2. **Watchlist** (`POST /tokens/track` ou `cli track`): confirma na fonte que o token existe como token-base antes de inserir.
3. **Refresh** (a cada 60 s): `tokens/v1/{chain}/{até 30 endereços}`; normaliza; ignora pares em que o token é *quote*; grava snapshot só se o hash do conteúdo mudou (a fonte usa cache de 60 s).
4. **Verificações técnicas** (a cada 30 s, 2 tokens por ciclo, recheck 1 h; 15 min após 429): `getAccountInfo` (autoridades, Token-2022) e `getTokenLargestAccounts`.
5. **Análise** (tokens com dados novos): features → risco → oportunidade → `analyses` (persistida se mudou ≥ 5 pontos, mudou de nível ou passaram 5 min) → alertas → previsões.
6. **Avaliação** (a cada 300 s): previsões com horizonte encerrado viram `evaluated` ou `unevaluable`.

## Identidade e tempo

- Token = `(chain_id, address)`; par = `(chain_id, pair_address)`. Ticker nunca é chave. Endereços EVM em minúsculas; Solana preserva maiúsculas (base58 é case-sensitive).
- Snapshots: `source_time` (a fonte não fornece por registro → `NULL`), `received_at`, `stored_at`. Análises: `computed_at`. Alertas: `event_at` (snapshot que originou), `detected_at`, `last_occurrence_at`.
- Todas as datas em UTC; API serializa ISO 8601 com `Z`.

## Persistência

Tabelas: `users`, `user_sessions`, `tokens`, `pairs`, `pair_snapshots`, `risk_checks`, `analyses`, `alerts`, `predictions`, `collector_runs`. Finalidade de cada uma documentada em `backend/app/models.py`.

- Migrações: Alembic (`backend/migrations/versions/0001_initial_schema.py`), testadas em todo teste (o conftest aplica `upgrade head`). Nenhuma migração destrutiva automática.
- Índices: `(pair_id, received_at)` para séries; `(token_id, computed_at)` para última análise; `(status, detected_at)` e `(dedup_key, status)` para alertas; `(status, resolve_at)` para avaliação.
- Retenção: payload bruto (`pair_snapshots.raw`) mantido 3 dias (D-013, disco gratuito pequeno); `python -m app.cli retention --apply` o apaga (dados normalizados ficam). Snapshots além de 90 dias são apenas reportados, nunca apagados automaticamente.
- Estimativa de volume: 150 tokens × 1 snapshot/min ≈ 216 mil linhas/dia no pior caso (na prática menos, pela deduplicação). SQLite atende desenvolvimento e também a produção gratuita (2 usuários, 1 worker); PostgreSQL é opcional via `DATABASE_URL`.

## Estratégia de fontes

| Fonte | Dados | Redes | Limites | Auth/custo | Lacunas | Falha |
|---|---|---|---|---|---|---|
| DEX Screener API (pública) | preço, liquidez (usd/base/quote), volume e transações (5m/1h/6h/24h), variação de preço, FDV/mcap, idade do par, links | multi-rede | 300 req/min (pares/tokens/busca), 60 req/min (profiles/boosts); `Cache-Control: max-age=60` | sem chave, gratuita | sem compradores/vendedores **únicos** (só contagem de transações); sem holders; sem timestamp por registro; sem OHLC histórico; `tokens/v1` devolve só parte dos pares | fonte `down` após 3 falhas seguidas → alerta de sistema + frescor `delayed/stale` |
| Solana JSON-RPC público | autoridades do mint, programa, extensões Token-2022, supply, 20 maiores contas | Solana | não documentado por método; **429 constante em `getTokenLargestAccounts`** (observado) | sem chave | sem proprietários das contas; sem histórico | verificação marcada `unavailable` e listada em `checks_not_performed` |

Verificado com requisições reais em 2026-10-28. Termos de uso do DEX Screener devem ser revisados pelo proprietário antes de uso comercial.

## Frescor

`fresh` ≤ 180 s; `delayed` ≤ 900 s; `stale` acima; `no_data` sem snapshot. Se a fonte estiver `down`, nada é reportado como `fresh`. Agregados do dashboard somam **apenas** dados `fresh`.

## Execução contínua e hospedagem (custo zero — D-013)

- Alvo: **uma VM do nível gratuito permanente** de um provedor de nuvem, com 3 coisas nela: `uvicorn app.main:app` (API + `frontend/dist` na mesma origem), `python -m app.worker` e o arquivo SQLite. Os processos são mantidos por `systemd` (reinício automático). HTTPS gratuito via proxy reverso (ex.: Caddy com Let's Encrypt) quando houver domínio; sem domínio, acesso só por IP e com `SESSION_COOKIE_SECURE=false`, **aceitável apenas com senhas fortes trocadas**.
- O worker é um processo de longa duração: **não roda em função serverless** nem em PaaS gratuito que hiberna.
- Provedor ainda não escolhido (T-020). As condições dos níveis gratuitos devem ser conferidas no momento da escolha.
- Um único worker por banco (não há lock distribuído). Reinício é seguro: o estado está no banco.
- O computador pessoal **não** precisa ficar ligado depois do deploy; até lá, a coleta só ocorre enquanto `python -m app.worker` estiver rodando localmente.

## Subsistemas dedicados (D-016)

Funções que precisam de ritmo próprio ganham um subsistema isolado: pacote, processo, trava, fonte e tabelas próprios, e um batimento em `service_heartbeats` que o `/health` lê.

| Subsistema | Processo | Função | Ritmo |
|---|---|---|---|
| Coletor geral | `python -m app.worker` | descoberta, 600 tokens, análise, sinais | 30 s (volta completa ~60 s) |
| Atualização rápida (`app/live`) | `python -m app.live` | preço do quadro "Quando vender" + golpe ao vivo | 10 s |

A API só lê o que os subsistemas gravam. Se um deles parar, a API volta ao dado do coletor e diz isso na resposta.

## Configuração

Variáveis em `backend/.env` (ignorado pelo Git); modelo em `backend/.env.example`. Nenhum segredo no código.
