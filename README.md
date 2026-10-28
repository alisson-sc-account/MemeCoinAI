# MemeCoinAI

Sistema web privado de inteligência para memecoins: coleta dados reais de mercado (DEX Screener) e verificações on-chain (RPC Solana), calcula scores explicáveis de risco e oportunidade, gera alertas deduplicados e previsões probabilísticas avaliadas depois do horizonte.

**Não é recomendação de investimento. Não executa ordens. Scores não são probabilidade de lucro.**

Estado atual e próximos passos: [`PROJECT_STATE.md`](PROJECT_STATE.md). Arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Rodar localmente (Windows / PowerShell)

Pré-requisitos: Python ≥ 3.11 (testado em 3.14.7), Git. PostgreSQL é opcional em desenvolvimento (SQLite por padrão).

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env        # edite SEED_INITIAL_PASSWORD (nunca versione o .env)
.\.venv\Scripts\python.exe -m app.cli migrate
.\.venv\Scripts\python.exe -m app.cli seed-users
```

API (terminal 1):

```powershell
cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Coletor contínuo (terminal 2) — sem ele os dados ficam `delayed`/`stale`:

```powershell
cd backend; .\.venv\Scripts\python.exe -m app.worker
```

Documentação interativa: http://127.0.0.1:8000/api/v1/docs

Quando existir `frontend/dist` (gerado por `npm run build`), a mesma API serve a interface em http://127.0.0.1:8000/. Tudo roda num único servidor: o projeto é desenhado para **custo zero** (ver `DECISIONS.md` D-013).

Comandos úteis (`python -m app.cli <cmd>`): `track <chain> <endereço>`, `discover`, `refresh`, `checks [N]`, `evaluate`, `retention [--apply]`, `openapi`.

## Testes

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest
```

## Segurança

- As senhas iniciais de `natan` e `alisson` são fracas e servem **somente para desenvolvimento local**. Troque-as (`/api/v1/auth/change-password`) antes de qualquer exposição pública e use `SESSION_COOKIE_SECURE=true` com HTTPS.
- Nenhum segredo é versionado; `.env` está no `.gitignore`.

## Divisão de trabalho

Backend, motor e contratos: Claude Code. Frontend: Codex, conforme [`CODEX_FRONTEND_TASK.md`](CODEX_FRONTEND_TASK.md), somente após autorização do proprietário.
