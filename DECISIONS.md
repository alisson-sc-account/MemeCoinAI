# Decisões técnicas

Formato: problema · decisão · alternativas · justificativa · consequências · revisar quando.

## D-001 Stack do backend: Python 3.14 + FastAPI + SQLAlchemy 2 + Alembic
- **Problema:** repositório vazio; precisa de API, ingestão, estatística e futuramente ML.
- **Decisão:** Python (instalado: 3.14.7), FastAPI, SQLAlchemy 2, Alembic, httpx, argon2-cffi.
- **Alternativas:** Node/NestJS (ecossistema estatístico fraco); Django (mais pesado, ORM menos flexível para séries).
- **Justificativa:** um só idioma para API e motor analítico; OpenAPI automático serve de contrato para o Codex.
- **Consequências:** tipos do frontend gerados do OpenAPI.
- **Revisar:** se a carga exigir processamento que Python não sustente (improvável no MVP).

## D-002 Banco: SQLite em desenvolvimento, PostgreSQL em produção
- **Problema:** PostgreSQL e Docker não estão instalados na máquina local.
- **Decisão:** `DATABASE_URL` configurável; SQLite (WAL) por padrão local; código e migrações portáveis (testado só em SQLite até agora).
- **Alternativas:** exigir instalação de PostgreSQL agora (bloquearia o progresso).
- **Consequências:** com D-013, SQLite também é o banco de produção; PostgreSQL fica opcional (T-012, P3).
- **Revisar:** se houver mais de um worker/instância da API.

## D-003 Rede inicial: Solana; fonte principal: DEX Screener
- **Problema:** escolher uma fonte acessível para um fluxo vertical completo.
- **Decisão:** DEX Screener (gratuito, sem chave, multi-rede) para mercado; RPC Solana para verificações técnicas. `CHAINS=solana`.
- **Justificativa:** a maior parte das memecoins novas está em Solana; o RPC permite checar autoridades de mint/freeze de forma verificável.
- **Consequências:** sem compradores únicos, holders reais nem histórico OHLC; outras redes ficam com verificação técnica `not performed`.
- **Revisar:** ao adicionar EVM (precisa de método próprio, sem reaproveitar regras Solana).

## D-004 Sessão em cookie httpOnly em vez de JWT no JavaScript
- **Decisão:** token opaco aleatório (32 bytes), só o SHA-256 no banco; cookie `httpOnly`, `SameSite=Lax`, `Secure` configurável; expiração 72 h; revogação no logout e na troca de senha; limite de 5 falhas de login por usuário+IP a cada 15 min (em memória).
- **Justificativa:** o token nunca fica acessível ao JS; revogação imediata.
- **Consequências:** frontend e API devem estar na mesma origem (proxy do Vite em dev; mesmo domínio em prod). O limite de login em memória zera ao reiniciar e não é compartilhado entre processos.
- **Revisar:** se houver múltiplas instâncias da API.

## D-005 Usuários iniciais via `seed-users`, senha fora do Git
- **Decisão:** `SEED_USERNAMES=natan,alisson` e `SEED_INITIAL_PASSWORD` em `backend/.env` (local: o valor pedido pelo proprietário). `must_change_password=true`; endpoint de troca de senha implementado.
- **Consequências:** a senha inicial é fraca: **trocar antes de qualquer exposição pública**.

## D-006 Pontuação explicável por pontos, não por modelo opaco
- **Decisão:** risco = soma de pontos de fatores identificáveis (máx. 100) + cobertura das verificações; oportunidade = soma de fatores positivos − penalidade de risco, com tetos para pool raso e dados insuficientes.
- **Justificativa:** auditável, versionável (`risk-1`, `opp-1`) e testável. Pesos são escolhas a priori.
- **Consequências:** **ainda não validados historicamente**; ajustar só com dados de avaliação (sem usar o conjunto de teste final).

## D-007 Previsão: heurística não calibrada + baseline de taxa-base, ambas registradas
- **Decisão:** dois alvos (`up_20pct_6h`, `down_30pct_6h`); probabilidade por sigmóide de coeficientes a priori, marcada `calibrated=false`; baseline = taxa-base Laplace usando somente previsões avaliadas antes do instante (sem vazamento); no máximo 1 previsão por alvo/token a cada 3 h.
- **Alternativas:** treinar LightGBM/regressão logística já (não há histórico para isso).
- **Revisar:** com ≥ 100 previsões avaliadas por alvo: comparar o Brier com a baseline; calibrar (Platt/isotônica) com divisão temporal.

