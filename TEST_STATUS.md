# Status dos testes

## 2026-10-30 — sessão 9 (tempo real, 10 mil tokens)

Backend e frontend verdes em `pytest` e `npm test`. Novos: leitura de reservas, calibração, foco por segundos, `peak_call`, prioridade de coleta, retenção de snapshots, favorito congelado, simulação automática, escolha de alertas.

## 2026-10-30 — sessão 8 (Favoritados e 1800 tokens)

Novos: `backend/tests/test_favorites.py`, dois testes em `test_burst_discovery.py`, `frontend/src/features/favorites.test.tsx`. Resultados na mensagem da sessão e em `pytest` / `npm test`.

## 2026-10-29 — sessão 7 (atualização rápida)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **122 passed** (novo `test_live.py`: 14 — lista com expiração, posições sempre, ciclo e falha da fonte, batimento, golpe ao vivo e falso alarme, estados do `live`, retenção, API do plano com preço rápido, venda total no golpe, `/health`) |
| `cd frontend; npm test` | **34 passed** (selo AO VIVO, ao vivo desligado, texto de golpe, ritmo de consulta) |
| Rodando de verdade | 1ª cotação ~3 s após abrir o quadro; depois 10,0 s entre cotações; preço mudou em todos os ciclos |


## 2026-10-29 — sessão 6 (Acertos e Quando vender)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **108 passed** (novo `test_accuracy_exitplan.py`: 10) |
| `cd frontend; npm test` | **28 passed** (novo `features/accuracy.test.tsx`: 4; teste de navegação agora espera 5 abas) |
| typecheck / lint / build | OK |
| Navegador (dados reais) | aba Acertos: 1 h = 121 acertos, 171 erros; card Quando vender com refetch a cada 10 s e idade dos dados atualizando |

## 2026-10-29 — sessão 5 (prompt mestre: 4 abas, níveis, registro de fontes, travas)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **98 passed** (novos: `test_ranking_registry.py` 17 — casos 16.5, histerese, política de custo, trava do worker, health, `/opportunities`; `test_db_contention.py` 3 — regressão do "database is locked") |
| `cd frontend; npm test` | **24 passed** (novo `features/buynow.test.tsx`: 4 abas exatas, vários tokens com nível/score/confiança/cobertura, filtro na URL, bloqueio crítico, erro da API) |
| `npm run typecheck`, `npm run lint`, `npm run build` | OK |
| `stop.bat` e `start.bat` (execução real) | encerrou e reiniciou API + worker; segundo worker recusado (saída 1, "outro worker já está rodando") |
| Navegador (dados reais, :8000) | 4 abas; Compre agora com 600 tokens (1 prioritária, 7 possíveis, 550 observar, 42 evitar); Configurações com 36 fontes (2 ligadas); Dashboard "Coletor rodando"; nenhum "database is locked" no log da API depois da correção |
| Verificação pontual de fontes sem chave | GeckoTerminal, Jupiter lite, RugCheck e GoPlus: HTTP 200; Birdeye: 401 |
| `npm run test:e2e` | **não executado** (Chromium do Playwright não instalado) |

## 2026-10-28 — sessão 4 (universo maior + disparo)

| Comando | Resultado |
|---|---|
| `cd backend; pytest` | **78 passed** (novo `tests/test_burst_discovery.py`: 11 — regras do disparo, estatística sem vazamento, alerta e auto-resolução, descoberta pelas 4 origens, capacidade, limpeza) |
| `cd frontend; npm test` | **20 passed** (alerta de disparo com som próprio e histórico do padrão) |
| typecheck / lint / build | OK |
| Execução real | 40 → **153 tokens** monitorados num ciclo; origens: perfis 49, buscas 72, impulsionados 31; sinal de COMPRA apareceu |
| API em execução | `/alerts?alert_type=pump_burst` 200; `/meta` lista `pump_burst` como oportunidade |

