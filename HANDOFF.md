# Handoff

## Sessão 11 — 2026-11-01 — negociações ao vivo e saída perto do topo (D-020)

- `app/tape/` (decode, book, store, processo), `app/notify.py`, `app/backup.py`, `app/supervisor.py`. `peak_call` reescrito. Mapa de bolhas removido; segurança em uma linha, com detalhes recolhidos.
- `start.bat` abre uma janela só; logs em `backend/data/logs/`. `stop.bat` salva cópia em `backend/data/backups/`.
- Trabalho em commits na branch `sistema-completo`; push depende do proprietário.


## Sessão 10 — 2026-10-30 — segurança e orquestrador (D-019)

- Plano e linha de base em `docs/PROMPT_ORQUESTRADOR.md`. Regressão do disparo em `tests/test_orchestrator.py`.
- Atenção: `app/security.py` é senha/sessão; o subsistema de moedas é `app/safety/`.
- Medido depois: dashboard 3,2 s → 0,013 s; Compre agora 6,2 s → ~0,11 s; idade do dado na análise mediana 25 → 20 s, p90 44 → 39 s; disparo sobe 72% em 15 min (n=40) contra 59% (n=213), amostra pequena.
- `outcomes.estimate` tinha 71% do custo da análise e `_cache` vazava memória: corrigidos sem mudar resultado.
- Tokens 6728 de 20 mil: a descoberta é o limite.


## Sessão 9 — 2026-10-30 — trader em tempo real e 10 mil tokens (D-018)

- `app/live/chain.py` + `FocusLane`: moeda aberta a ~1 s. `peak_call` em `app/live/service.py`. `app/sources/jupiter_tokens.py` na descoberta. Migração `0006` (`tokens.heat`). `_refresh_selection` prioriza a coleta. `tracked_list_items` e `_ranked_rows` com cache.
- Gráfico: `priceFormat` custom (o padrão arredondava em 0,01 e achatava memecoins). `TokenDetail.buy_simulation`. `features/alertPrefs.ts`.
- Favoritos congelados no clique: campos de ganho atual removidos da API.
- Medido com 2241 tokens: exit-plan ~50 ms, preço com até 2 s de idade em pump.fun. PumpSwap TYGR ficou sem ao vivo por pool quase vazia.
- Pendente: chegar aos 10 mil depende da descoberta; token com variação absurda (Pum Coin) segue podendo virar Compra prioritária; resto do caso USDF.


## Sessão 8 — 2026-10-30 — Favoritados e 1800 tokens (D-017)

- Backend: `app/engine/favorites.py`, `app/api/favorites.py` (`GET/POST /favorites`, `DELETE /favorites/{id}`, `GET /favorites/report`), migração `0005`, `OpportunityOut.signal_id`.
- Frontend: `features/favorites.tsx` (estrela e aba), hora do sinal nos cards, paleta e cantos ajustados em `styles/tokens.css`.
- Escala: ver D-017. Bug evitado: em coluna JSON, `raw=None` grava o JSON `null`; a limpeza usa `sqlalchemy.null()`.
- Reforma visual: paleta e acento em `styles/tokens.css`; barra lateral e componentes em `App.module.css`; Dashboard com números e sinais primeiro, saúde do sistema por último; moeda com mercado, decisão (sinal + quando vender) e gráfico no topo; cards de Compre agora com preço, score e motivos em destaque.
- Pendente: o que falta do caso USDF (marca permanente de golpe, liquidez travada, atividade artificial).


## Sessão 8 — 2026-10-30 — candles e simulação no detalhe do token

- `PriceChart` agora agrega candles de 1 min/5 min/15 min/1 h a partir dos snapshots existentes e das cotações rápidas observadas; não desenha volume ou negócios que a API não fornece.
- Clique numa vela para marcar "Começamos aqui" e abrir a leitura do sinal vigente/estimativas empíricas existentes. O campo de valor em USD calcula tokens, valor atual, P/L bruto e retorno ao lado do gráfico; não envia ordem nem altera a posição gravada.
- O painel compartilha a consulta `exit-plan` com "Quando vender" para reaproveitar o ciclo rápido de 10 s sem uma segunda chamada concorrente. O feed é da Jupiter e só cobre Solana; outras redes ficam no snapshot do coletor, com idade visível.
- Eixo e cursor formatam UTC no fuso local do navegador sem deslocar timestamps. Especificação atualizada em `FRONTEND_SPEC.md` §11; decisão D-017 em `DECISIONS.md`.
- Verificações: frontend 38 testes passaram, `typecheck` e `build` passaram. `lint` passou com um aviso preexistente de Fast Refresh em `features/sellplan.tsx`; nenhum E2E visual foi executado nesta sessão.
- Continuidade: validar a tela em navegador autenticado com tokens que tenham dados; confirmar o fuso e selecionar uma vela; não esperar candles nativos/stream da API pública da DEX Screener. Nenhum commit/push foi feito.

