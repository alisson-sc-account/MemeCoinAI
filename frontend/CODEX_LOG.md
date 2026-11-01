# Registro do frontend — MemeCoinAI

## 2026-10-28 — Sinais e simplificação (Claude, a pedido do proprietário)

- Novo `src/features/signals.tsx` (+ `.module.css`, `.test.tsx`): `SignalHero`, `Estimates`, `PositionPanel`, `ActiveSignals`, `SignalWatcher` (modal global) e `REFRESH_MS = 30_000`.
- `TokenDetailPage` reescrita (multilinha): sinal → posição → mercado resumido → gráfico → alertas; detalhes técnicos em `<details>` no fim (`.moreDetails` em `App.module.css`). `/exit-estimate` só é chamado para valores personalizados e quando há par.
- Todos os `refetchInterval` de 60 s passaram a `REFRESH_MS` (30 s).
- `lib/format.ts`: zeros subscritos sem vírgula na mantissa (`0,0₄6814`); o teste antigo exigia o formato com defeito e foi corrigido.
- Tipos regenerados (`npm run gen:api`) após as rotas novas.

## 2026-10-28 — Revisão de integração (Claude)

Correções feitas pelo líder técnico após o teste local do proprietário (ver `HANDOFF.md`, sessão 2):
- `App.tsx`: o tratador de 401 usava `window.location.assign` inclusive no `/login` → recarga infinita. Agora: `navigate` do roteador + localização por ref + nenhuma ação no `/login`; removido o tratador duplicado do `AppShell`.
- `App.tsx`: `LoginRoute`/`LoginPage` respeitam `next` via `safeNext`.
- `App.tsx`: `alertSubject` (token sem símbolo → endereço; só alerta sem token é "Sistema").
- `App.tsx`: JSON da verificação técnica com `overflowWrap:'anywhere'` (estourava 390 px).
- Novo `src/components/AuthRedirect.test.tsx` (3 testes). Suíte: 14 passed; typecheck, lint e build OK.

## 2026-10-28 — Fundação e fluxos principais

### Etapa concluída

- Criada a aplicação frontend com Vite 5, React 18 e TypeScript estrito.
- Implementados layout responsivo, sidebar/trilho/drawer, login por cookie da API, conta/troca de senha/logout, estado de troca obrigatória de senha, tratamento global de sessão expirada, busca de fontes e indicador/banner de indisponibilidade.
- Implementados explorador com filtros na URL e paginação, adicionar/parar monitoramento, detalhe do token, histórico/gráfico sob demanda, evidências, verificações, cenários genéricos de saída, alertas/alteração de estado, sino de alertas, previsões/métricas e sistema/execuções de coletores.
- Os dados de tela vêm dos endpoints documentados; não há fixtures nem respostas demonstrativas no runtime. O gráfico informa que os dados são snapshots e inclui a atribuição ao TradingView exigida pela licença.
- Tipos regenerados do OpenAPI com `npm run gen:api`.

### Arquivos

Aplicação: `index.html`, `package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig.json`, `eslint.config.js`, `playwright.config.ts`, `.gitignore`, `src/App.tsx`, `src/App.module.css`, `src/main.tsx`, `src/ui.tsx`, `src/styles/*`, `src/api/*`, `src/lib/*`, `src/components/*`, `src/test/setup.ts`, `e2e/smoke.spec.ts`.

### Dependências diretas e licenças

Versões instaladas no lockfile; licenças lidas dos `package.json` instalados:

