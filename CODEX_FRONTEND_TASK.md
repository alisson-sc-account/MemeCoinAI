# Tarefa do Codex — Frontend do MemeCoinAI

> Só comece a implementar após **autorização explícita do usuário** nesta sessão.

## Papel

Você implementa **somente o frontend** (`frontend/`) do MemeCoinAI, um painel web privado de inteligência de memecoins. O Claude Code é o líder técnico e responsável por arquitetura, backend, banco, motor analítico, contratos de API e integração final. Você **não** toma decisões arquiteturais nem altera o contrato.

## Requisito do proprietário: custo zero, mesma qualidade

O projeto inteiro deve operar **sem nenhum custo** (decisão D-013). Isso **não** reduz a exigência de qualidade: todos os critérios de `FRONTEND_SPEC.md` continuam valendo. Regras para o frontend:

- **Somente dependências gratuitas e de código aberto** com licença permissiva (MIT, Apache-2.0, BSD, ISC, OFL para fontes). Proibido: bibliotecas pagas ou "pro" (AG Grid Enterprise, Highcharts, amCharts comercial, kits de UI pagos), fontes pagas, ícones pagos e trials.
- **Nenhum serviço externo** em runtime: sem CDN, Google Fonts remoto, analytics, Sentry/LogRocket, mapas, feature flags ou APIs de terceiros. Tudo é empacotado no build (`@fontsource/*` auto-hospedado).
- **Sem hospedagem separada para o frontend** (nada de Vercel, Netlify ou Cloudflare Pages). O `npm run build` gera `frontend/dist/`, que **a própria API FastAPI serve** na mesma origem (já implementado e testado: `/` e as rotas do cliente devolvem `index.html`, `/assets/*` devolve os arquivos, `/api/*` continua sendo a API). Use `base: "/"` no Vite e nomes de arquivo com hash (padrão do Vite).
- **Leve:** o servidor gratuito alvo é pequeno (cerca de 1 GB de RAM, CPU compartilhada). Respeite o orçamento do bundle (§22 da spec: ≤ 250 KB gzip iniciais), use code splitting e não faça polling mais agressivo que o especificado, para não pressionar a API nem os limites gratuitos das fontes de dados.
- **Licenças com atribuição:** `lightweight-charts` (Apache-2.0) exige atribuição ao TradingView. Mantenha o aviso e o link exigidos pela licença (por exemplo, no rodapé do gráfico ou numa seção "Sobre/Licenças" em `/system`). Registre em `frontend/CODEX_LOG.md` a licença de cada dependência adicionada (`npx license-checker --summary` ou equivalente gratuito).
- Ferramentas de teste também gratuitas e locais: Vitest, Testing Library, Playwright com navegadores baixados localmente. Nada de serviços de teste na nuvem pagos.

Se algum requisito da spec parecer exigir algo pago, **não contrate nem adicione**: registre em `CONTRACT_ISSUES.md` e siga com a alternativa gratuita mais próxima.

## Leitura obrigatória (nesta ordem)

1. `PROJECT_STATE.md` — o que existe e o que funciona.
2. `HANDOFF.md` — último estado e avisos.
3. `API_CONTRACT.md` + `docs/openapi.json` + `docs/api-examples/*.json`.
4. `FRONTEND_SPEC.md` — páginas, comportamento, critérios de aceitação.
5. `DESIGN_SYSTEM.md` — visual.
6. `ARCHITECTURE.md` e `DECISIONS.md` (D-004 sessão/cookie, D-011 stack do frontend).

Depois confira o repositório real: `git status`, `git log --oneline -5`, e se `frontend/` já existe. A documentação não substitui a verificação do código.

## O que você PODE modificar

- Tudo dentro de `frontend/`.
- `frontend/CODEX_LOG.md` (seu registro de progresso; crie se não existir).
- `CONTRACT_ISSUES.md` na raiz (apenas acrescentar entradas).

## O que você NÃO PODE modificar

- `backend/**` (código, migrações, testes, `.env`), `docs/openapi.json`, `docs/api-examples/**`.
- `API_CONTRACT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `ANALYSIS_ENGINE.md`, `FRONTEND_SPEC.md`, `DESIGN_SYSTEM.md`, `PROJECT_STATE.md`, `HANDOFF.md`, `TASKS.md`, `TEST_STATUS.md`, `PROMPT_DE_CONTINUACAO.md`, `.gitignore` raiz.
- Não faça commit/push sem autorização do usuário. Não use `git reset --hard`, `git clean`, force push.

## Stack (decidida — D-011)

- Node 24 (instalado), npm.
- Vite 5 + React 18 + TypeScript (strict).
- React Router 6, TanStack Query 5.
- `lightweight-charts` 4.x (gráficos), `lucide-react` (ícones), `@fontsource/inter`, `@fontsource/jetbrains-mono`.
- CSS Modules + `src/styles/tokens.css` (variáveis do DESIGN_SYSTEM). Sem Tailwind, sem bibliotecas de UI completas (MUI/Chakra/Antd).
- Tipos: `openapi-typescript` → `src/api/schema.d.ts` (script `gen:api`). Cliente: `fetch` fino em `src/api/client.ts` que lê `{error:{code,message,details}}` e lança um `ApiError` tipado.
- Testes: Vitest + @testing-library/react (+ jsdom); Playwright para smoke e2e.
- Vite: `server.proxy = { '/api': 'http://127.0.0.1:8000' }` (mesma origem → o cookie httpOnly funciona). Nunca coloque URL absoluta da API no código.

Versões: use as estáveis atuais compatíveis com o acima; registre as versões exatas em `frontend/CODEX_LOG.md`.

## Comandos

```bash
# Backend (já pronto): ver README.md da raiz
cd frontend
npm install
npm run gen:api      # gera tipos a partir de ../docs/openapi.json
npm run dev          # http://localhost:5173
npm run typecheck && npm run lint && npm test && npm run build
npm run test:e2e     # exige backend + worker rodando

