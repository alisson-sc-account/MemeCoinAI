# Handoff

## Sessão 1b — 2026-10-28 — requisito de custo zero + commit inicial

- O proprietário exigiu **tudo de graça com a mesma qualidade** → D-013 em `DECISIONS.md`.
- A API agora serve `frontend/dist` na mesma origem (`app/main.py::_mount_frontend`, setting `FRONTEND_DIST_DIR`): uma única VM gratuita roda tudo. 2 testes novos; suíte com 49 passed.
- Retenção do payload bruto reduzida de 7 para 3 dias (disco gratuito pequeno).
- `CODEX_FRONTEND_TASK.md` ganhou a seção "custo zero" (somente open source, sem serviços externos, sem hospedagem separada, atribuição de licença do lightweight-charts, bundle leve); `FRONTEND_SPEC.md` §24 atualizado.
- TASKS: T-012 (PostgreSQL) rebaixada para P3; T-014 validada no backend; T-015/T-020 aguardam contas **gratuitas** criadas pelo proprietário; nova T-024 (script de deploy).
- Commit inicial e push autorizados pelo proprietário nesta sessão.

## Sessão 1 — 2026-10-28 — Claude Code (Opus 5.5)

### O que foi feito
- Pasta vazia → `git init -b main` + `origin` = `https://github.com/alisson-sc-account/MemeCoinAI.git` (o remoto está vazio: `git ls-remote` não retornou refs). **Nenhum commit/push feito** (aguarda autorização).
- Fontes verificadas com requisições reais: DEX Screener (search, tokens/v1, token-pairs, profiles, boosts) e RPC Solana (`getAccountInfo` OK; `getTokenLargestAccounts` = 429).
- Backend completo do MVP em `backend/` (ver `ARCHITECTURE.md`): config, banco + migração, autenticação, adaptadores com retry/backoff/limite, normalização, coleta, verificações Solana, features sem vazamento, risco/oportunidade explicáveis, slippage x*y=k, alertas com deduplicação, previsões + avaliação + métricas, worker, CLI, API `/api/v1`.
- 47 testes automatizados (todos passando) + execução real (40 tokens Solana, análises e alertas reais).
- Pacote do Codex: `FRONTEND_SPEC.md`, `DESIGN_SYSTEM.md`, `API_CONTRACT.md`, `CODEX_FRONTEND_TASK.md`, `docs/openapi.json`, `docs/api-examples/` (respostas reais capturadas), `CONTRACT_ISSUES.md`.
- Continuidade: README, PROJECT_STATE, TASKS, DECISIONS, TEST_STATUS, ANALYSIS_ENGINE, PROMPT_DE_CONTINUACAO.

### Decisões importantes
D-001 a D-012 em `DECISIONS.md` (Python/FastAPI; SQLite dev/PostgreSQL prod; Solana + DEX Screener; cookie httpOnly; seed de usuários sem senha no Git; scores por pontos; previsão não calibrada + baseline; slippage só x*y=k; deduplicação; frontend React/Vite; hospedagem pendente).

### Ajustes feitos após observar dados reais
- O alerta `insufficient_data` disparava para todo token novo (36 alertas): agora só após 1 h de monitoramento.
- O alerta `risk_high` passou a informar quantos pontos vêm de verificações não realizadas.

### Testes
- `pytest`: 47 passed. Falhas: nenhuma.
- Não executados: PostgreSQL, worker prolongado, frontend.

### Bloqueios
- Concentração de holders: RPC público com 429 → precisa de RPC dedicado (decisão do proprietário, possível conta externa/custo).
- Hospedagem: decisão do proprietário (custo).

### Próximas tarefas recomendadas (ordem)
1. Proprietário: autorizar o commit inicial e o push; autorizar o início do Codex.
2. Rodar `python -m app.worker` por ≥ 6 h para acumular histórico e avaliar as primeiras previsões (T-011).
3. Decidir RPC dedicado (T-015) e hospedagem (T-020).
4. Após o frontend: integração e revisão (T-013, T-014).

### Comandos para retomar
```powershell
cd "C:\Users\aliss\Downloads\Meme Coins - Projeto pessoal"
git status
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m app.worker      # coleta contínua
```

### Estado do Git
Branch `main`, sem commits; todos os arquivos não rastreados. Ignorados: `backend/.env`, `backend/.venv/`, `backend/data/` (SQLite local com dados reais), caches.

### Riscos de regressão
- Mudar `schemas.py` altera o contrato → regenerar `docs/openapi.json` (`python -m app.cli openapi`) e atualizar `API_CONTRACT.md` + avisar o Codex.
- Mudar regras/pesos → nova versão (`risk-2` etc.) + `ANALYSIS_ENGINE.md` + `DECISIONS.md`.
- Migração 0001 editada manualmente (FK circular `tokens.primary_pair_id` criada depois de `pairs`); validar em PostgreSQL antes do deploy.