| Pacote | Versão | Licença |
|---|---:|---|
| `@fontsource/inter` | 5.3.0 | OFL-1.1 |
| `@fontsource/jetbrains-mono` | 5.3.0 | OFL-1.1 |
| `@tanstack/react-query` | 5.105.0 | MIT |
| `lightweight-charts` | 4.2.3 | Apache-2.0 |
| `lucide-react` | 0.468.0 | ISC |
| `react` | 18.3.1 | MIT |
| `react-dom` | 18.3.1 | MIT |
| `react-router-dom` | 6.30.6 | MIT |
| `@playwright/test` | 1.64.1 | Apache-2.0 |
| `@testing-library/jest-dom` | 6.9.1 | MIT |
| `@testing-library/react` | 16.3.3 | MIT |
| `@testing-library/user-event` | 14.6.8 | MIT |
| `@types/react` | 18.3.31 | MIT |
| `@types/react-dom` | 18.3.7 | MIT |
| `@vitejs/plugin-react` | 4.7.0 | MIT |
| `eslint` | 9.39.5 | MIT |
| `eslint-plugin-react-hooks` | 5.2.0 | MIT |
| `eslint-plugin-react-refresh` | 0.4.26 | MIT |
| `jsdom` | 25.0.1 | MIT |
| `openapi-typescript` | 7.13.0 | MIT |
| `typescript` | 5.7.3 | Apache-2.0 |
| `typescript-eslint` | 8.72.1 | MIT |
| `vite` | 5.4.21 | MIT |
| `vitest` | 2.1.9 | MIT |

### Verificações executadas

- `npm install` — concluído; registrou 8 avisos de vulnerabilidade no grafo de dependências (5 moderadas, 1 alta, 2 críticas).
- `npm run gen:api` — concluído; schema gerado de `../docs/openapi.json`.
- `npm run typecheck` — passou.
- `npm run lint` — passou.
- `npm test` — passou: 4 arquivos, 11 testes.
- `npm run build` — passou após os últimos ajustes. Bundle JS/CSS inicial: 94,18 KB gzip (81,35 KB JS + 12,83 KB CSS); gráfico em chunk separado de 52,54 KB gzip.
- `npm audit --json` — retornou 8 vulnerabilidades (5 moderadas, 1 alta, 2 críticas). `npm audit --omit=dev --json` retornou 2 moderadas em `react-router-dom@6.30.6` / `react-router`, relacionadas a open redirect via backslash e SSR hydration; correção indicada exige React Router 7.18.5 (major). O código valida rotas recebidas da API antes de navegar, mas a auditoria da dependência continua pendente. As falhas críticas/moderadas restantes estão no grafo de desenvolvimento/testes, incluindo Vitest 2 e Vite 5; as correções apontadas pelo registro exigem atualização fora da stack definida em D-011. Não foi executado `npm audit fix` nem upgrade major sem decisão do líder técnico.
- E2E — não executado: API local indisponível, variáveis `E2E_USERNAME`/`E2E_PASSWORD` ausentes e navegador Playwright não instalado localmente.

### Pendências / limites

- Conferir com o responsável técnico atualizações compatíveis de React Router, Vite e Vitest para resolver os avisos de segurança; D-011 fixa React Router 6 e Vite 5, e a correção do npm exige major em pelo menos parte dos pacotes.
- Executar Playwright contra API e worker reais com credenciais fornecidas por variáveis de ambiente e Chromium instalado localmente.
- Verificar visualmente os breakpoints 360×800, 390×844, 768×1024, 1366×768 e 1920×1080 quando houver ambiente de navegador disponível.
- Revisar em integração as respostas e estados com a API/worker em execução. Não houve mudanças no backend nem no contrato.
- Páginas compartilham o chunk principal; o gráfico é carregado sob demanda. O chunk inicial está abaixo do orçamento, mas a divisão por página pode ser refinada após a revisão do líder técnico.
- A lista de notificações navega pelo `alert.link`; marcador visual “Novo” por usuário e drawer móvel dedicado para notificações ainda precisam de refinamento.

### Próximos passos

1. Rodar backend + worker locais e fornecer credenciais de teste somente em `E2E_USERNAME`/`E2E_PASSWORD` no ambiente do processo, sem gravá-las em arquivos.
2. Instalar Chromium localmente via Playwright e executar `npm run test:e2e`.
3. Fazer revisão de segurança da versão de Vite/Vitest com o líder técnico e confirmar a matriz visual em navegador.