# Verificação de produção (mesma origem, como no servidor gratuito):
npm run build
cd ../backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# abrir http://127.0.0.1:8000/  (SPA + API na mesma porta)
```

Credenciais de desenvolvimento: usuários `natan` e `alisson`, com a senha inicial definida pelo proprietário em `backend/.env` (pergunte ao usuário; **não** escreva a senha em nenhum arquivo do frontend, teste ou log). Para e2e, leia `E2E_USERNAME`/`E2E_PASSWORD` de variáveis de ambiente.

## Contrato e dados

- Use **somente** os endpoints de `API_CONTRACT.md`. Os tipos vêm do OpenAPI gerado.
- **Proibido** criar respostas falsas, mocks em runtime, "modo demonstração" ou valores fixos para preencher a tela. Mocks (MSW ou fixtures) são permitidos **apenas** em testes automatizados, e as fixtures devem vir de `docs/api-examples/` ou ser montadas a partir dos tipos gerados.
- Funcionalidade marcada como PLANEJADA (posição do usuário, carteiras, métricas sociais, push) não ganha controles ativos: mostre o texto informativo do campo `note` da API.
- `null` → "—" + explicação. Nunca 0.
- Se faltar algo no backend: **não invente endpoint**. Registre em `CONTRACT_ISSUES.md`:
  ```
  ## <data> — <endpoint/schema>
  - Esperado:
  - Real:
  - Impacto na UI:
  - Contorno adotado (seguindo o contrato atual):
  ```
  e avise o usuário para encaminhar ao Claude.

## Páginas e comportamento

Implementar exatamente o que está em `FRONTEND_SPEC.md` §2–§21. Ordem sugerida de entrega (cada etapa deve ser utilizável e testada antes da próxima):

1. Fundação: Vite + TS + tokens CSS + fontes + `AppShell` responsivo (sidebar/trilho/drawer) + cliente API + `gen:api` + guarda de autenticação + `/login` + `/account`.
2. `/tokens` (Explorador) com filtros na URL, tabela/cards, paginação, modal "Adicionar token".
3. `/tokens/:chainId/:address` (todas as seções do §13, gráfico).
4. `/alerts` + `/alerts/:id` + `NotificationBell`.
5. `/` Visão geral.
6. `/predictions` e `/system`.
7. Revisão de responsividade, acessibilidade e estados (vazio/erro/carregando/desatualizado).

Todo botão executa a ação real, mostra loading, mostra erro em caso de falha e reflete a resposta da API, ou fica desabilitado com o motivo visível.

## Testes necessários

- Unitários: formatadores (`format.ts`: preços com subscrito, USD compacto, percentuais, `null`), `ApiError`/cliente (401 → redireciona), `FreshnessBadge` (4 estados), `RiskBadge`.
- Componentes: Explorador (filtros → query string → chamada correta), `FactorList` com evidência, `NotificationBell` (clique navega para `alert.link`), estados vazio/erro.
- E2E (Playwright, backend real): login → dashboard → abrir token pela tabela → abrir alerta pelo sino → token correto; viewport 390×844 e 1366×768 sem rolagem horizontal (`document.documentElement.scrollWidth <= innerWidth`).
- Nunca altere um teste para forçar aprovação.

## Restrições arquiteturais

- Sem SSR/Next.js, sem backend Node próprio, sem armazenamento de dados de mercado no navegador (só `localStorage` para conveniências: último alerta visto, filtros recolhidos), sem bibliotecas de estado global além do TanStack Query (estado de UI local com `useState`/contexto).
- Sem analytics/telemetria de terceiros, sem CDN externa para scripts (ver "custo zero").
- Produção = `frontend/dist` servido pela API na mesma origem. Não crie servidor Node, Dockerfile de frontend nem configuração de hospedagem própria.

## Registro e continuidade

Ao final de cada etapa, atualize `frontend/CODEX_LOG.md` com: data, etapa, arquivos criados/alterados, comandos executados e resultados (copie a saída resumida), pendências, divergências registradas e próximos passos. Antes de encerrar a sessão, liste exatamente o que está implementado, o que está verificado e o que falta. O Claude fará a revisão e a integração final.
