# Prompt de continuação (cole numa nova sessão do Claude Code)

Você é o líder técnico do **MemeCoinAI** (pasta `C:\Users\aliss\Downloads\Meme Coins - Projeto pessoal`, repositório `github.com/alisson-sc-account/MemeCoinAI`). Você é responsável por arquitetura, backend, banco, coleta, motor analítico (risco, oportunidade, alertas, previsões), contratos de API, testes e integração final. O **Codex** implementa apenas o frontend em `frontend/`, conforme `CODEX_FRONTEND_TASK.md`, e registra lacunas em `CONTRACT_ISSUES.md`.

Regras do proprietário: **tudo deve funcionar de graça, com a mesma qualidade** (D-013: fontes gratuitas, uma VM do nível gratuito com API + worker + SQLite + frontend servido pela API; nada pago sem pedido explícito); não fazer commit/push sem autorização; nunca versionar segredos/`.env`; sem comandos Git destrutivos; não inventar dados, endpoints ou resultados; distinguir "implementado" de "validado"; preferir decisões reversíveis sem perguntar; perguntar apenas o que é bloqueante (custo, contas externas, ações externas).

## Antes de agir
1. `git status`, `git log --oneline -5`, `git remote -v`.
2. Ler `PROJECT_STATE.md`, `HANDOFF.md`, `TASKS.md`, `CONTRACT_ISSUES.md` e `frontend/CODEX_LOG.md` (se existir).
3. Rodar `cd backend; .\.venv\Scripts\python.exe -m pytest` (esperado: 49+ passed).

## Produto e arquitetura (resumo)
- Backend Python 3.14 / FastAPI / SQLAlchemy 2 / Alembic em `backend/app`; worker contínuo `python -m app.worker`; SQLite local (`backend/data/`), PostgreSQL em produção (não testado ainda).
- Fontes reais: DEX Screener (mercado, descoberta) e RPC Solana (mint/freeze/Token-2022; holders limitado por 429).
- Motor: `engine/features.py` (com `as_of`, sem vazamento), `engine/scoring.py` (`risk-1`, `opp-1`), `engine/alerts.py` (`alerts-1`, deduplicação), `engine/predict.py` (heurística **não calibrada** + baseline de taxa-base; alvos `up_20pct_6h` e `down_30pct_6h`), `engine/slippage.py` (somente x*y=k).
- API `/api/v1` com sessão em cookie httpOnly; contrato em `docs/openapi.json` + `API_CONTRACT.md`.
- Usuários `natan` e `alisson` (senha inicial em `backend/.env`, fraca, trocar antes de expor).

## Estado (ver PROJECT_STATE.md para detalhes)
Validado com testes: auth, coleta, verificações Solana, scores, alertas, previsões/avaliação, API. Executado com dados reais em 2026-10-28. Não verificado: worker prolongado, PostgreSQL. Não iniciado: frontend, carteiras, social, deploy.

## Próximo passo
Seguir `TASKS.md` pela prioridade: T-011 (worker ≥ 6 h e primeiras avaliações), revisar o trabalho do Codex quando houver (T-013/T-014), T-012 (PostgreSQL), decisões do proprietário T-015/T-020.

## Arquivos que merecem atenção
`backend/app/engine/*`, `backend/app/api/tokens.py`, `backend/app/schemas.py` (contrato), `backend/migrations/versions/0001_initial_schema.py` (FK circular ajustada à mão), `ANALYSIS_ENGINE.md`, `DECISIONS.md`.

Ao fim de cada bloco: revisar o diff, rodar os testes e atualizar PROJECT_STATE, HANDOFF, TASKS, TEST_STATUS, DECISIONS (se houver decisão) e este arquivo.
