# Prompt para o Codex — MemeCoinAI (copie tudo abaixo)

Você vai fazer **três tarefas pequenas** no repositório local do MemeCoinAI em `C:\Users\aliss\Downloads\Meme Coins - Projeto pessoal`. Faça a menor alteração possível em cada uma e reporte ao final.

## Contexto

O MemeCoinAI é uma aplicação **local** de monitoramento e classificação de memecoins da rede Solana. Um worker Python coleta dados públicos gratuitos (DEX Screener e RPC público Solana), grava tudo em SQLite, calcula scores explicáveis e alimenta uma interface React. É apoio à análise: **não executa ordens, não guarda chave privada e não promete lucro**.

Restrição absoluta: **custo zero e execução local**. Nenhuma API paga, chave obrigatória, nuvem, assinatura ou serviço que possa cobrar. A API escuta só em `127.0.0.1`.

## Estado verificado (2026-10-29)

- Backend: Python 3.14, FastAPI, SQLAlchemy 2, Alembic (migrações `0001`–`0003`), SQLite em `backend/data/memecoinai.db`. Código em `backend/app/`. Ambiente em `backend/.venv`.
- Worker: `python -m app.worker`, instância única por trava de arquivo (`backend/app/worker_lock.py`, `backend/data/worker.lock`).
- Frontend: React 18 + TypeScript + Vite 5 + TanStack Query 5 em `frontend/`. Navegação com **exatamente quatro abas** definida em `frontend/src/App.tsx` (constante `routes` e função `isTabActive`): Dashboard (`/`), Compre agora (`/compre-agora`), Alertas (`/alerts`) e Configurações (`/settings`). `/tokens`, `/tokens/:chainId/:address`, `/predictions` e `/system` são páginas internas, sem aba. `/account` redireciona para `/settings`.
- "Compre agora": `frontend/src/features/buynow.tsx` (`BuyNowPage`, `OpportunityCard`, `WorkerStatusCard`, `SourcesRegistry`), consumindo `GET /api/v1/opportunities` (`backend/app/api/opportunities.py`, regras em `backend/app/engine/ranking.py`).
- Estado do worker: `GET /api/v1/health` → campo `worker`, calculado em `backend/app/api/system.py::worker_status` a partir de `CollectorRun` (`backend/app/models.py`); schema `WorkerStatusOut` em `backend/app/schemas.py`.
- Testes atuais: backend **98 passed**; frontend **24 passed**; typecheck, lint e build OK. E2E (Playwright) **nunca executado** (Chromium não instalado).

Comandos reais (PowerShell, a partir da raiz):

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest
cd ..\frontend; npm test; npm run typecheck; npm run lint; npm run build
.\start.bat   # sobe API + interface em http://127.0.0.1:8000 e o worker
.\stop.bat    # encerra API e worker desta pasta
```

Glossário mínimo: **tier/nível** = `priority_buy` (Compra prioritária), `possible_buy` (Compra possível), `watch` (Observar), `avoid` (Evitar). **decision_quality** = `ok`, `partial` (falta dado secundário) ou `no_reliable_signal` (falta preço/liquidez ou cotação velha; exceção, nunca padrão). **Score, confiança e cobertura** são campos separados e não podem ser fundidos.

## Regras que não podem ser quebradas

- Não adicionar dependência, serviço ou API paga; não exigir chave.
- Não apagar, recriar nem "limpar" o banco; nada de migração destrutiva.
- Não expor a API fora de `127.0.0.1`. Não implementar ordens nem guardar chaves privadas.
- Não inventar dados, nem mostrar fixture como dado real.
- Não quebrar as quatro abas nem transformar dado secundário ausente em bloqueio global.
- **Antes de editar, abra o arquivo atual.** Preserve alterações locais não relacionadas (há arquivos não commitados). Sem renomeações em massa, sem reescrever arquivos inteiros.
- Não faça commit nem push.
- Se perceber risco de perda de dados, cobrança ou falta de informação crítica, pare e reporte.

---

## TAREFA 1 — Atualizar e executar o teste E2E para as quatro abas

**Contexto verificado:** `frontend/e2e/smoke.spec.ts` existe, faz login (`E2E_USERNAME`/`E2E_PASSWORD`), navega por `/tokens` e pelo sino de alertas, e mede rolagem horizontal em 390×844 e 1366×768. `frontend/playwright.config.ts` usa `baseURL: http://127.0.0.1:8000`. Nunca foi executado.

**Resultado esperado:** o teste cobre também a navegação principal e "Compre agora", e é executado de fato contra o app local.