## Sessão 7 — 2026-10-29 — atualização rápida do "Quando vender" (D-016)

- Novo subsistema `backend/app/live/` (processo `python -m app.live`, aberto pelo `start.bat` numa janela própria e fechado pelo `stop.bat`). Fonte Jupiter Price v3, ciclo de 10 s, só tokens com o quadro aberto ou com posição. Migração `0004` (`live_watch`, `live_quotes`, `service_heartbeats`).
- `GET .../exit-plan` agora: registra o pedido na lista rápida, usa o preço rápido quando há cotação de até 30 s (`freshness.source = jupiter_price`), devolve `live { status: live|waiting|unavailable|off, observed_at, age_seconds, interval_seconds, price_usd, liquidity_usd, note }` e vende tudo com alerta de golpe ao vivo.
- `/health` ganhou `live` (estado do serviço); `degraded` se ele não estiver rodando.
- Quadro: selo "AO VIVO · preço conferido há N s", consulta logo após cada cotação nova, texto "Golpe detectado" quando o motivo é retirada de liquidez.
- Verificado rodando: primeira cotação ~3 s após abrir o quadro, depois intervalos de 10,0 s e preço diferente a cada ciclo.
- Testes: backend 122 passed (novo `test_live.py`: 14); frontend 34 passed.
- Ainda pendente do caso USDF (não pedido): marca permanente de golpe, checagem de liquidez travada via RugCheck/GoPlus, detector de atividade artificial.


## Sessão 6b — 2026-10-29 — filtro por nível na aba Acertos

- `GET /accuracy?tier=priority_buy|possible_buy|watch|sell`; `summary` traz os quatro níveis. "Observar" (sinal AGUARDAR) entra só como **referência** (julgado como "subiu sem sinal?"), fora das contagens de previsão. Tabela comparativa na aba.
- **Resultado real (1 h):** Compra prioritária 1/6 (17%), Compra possível 26/148 (18%), Observar 71/401 (18%), Venda 97/146 (66%). As compras acertam o mesmo que não fazer nada; a maioria das memecoins cai em 1 h, o que também ajuda a Venda. Próximo passo natural (não pedido ainda): revisar as regras de compra com esses dados, com validação antes de trocar.
- `/accuracy` sem cache leva ~3 s (avalia ~2 mil sinais); com cache de 30 s, instantâneo.
- Testes: backend 109 passed; frontend 29 passed.


## Sessão 6 — 2026-10-29 — aba Acertos e card Quando vender (Claude)

- **Aba Acertos** (`/acertos`, 5ª aba a pedido do proprietário): `engine/accuracy.py` (`acc-1`) + `GET /accuracy`. Sinal COMPRAR = "deve subir" (acerta se o preço ao fim do horizonte ficou acima do preço do sinal); VENDER = "deve descer". Horizontes 15 min / 1 h / 6 h; pendente até o horizonte; inavaliável sem coleta contínua. Interface: `features/accuracy.tsx`.
- **Primeiro resultado real (1 h, 2026-10-29):** 121 acertos e 171 erros (41%). Subida: 27/149 (18%). Queda: 94/143 (66%). Ou seja, os sinais de COMPRA estão errando a maioria; os de VENDA acertam mais. As regras não foram alteradas (o proprietário pediu para não implementar aprendizado por enquanto).
- **Card Quando vender** no detalhe do token, abaixo do sinal: `engine/exit_plan.py` (`exit-1`) + `GET /tokens/{c}/{a}/exit-plan`; `features/sellplan.tsx` consulta a cada 10 s e mostra a idade dos dados ao vivo ("há 3 min 12 s"). Urgência (vender agora / reduzir / manter), % a vender agora, alvos +20/+50/+100% (30/30/40%), stop −15%, gatilhos.
- Testes: backend **108 passed** (`test_accuracy_exitplan.py`); frontend **28 passed** (`accuracy.test.tsx`). Conftest limpa caches em memória entre testes.

