# MemeCoinAI

Sistema web privado de inteligência para memecoins: coleta dados reais de mercado (DEX Screener) e verificações on-chain (RPC Solana), calcula scores explicáveis de risco e oportunidade, gera alertas deduplicados e previsões probabilísticas avaliadas depois do horizonte.

**Não é recomendação de investimento. Não executa ordens. Scores não são probabilidade de lucro.**

Estado atual e próximos passos: [`PROJECT_STATE.md`](PROJECT_STATE.md). Arquitetura: [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Interface

Quatro abas: **Dashboard** (estado do sistema, sinais, riscos), **Compre agora** (ranking em níveis: Compra prioritária, Compra possível, Observar, Evitar), **Alertas** e **Configurações** (saldo para simulação, som, fontes e custo, senha). Clicar num token abre o detalhe com gráfico, sinal, posição e evidências.

Guia completo para Windows: [`docs/QUICKSTART_WINDOWS.md`](docs/QUICKSTART_WINDOWS.md) · Fontes e custo: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) · Configuração: [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) · Segurança: [`docs/SECURITY_AND_COST.md`](docs/SECURITY_AND_COST.md) · Fluxograma → código: [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md).

**Atalho:** `start.bat` inicia tudo; `stop.bat` encerra.

## Rodar localmente (Windows / PowerShell)

Pré-requisitos: Python ≥ 3.11 (testado em 3.14.7), Node ≥ 20 (testado em 24), Git.

### Jeito rápido (um comando)

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

O script cria o ambiente Python, aplica as migrações, cria os usuários, instala e gera o build da interface quando necessário, abre o **coletor** numa janela própria e sobe a **API + interface** em http://127.0.0.1:8000. Use `-NoStart` para só preparar e verificar, e `-Port 8010` se a 8000 estiver ocupada. Na primeira vez, ele cria `backend/.env` e pede que você defina `SEED_INITIAL_PASSWORD`.

Para desenvolver a interface com recarregamento automático: rode a API (abaixo) e, em `frontend/`, `npm run dev` → http://localhost:5173.

### Passo a passo (manual)

PostgreSQL é opcional (SQLite por padrão).

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

Atualização rápida (terminal 3) — preço a cada 10 s no quadro "Quando vender" (D-016); sem ela o quadro usa o preço do coletor (~30–60 s) e mostra "AO VIVO DESLIGADO":

```powershell
cd backend; .\.venv\Scripts\python.exe -m app.live
```

O `start.bat` abre os três de uma vez; o `stop.bat` fecha os três.

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