## D-008 Slippage só para pools de produto constante
- **Decisão:** o mapeamento `dexId`/`labels` vem de pares reais observados: `CPMM`, `v2`, `pumpswap` e `raydium` sem rótulo → x*y=k. CLMM/DLMM/Whirlpool (`wp`)/`v3`/`v4` → `concentrated`; `DYN`/`DYN2` → `unsupported`; `pumpfun` → `bonding_curve`. Fora de x*y=k não há estimativa.
- **Consequências:** muitos pools Solana (CLMM/DLMM) ficam sem estimativa; taxas do pool não são incluídas.
- **Revisar:** ao integrar uma fonte de cotação real (ex.: agregador de swap) ou leitura de ticks.

## D-009 Deduplicação de alertas
- **Decisão:** chave `tipo:token`. Mesma severidade ou menor → incrementa `occurrences`. Severidade maior → novo alerta. Alertas de condição contínua são auto-resolvidos quando a condição some; eventos (`liquidity_drop`, `permission_change`) ficam até ação do usuário. `insufficient_data` só dispara após 1 h de monitoramento.

## D-010 Persistência de análises com limitação de frequência
- **Decisão:** só grava nova análise se o risco ou a oportunidade mudar ≥ 5 pontos, se o nível de risco mudar ou se passarem 5 min.
- **Justificativa:** evita cerca de 200 mil linhas/dia de JSON redundante.
- **Consequências:** entre análises gravadas, os alertas não são reavaliados.

## D-011 Frontend: React + TypeScript + Vite (implementação pelo Codex)
- **Decisão:** React 18, Vite 5, TypeScript estrito, React Router 6, TanStack Query 5, lightweight-charts 4, CSS Modules + tokens CSS, Vitest + Testing Library, Playwright para smoke e2e; tipos gerados com `openapi-typescript` a partir de `docs/openapi.json`.
- **Justificativa:** stack bem suportada, sem servidor Node em produção (build estático servido junto da API).

## D-012 Hospedagem: um único servidor gratuito (substituída em parte por D-013)
- Exige processo contínuo + banco persistente. Com D-013, o alvo é **uma VM gratuita** rodando API + worker + SQLite + frontend estático. Provedor ainda não escolhido (T-020).

## D-013 Custo zero como requisito, sem perda de qualidade (proprietário, 2026-10-28)
- **Problema:** o proprietário exige que todo o sistema funcione de graça, com a mesma qualidade.
- **Decisão:**
  1. **Dados:** só fontes gratuitas (DEX Screener público; RPC Solana público ou plano gratuito de provedor via `SOLANA_RPC_URL`). Nenhuma API paga, nenhuma IA generativa paga.
  2. **Implantação:** uma única VM do nível gratuito permanente de um provedor de nuvem, rodando API + worker + SQLite (WAL) + `frontend/dist` servido pela própria API (implementado e testado em `app/main.py::_mount_frontend`). Sem banco gerenciado, sem hospedagem separada de frontend, sem serverless.
  3. **SQLite também em produção** enquanto houver 2 usuários e 1 worker; PostgreSQL vira opcional (suportado via `DATABASE_URL`).
  4. **Armazenamento enxuto:** payload bruto retido 3 dias (era 7); dados normalizados preservados.
  5. **Frontend:** somente dependências open source, sem serviços externos em runtime (ver `CODEX_FRONTEND_TASK.md`).
- **Alternativas rejeitadas:** PaaS gratuitos que hibernam o serviço ou expiram o banco (interrompem a coleta contínua); funções serverless (não mantêm o worker); bancos gerenciados gratuitos com pausa por inatividade.
- **Qualidade preservada:** motor, regras, testes, contratos e verificações não mudam. Limites reais do gratuito, documentados e visíveis na UI:
  - concentração de holders depende de um RPC sem 429 → plano gratuito de provedor RPC, com chave criada pelo proprietário (custo zero, mas exige conta);
  - VM gratuita sem SLA → a coleta pode parar; o sistema já marca os dados como `delayed`/`stale` e abre alerta de fonte;
  - recursos pequenos (~1 GB RAM) → limite `MAX_TRACKED_TOKENS` (padrão 150) e intervalos atuais.
- **Consequências:** o proprietário precisa criar a conta do provedor de nuvem (nível gratuito; alguns exigem cartão apenas para verificação) e, se quiser holders, a do provedor RPC. As condições de cada nível gratuito devem ser conferidas no momento da escolha; aqui não se afirma nenhuma condição que não foi verificada.
- **Revisar:** se o número de usuários/tokens crescer além do que uma VM pequena com SQLite sustenta, ou se as condições gratuitas mudarem.