## Sessão 5 — 2026-10-29 — prompt mestre: quatro abas, níveis, fontes e custo (Claude)

- **Fluxograma:** usada a exportação de 143 blocos colada pelo proprietário. O HTML em disco tem só a versão original (53 blocos); as edições estão no `localStorage` do navegador. Matriz em `docs/TRACEABILITY.md`.
- **Erro real corrigido (P0):** `sqlite3.OperationalError: database is locked` na API. Causa: `collector_run` gravava o registro no início e segurava a trava de escrita durante chamadas de rede lentas (RPC com espera de 429). Agora grava só no fim; `discover` faz commit por lote, `label_due` a cada 200 rótulos; o toque de sessão não derruba a requisição; banco ocupado responde 503 `database_busy`.
- **Novo:** `engine/ranking.py` + `GET /opportunities` (níveis, vetos, qualidade da decisão, score/confiança/cobertura separados, mudança do score); histerese de 5 pontos em `signals.decide`; `sources/registry.py` + `GET /system/registry` (36 fontes, classes A/B/C/D, só A ligadas); `worker` em `/health`; `worker_lock.py` (instância única); `start.bat`, `stop.bat`, `stop.ps1`.
- **Interface:** exatamente 4 abas (Dashboard, Compre agora, Alertas, Configurações); `/account` redireciona para `/settings`; sistema e previsões viraram páginas internas.
- **Docs:** `docs/DATA_SOURCES.md` e `docs/CONFIGURATION.md` (gerados do código), `docs/TRACEABILITY.md`, `docs/QUICKSTART_WINDOWS.md`, `docs/SECURITY_AND_COST.md`; `CODEX_PROMPT.md` com 3 tarefas.
- **Não commitado** (o proprietário pediu para não commitar até autorizar).

## Sessão 4 — 2026-10-28 — universo maior + alerta de disparo (Claude)

- **Descoberta ampliada** (`ingest/service.py`): perfis + impulsionados (latest/top) + buscas rotacionadas (8 termos/ciclo). `MAX_TRACKED_TOKENS` 40 → 600. Resultado real: 40 → **153 tokens** no primeiro ciclo, e com mais tokens já apareceu sinal de COMPRA.
  - A fonte **não** expõe "todo o DEX Screener": não há endpoint com todos os tokens, e cada busca devolve no máximo 30 pares (15 buscas = 132 tokens únicos, medido).
- **`prune_inactive`**: solta tokens sem vida (3 h sem par, ou liquidez < 1,5 mil e volume < 1 mil), preservando watchlist e posições.
- **Detector de disparo** `engine/burst.py` (`burst-1`): alerta `pump_burst` com estatística histórica do próprio padrão em 15 min. Interface: alerta próprio no centro da tela (prioridade sobre os demais), som de rajada, e linha "DISPARO AGORA" na lista do dashboard.
- **Correções**: `compute_features` não expunha `buys_m5`/`sells_m5` (o detector nunca via as compras); `discover()` criava tokens mas devolvia lista vazia (worker reportava 0). Ambas cobertas por teste.
- Verificações de contrato agora priorizam tokens com oportunidade alta (RPC gratuito não cobre 600).
- Testes: backend **78 passed**, frontend **20 passed**; lint/typecheck/build OK. `conftest` deixou de depender do `backend/.env` local.

## Sessão 3b — 2026-10-28 — saldo para simulação + som de alerta (Claude)

- Migração `0003` (colunas `users.balance_amount`, `balance_currency` BRL/USD, `max_trade_percent` padrão 10), aplicada no banco local.
- `GET/PUT /auth/settings`; `SignalOut.allocation` e `AdviceOut.buy_percent_of_balance/buy_amount/currency` por usuário. Regra `size-1` (`engine/signals.py::allocation`): compra forte = teto por operação; moderada = metade; risco ≥ 25 → metade de novo.
- Interface: aba Conta com "Saldo para simulação" e "Som dos alertas" (ligar/desligar + testar); o alerta central diz "Compre agora com X% do seu saldo (R$ Y)" e toca um som (Web Audio, sem arquivo): compra = bipes subindo, venda = descendo. O navegador só libera áudio após um clique na página.
- Testes: backend 67 passed; frontend 18 passed; lint, typecheck e build OK. Sistema reiniciado via `run-local.ps1`.