## 2026-10-28 — sessão 3 (sinais, posição, 30 s)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **64 passed** (inclui `tests/test_signals.py`: regras, regressões de dado velho e de risco só por falta de dados, rótulos sem vazamento, estimativas, deduplicação de sinais, sugestão de posição, API de sinais/posições, isolamento por usuário) |
| `cd frontend; npm test` | **16 passed** (inclui `features/signals.test.tsx`: modal só para sinais novos, ignora compra moderada, navega ao token; formatador com zeros subscritos) |
| `npm run typecheck`, `npm run lint`, `npm run build` | OK |
| Varredura HTTP de todos os endpoints na API em execução (40 tokens) | nenhum 500; apenas 404 esperados de `exit-estimate` para tokens sem par |
| Migração `0002` no banco local | aplicada (só criação de tabelas) |
| Dados reais | 216 rótulos (135 válidos de 15 min); sinais reais gerados (venda forte para CATCULUS: liquidez −60% e preço −40% em 1 h) |
| Navegador (API nova em :8001) | modal de sinal → token correto; página do token em 390 px sem rolagem; registro e remoção de posição |

## 2026-10-28 — sessão 2 (integração do frontend)

| Comando | Resultado |
|---|---|
| `cd frontend; npm run typecheck; npm run lint` | sem erros |
| `cd frontend; npm test` | **14 passed** (11 do Codex + 3 de `AuthRedirect.test.tsx`) |
| Teste de regressão contra o código antigo (recarga no 401) | **falha** como esperado (2/2) → confirma que detecta o bug |
| `npm run build` | OK (JS inicial 81 KB gzip; gráfico 52 KB gzip sob demanda) |
| `run-local.ps1 -NoStart` | OK (migração, usuários, build; detecta porta ocupada) |
| Navegador (build servido pela API, dados reais) | login, dashboard, alerta → token correto, F5, logout e redirect `next` OK; 390 px sem rolagem horizontal em 6 páginas |
| `npm run test:e2e` | **não executado** (Chromium do Playwright não instalado) |

## 2026-10-28 — sessão 1 (continuação: custo zero)

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **49 passed** (47 anteriores + 2 de `test_frontend_serving.py`: SPA, fallback de rotas do cliente, assets, proteção contra path traversal, 404 de API no formato padrão, ausência de build) |

## 2026-10-28 — sessão 1

| Comando | Resultado |
|---|---|
| `cd backend; .\.venv\Scripts\python.exe -m pytest` | **47 passed** (~20 s), 0 falhas |
| `python -m app.cli migrate` (SQLite real) | migração `0001` aplicada |
| `python -m app.cli seed-users` | 2 usuários criados (hash Argon2id verificado em teste) |
| `python -m app.cli track solana DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | **dados reais**: BONK, risco 30, oportunidade 12,5 (antes das verificações técnicas) |
| `python -m app.cli discover` | **dados reais**: 39 tokens adicionados (limite local 40) |
| `python -m app.cli refresh` | **dados reais**: 35 tokens com dados novos, 35 análises; 4 tokens sem par retornado pela fonte |
| `python -m app.cli checks 3` | **dados reais**: 3 mints `ok` (2 spl-token, 1 token-2022); `getTokenLargestAccounts` → **429** nos 3 |
| API via HTTP (uvicorn local) | health 200; 401 sem sessão; login OK; dashboard, filtros, detalhe, alertas OK com dados reais |

### Cobertura (resumo)
- Unitários: normalização (strings numéricas, ausentes = None, identidade, EVM/Solana), features sem vazamento temporal, scores (dados ausentes ≠ risco baixo, rede não suportada, autoridade de mint, queda de liquidez, teto de oportunidade), slippage x*y=k e mapeamento de 8 tipos de pool, HTTP (429→retry, 5xx com limite, 404 sem retry, erro de rede), parse de mint real e Token-2022, concentração.
- Integração: hash de senha, 401 em rotas protegidas, login/logout/limite/troca de senha, deduplicação de snapshots em cache, pares em que o token é quote ignorados, fonte fora → alerta de sistema → resolução, queda de liquidez → alerta crítico deduplicado, escalonamento de severidade, alteração de permissão, auto-resolução de alertas de condição, ciclo de vida da previsão (pendente → avaliada; inavaliável), API ponta a ponta, 404/502 ao adicionar, dados `stale` e agregados, limitação de persistência de análises.
- As migrações Alembic são aplicadas em todo teste (banco temporário).

### Não executado / ausente
- Suíte contra **PostgreSQL** (não instalado).
- **Worker contínuo** por horas; avaliação de previsões reais (requer ≥ 6 h de coleta).
- Testes de interface (frontend não existe).
- Testes de carga.
- Avisos conhecidos: `StarletteDeprecationWarning` (TestClient com httpx), sem impacto.
