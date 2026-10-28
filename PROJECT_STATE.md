# Estado do projeto

Atualizado: 2026-10-28 (sessão 1, Claude Code / Opus 5.5).

## Missão

Sistema web de inteligência para memecoins baseado em dados reais verificáveis, com risco e oportunidade explicáveis, alertas, previsões avaliadas fora da amostra e transparência sobre limitações. Ver README.

## Estado geral

| Área | Estado |
|---|---|
| Requisito de custo | **custo zero** sem perda de qualidade (D-013): fontes gratuitas, uma VM gratuita, SQLite, frontend servido pela API |
| Repositório Git | `main`, `origin` = github.com/alisson-sc-account/MemeCoinAI; commit inicial autorizado pelo proprietário |
| Frontend servido pela API (mesma origem) | **validado com testes** (`tests/test_frontend_serving.py`) |
| Backend (API FastAPI) | **validado com testes** + exercitado via HTTP com dados reais |
| Autenticação (2 usuários, Argon2id, sessão em cookie) | **validado com testes** |
| Persistência (SQLite, migração Alembic 0001) | **validado com testes** (SQLite, também alvo de produção). PostgreSQL opcional, **não verificado** |
| Coleta DEX Screener (descoberta, watchlist, refresh, dedup) | **validado com testes** + **execução real** (40 tokens, 36 snapshots) |
| Verificações Solana (mint/freeze/Token-2022) | **validado com testes** + **execução real** (3 tokens, status `ok`) |
| Concentração de holders (Solana) | **implementado; bloqueado na prática**: RPC público devolve 429 sempre |
| Motor de risco/oportunidade (`risk-1`, `opp-1`) | **validado com testes**; pesos **não validados historicamente** |
| Alertas + deduplicação (`alerts-1`) | **validado com testes** + gerados com dados reais |
| Slippage (x*y=k) | **validado com testes** (fórmula); não comparado com execuções reais |
| Previsões + avaliação + métricas | **validado com testes**; modelo **não calibrado**; nenhuma previsão real avaliada ainda (horizonte 6 h) |
| Worker contínuo | **implementado, não verificado em execução prolongada** (jobs testados individualmente via CLI) |
| Frontend | **não iniciado** — especificação pronta para o Codex |
| Inteligência de carteiras | não iniciado |
| Dados sociais | apenas links declarados pela fonte |
| Deploy/hospedagem | não iniciado; alvo: VM do nível gratuito (falta o proprietário criar a conta) |

## Arquitetura real

Ver `ARCHITECTURE.md`. Resumo: `backend/app` (FastAPI + SQLAlchemy 2 + Alembic), worker separado (`python -m app.worker`), banco único. Contrato: `docs/openapi.json` + `API_CONTRACT.md`.

## Stack confirmada (instalada)

Python 3.14.7 · FastAPI 0.162.0 · Starlette 1.10.0 · SQLAlchemy 2.1.6 · Alembic 1.20.1 · Pydantic 2.14.1 · pydantic-settings 2.16.2 · httpx 0.28.1 · argon2-cffi 25.1.0 · uvicorn 0.54.0 · pytest 9.2.0 · Node 24.19.0 (para o frontend) · Git 2.47.1. Sem Docker e sem PostgreSQL locais.

## Integrações

| Integração | Tipo |
|---|---|
| DEX Screener API pública | **real**, testada em 2026-10-28 |
| Solana RPC público `getAccountInfo` | **real**, funciona |
| Solana RPC público `getTokenLargestAccounts` | **real, mas limitado** (429) |
| Simulações | somente nos testes (`tests/conftest.py::FakeDex`), identificadas como tal |

## Limitações conhecidas

- DEX Screener: sem compradores/vendedores únicos, sem holders, sem timestamp por registro, cache de 60 s, descoberta enviesada (perfis/boosts).
- Histórico de preço = snapshots próprios (~1/min enquanto o worker roda), não candles.
- Slippage indisponível para CLMM/DLMM/Whirlpool (maioria dos pools grandes de Solana) e sem taxas.
- Verificações técnicas só para Solana.
- Limite de tentativas de login em memória (não compartilhado entre processos).
- Previsões: coeficientes a priori; métricas sem amostra suficiente.

## Comandos principais

Ver README (instalação, `migrate`, `seed-users`, API, worker, testes).

## Próximos passos

Ver `TASKS.md` (prioridades P0–P3) e `HANDOFF.md`.