## Sessão 3 — 2026-10-28 — sinais de compra/venda, interface mais simples, 30 s (Claude)

- **"Erro na API" relatado:** a varredura de todos os endpoints na API em execução não achou 500. Achados: 3 tokens sem par fazem `/exit-estimate` responder 404 e a página do token tratava isso como erro (corrigido: a consulta só ocorre quando há par); o RPC Solana segue com 429 ("degradado").
- **Backend:** migração `0002` (tabelas `analysis_outcomes`, `signals`, `positions`, aplicada ao banco local); `engine/outcomes.py` (rótulos 15 min/1 h/6 h + estimativas empíricas sem vazamento); `engine/signals.py` (regras `sig-1`, sugestão `advice-1`, desempenho); rotas `/signals`, `/signals/performance`, `/signals/{id}`, `/positions`; detalhe do token com `signal`, `estimates`, `position`, `advice`; coletor a cada 30 s; `cli evaluate` também rotula.
- **Frontend:** a página do token agora traz sinal + estimativas → minha posição/sugestão → mercado resumido → gráfico → alertas, e "Detalhes técnicos" recolhidos no fim. "Sinais agora" no topo do dashboard. Alerta modal global (`SignalWatcher`) para sinais novos de compra forte/venda, com notificação opcional do navegador. Tudo atualiza a cada 30 s. Correção do formatador de preço (`0,0₄6814`).
- **Defeitos achados na verificação real e corrigidos:** "Venda agora" emitido para token com cotação de 2 h atrás, e "vender" causado só por falta de verificação. Agora: dados velhos → aguardar; venda por risco usa só o risco observado.
- **Verificado no navegador (dados reais):** o modal apareceu para o sinal novo e levou ao token; página do token em 390 px sem rolagem horizontal; registro de posição → "Vender 100%" (sinal de venda forte) → removida.
- **Atenção:** a API (porta 8000) e o coletor que o proprietário deixou rodando são a versão **antiga** e não geram sinais. É preciso reiniciar (fechar e rodar `run-local.ps1`).

## Sessão 2 — 2026-10-28 — integração do frontend do Codex (Claude)

O Codex entregou `frontend/` (não commitado; ver `frontend/CODEX_LOG.md`). Ao rodar localmente, a página **recarregava sem parar**. Corrigido e verificado no navegador com dados reais:

1. **Loop de recarga (P0):** o tratador global de 401 fazia `window.location.assign('/login?next=...')`, e isso valia também na própria tela de login (`/auth/me` → 401 → recarrega → ...; o `next` crescia indefinidamente). Agora usa navegação do roteador, ignora o `/login` e existe um único tratador (havia dois). Teste de regressão em `src/components/AuthRedirect.test.tsx`, que falha com o código antigo.
2. **`next` ignorado após o login:** o `LoginRoute` mandava sempre para `/`. Agora respeita `next` (com `safeNext`, que bloqueia `//` e `/login`). Teste adicionado.
3. **Alertas de token sem símbolo exibidos como "Sistema":** agora mostram o endereço abreviado (`alertSubject`).
4. **Rolagem horizontal no celular** na página do token: o JSON da verificação técnica não quebrava a linha. Corrigido (`overflow-wrap:anywhere`).
5. `run-local.ps1`: preparação + inicialização local com um comando (testado com `-NoStart`).

Verificado no navegador (build servido pela API): login → dashboard → alerta → token correto (ZMINER) → F5 mantém a sessão → logout sem loop → rota protegida redireciona uma vez. Em 390 px: `/`, `/tokens`, `/alerts`, detalhe do token, `/predictions` e `/system` sem rolagem horizontal.

Pendências: e2e Playwright não executado; `npm audit` com avisos (sobretudo em dependências de desenvolvimento, ver CODEX_LOG); frontend ainda não commitado.

Novos pedidos do proprietário (ainda não implementados): sinais de compra em destaque (modal em qualquer página), sugestão de "vender/comprar X%" na página do token e estimativa de valorização por horizonte ("em 1 h, +X%").

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