**Escopo permitido:** só `frontend/e2e/smoke.spec.ts`.

**Implementação mínima:**
1. Depois do login, verificar que o primeiro `nav` com `aria-label="Navegação principal"` tem exatamente os links (atributo `aria-label`) `Dashboard`, `Compre agora`, `Alertas`, `Configurações`.
2. Ir para `/compre-agora`, esperar ao menos um card (`main a[aria-label]` com `href` começando em `/tokens/`), clicar e verificar que a URL vira `/tokens/solana/...`.
3. Manter as verificações existentes de rolagem horizontal.
4. Instalar o navegador (download gratuito, sem conta): `cd frontend; npx playwright install chromium`.
5. Com `.\start.bat` rodando, executar `$env:E2E_USERNAME='alisson'; $env:E2E_PASSWORD='<senha do backend/.env>'; npm run test:e2e`. **Não grave a senha em nenhum arquivo.**

**Critérios de aceitação:** `npm run test:e2e` passa (ou só pula com o motivo `test.skip` já existente, quando não houver alerta ligado a token); `npm test`, `npm run typecheck` e `npm run lint` continuam passando.

**Relatório:** arquivo alterado, saída do `npm run test:e2e` e eventuais skips com o motivo.

---

## TAREFA 2 — Mostrar a duração do ciclo de coleta e avisar quando passa do intervalo

**Contexto verificado:** com 600 tokens, o ciclo de mercado leva cerca de 60 s, mais que `REFRESH_INTERVAL_SECONDS` (30). `worker_status` em `backend/app/api/system.py` usa só `finished_at` da última `CollectorRun` com `source == "dexscreener"` e `job == "refresh"`. `CollectorRun` tem `started_at` e `finished_at`.

**Resultado esperado:** `/api/v1/health` informa `last_cycle_duration_seconds`, e o card de estado do sistema avisa quando a coleta está mais lenta que o intervalo configurado.

**Escopo permitido:** `backend/app/api/system.py` (`worker_status`), `backend/app/schemas.py` (`WorkerStatusOut`), `backend/tests/test_ranking_registry.py` (`test_health_reports_worker_state`), `frontend/src/features/buynow.tsx` (`WorkerStatusCard`). Depois: `python -m app.cli openapi` (em `backend`) e `npm run gen:api` (em `frontend`) para regenerar os tipos.

**Implementação mínima:**
1. Em `worker_status`, buscar `started_at` e `finished_at` da mesma última execução e devolver `last_cycle_duration_seconds` (arredondado em 0,1; `None` sem execução).
2. Adicionar o campo opcional em `WorkerStatusOut` (`float | None = None`).
3. Em `WorkerStatusCard`, quando a duração passar de `expected_interval_seconds`, mostrar: "Coleta levando X s (intervalo configurado: Y s). Reduza MAX_TRACKED_TOKENS no backend/.env se quiser ciclos mais curtos."
4. Estender o teste existente para checar o campo com uma `CollectorRun` de 45 s de duração.

**Critérios de aceitação:** `pytest` e `npm test` passam; o aviso aparece só quando a duração é maior que o intervalo; nenhuma mudança na lógica de coleta.

**Relatório:** arquivos alterados, comandos e resultados.

---

## TAREFA 3 — Alinhar a especificação de frontend às quatro abas

**Contexto verificado:** `FRONTEND_SPEC.md` §2 ("Rotas e páginas") ainda lista `/` como "Visão geral" e `/account` como página de conta. A navegação real é a descrita acima. `CODEX_FRONTEND_TASK.md` não menciona "Compre agora".

**Resultado esperado:** documentação coerente com o código.

**Escopo permitido:** só `FRONTEND_SPEC.md` (§2 e §3) e `CODEX_FRONTEND_TASK.md` (seção de páginas). Não altere código.

**Implementação mínima:** atualizar a tabela de rotas com `/` Dashboard, `/compre-agora` Compre agora (`GET /opportunities`), `/alerts` Alertas e `/settings` Configurações (saldo, som, fontes e custo, senha); marcar `/tokens`, `/predictions` e `/system` como páginas internas sem aba e `/account` como redirecionamento; escrever explicitamente a regra "exatamente quatro abas principais".

**Critérios de aceitação:** todas as rotas citadas existem em `frontend/src/App.tsx` (confira o `<Routes>` em `App`); nada além desses dois arquivos muda.

**Relatório:** trechos alterados.

---

## Relatório final esperado

Para cada tarefa: arquivos alterados, o que mudou, comandos executados com o resultado (número de testes), o que ficou pendente e qualquer divergência encontrada entre este prompt e o código real.
