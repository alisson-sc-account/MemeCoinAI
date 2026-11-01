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

## D-014 Sinais de compra/venda, estimativas por horizonte e sugestão de posição (pedido do proprietário)
- **Problema:** o proprietário quer saber "o que vai subir", receber um alerta em destaque ("compre agora" / "venda") e ver quanto vender ou comprar.
- **Decisão:** regras explícitas `sig-1` (ANALYSIS_ENGINE §9) + estimativas empíricas por horizonte medidas pelo próprio sistema (§10) + sugestão `advice-1` com posição informada manualmente (§11). Alerta modal na interface para sinais novos de compra forte e de venda; notificação do navegador opcional (gratuita).
- **Alternativas rejeitadas:** prometer porcentagem exata ou previsão de 2 minutos (a fonte gratuita tem até ~60 s de atraso; seria ruído); usar modelo de ML agora (sem histórico suficiente).
- **Consequências:** as estimativas começam com poucos casos e melhoram com o coletor ligado; o acerto real fica visível em `/signals/performance`.
- **Revisar:** com ≥ 100 sinais avaliados por tipo, recalibrar os limiares usando divisão temporal.

## D-015 Atualização a cada 30 s
- Coletor e interface passam de 60 s para 30 s. A fonte tem cache de ~60 s, então parte das coletas repete dados (deduplicados); o ganho é ver a mudança até 30 s antes, sem custo adicional (bem abaixo do limite de 300 req/min).

## D-019 Segurança das moedas e orquestrador de agentes (proprietário, 2026-10-30)
- **Segurança (`app/safety`, `sec-1`):** processo próprio. RugCheck (liquidez travada, donos sem a pool, insiders), carteiras novas (triagem no publicnode, ~63 h de histórico; confirmação no RPC oficial, muito limitado), atividade artificial, liquidez x valor, nome que imita algo oficial. Nunca diz "seguro": "Sem alertas" ou "Sem dados". Perigo bloqueia compra; compra forte exige verificação limpa. Marca de golpe é permanente. Bubblemaps fora: API pública sem mapa, oficial paga; mapa próprio no quadro da moeda.
- **Orquestrador (`app/worker.py`, `app/agents.py`):** agentes por categoria em threads. Coleta separada da análise por fila com prioridade. Radar promove quem aparece em "mais negociados agora" por 15 min. Painel em processo próprio (`app/board.py`, `data/board.db`).
- **Limite de 20 mil:** o DEX Screener (300 req/min) não permite todos ao mesmo tempo. Quentes a cada ~30 s, demais em rodízio. Sem proxies ou contas para burlar limite. O número real depende da descoberta.
- **Previsão antecipada rejeitada:** backtest com divisão por tempo: regras de pré-disparo atingiram +20% em 0% a 5% dos casos na prova, contra 68% do Disparo atual. Não entraram. `burst-1` congelado por teste.
- **Dado impossível:** variação acima de +100.000% bloqueia compra (`IMPOSSIBLE_CHANGE_PCT`).
- **Revisar:** limiares de segurança com falsos positivos reais; as regras foram desenhadas olhando a USDF, um caso só; 83 de 169 verificadas deram perigo, o que pode estar rígido demais.

## D-018 Trader em tempo real e 10 mil tokens (proprietário, 2026-10-30)
- **Moeda aberta a ~1 s:** pista própria em `app/live` lê as reservas da pool na Solana (`getMultipleAccounts`, RPC público). Medido: Jupiter responde 429 acima de 5 chamadas por 10 s e tem cache de 5 s; DEX Screener segura ~30 s. Só a blockchain muda a cada segundo.
- **Pools:** pump.fun, PumpSwap, Raydium CPMM e AMM v4. As demais (CLMM, Meteora, Orca) ficam na cotação de 10 s. A razão bruta nem sempre bate com o preço das fontes, então o preço é calibrado pela cotação mais recente e só a variação das reservas o move: é uma estimativa ao vivo, não o preço de execução. Pool quase vazia é recusada.
- **Venda:** regra `peak_call`: queda de 8% do topo de 15 min = vender 50%; 15% = vender tudo; retirada de liquidez = tudo. Duas leituras seguidas, agora ~2 s na moeda aberta (antes ~20 s). Limiares fixos, não calibrados: podem vender em oscilação normal e ninguém detecta o topo exato.
- **Alertas:** venda fica dentro da moeda; Configurações escolhe o que abre no meio da tela (padrão: compra forte e disparo).
- **Simulação:** automática desde o último sinal de compra, com 1.000 moedas e também US$ 1.000.
- **10 mil tokens:** limite do DEX Screener (300/min) não cobre todos a cada ciclo. Urgentes e os 1500 mais quentes atualizam todo ciclo; os demais, em rodízio (`Token.heat`). Descoberta com Jupiter e buscas por duas letras. Listas com cache de 15 s. Payload bruto desligado; snapshots além de 15 dias apagados automaticamente, exceto de moedas com posição.
- **Revisar:** os limiares de venda com os dados da aba Acertos e os favoritos copiados pelo proprietário; crescimento do banco.

## D-017 Favoritados e escala para 1800 tokens (proprietário, 2026-10-30)
- **Favoritados (`fav-1`):** estrela em Compre agora, Acertos e no detalhe do token. Cada clique grava uma foto imutável (preço, ganho, melhor e pior momento até ali, e as especificações do motor). A aba Favoritados mostra só esse registro, congelado no clique (pedido do proprietário: o ganho não continua contando), e copia um relatório em texto + JSON, para o proprietário colar na conversa e orientar ajustes. Favorito é por usuário e por previsão (sinal).
- **Escala:** limite de 600 para 1800 tokens. Descoberta a cada 60 s (era 300), mais termos, e GeckoTerminal como fonte nova (classe A, sem chave, sem o viés das listas pagas; pools abaixo de US$ 3 mil não gastam vaga).
- **Agentes:** cada job do worker roda em thread própria; RPC lento não atrasa preço. Uma trava serializa as análises.
- **Banco:** `synchronous=NORMAL` com WAL e cache maior. Payload bruto limpo sozinho após 1 dia (dados normalizados ficam).
- **Holders:** após 429 em `getTokenLargestAccounts`, o método fica 10 min em pausa, e o dado segue "sem verificação".
- **Limite conhecido:** o crescimento do banco aumenta com 3x mais tokens; snapshots normalizados não são apagados automaticamente. Revisar a retenção se o disco apertar.

## D-016 Atualização rápida do "Quando vender" como subsistema próprio (proprietário, 2026-10-29)
- **Problema:** o quadro "Quando vender" demorava para mudar. O coletor percorre 600 tokens (~60 s por volta) e o DEX Screener segura o mesmo preço por ~30 s no cache dele (medido: 3 consultas seguidas de 10 s devolveram o mesmo preço). O proprietário exige atualização a cada 10 s.
- **Decisão:** um subsistema dedicado a essa função (`backend/app/live/`, regras `live-1`), com processo próprio (`python -m app.live`), trava própria (`data/live.lock`), fonte própria e tabelas próprias (`live_watch`, `live_quotes`, `service_heartbeats`). Primeiro de uma série: cada função crítica ganha o seu subsistema.
  1. **Fonte:** Jupiter Price API v3 (`lite-api.jup.ag/price/v3`, sem chave, classe A, cache de 5 s, até 50 tokens por requisição). Medido em 2026-10-29: o preço mudou em todas as consultas de 10 s.
  2. **Escopo:** só os tokens com o quadro aberto (vale por 60 s após a última consulta) e os com posição registrada; no máximo 100. Assim o custo é ~1 requisição a cada 10 s, não 600 tokens.
  3. **Ritmo:** ciclo fixo de 10 s pelo relógio; quadro recém-aberto é cotado na hora (~1–3 s). O quadro consulta logo depois de cada cotação nova.
  4. **Golpe ao vivo:** comparando só cotações rápidas entre si, liquidez ≤ 40% do máximo de 15 min ou preço ≤ 60% do máximo de 5 min, em 2 leituras seguidas, viram "Vender tudo agora" com o motivo (caso USDF).
  5. **Sem o serviço** a API volta sozinha ao preço do coletor e diz isso (`live.status = off`); `/health` fica `degraded`.
- **Alternativas rejeitadas:** baixar o intervalo do coletor para 10 s (600 tokens × cache de 30 s da fonte = mesmo preço repetido e 6× mais requisições); consultar a fonte dentro da requisição da API (acopla a API à fonte externa e multiplica chamadas por aba aberta).
- **Limites:** a liquidez da Jupiter é a soma das pools (não é a do par principal) e só é comparada com ela mesma; o limite exato de uso da Jupiter não está documentado na resposta (o cliente respeita HTTP 429).

## D-017 Candles agregados e simulador no gráfico do token (proprietário, 2026-10-30)
- **Decisão:** apresentar candles verdes/vermelhos agregando observações reais do histórico e do feed rápido; intervalos de 1 min, 5 min, 15 min e 1 h para as janelas 1h, 6h, 24h e 7d. Não fabricar OHLC, volume ou trades.
- **Dados rápidos:** compartilhar no frontend a consulta existente de plano de saída, que já acompanha Solana pela Jupiter a cada 10 s. Outras redes e estados degradados exibem o último snapshot com sua idade.
- **Agente:** ao selecionar uma vela, apresentar o sinal vigente e estimativas empíricas já retornados pelo motor. A interface não cria previsão nem chama IA generativa.
- **Simulação:** valor inicial em USD e preço da vela escolhida (ou preço atual) determinam quantidade teórica de tokens e P/L bruto; cálculo local, sem ordem, persistência ou efeito na posição registrada. Taxas e slippage ficam explicitamente fora.
- **Tempo:** timestamps permanecem UTC para dados e ordenação; somente eixo e cursor usam o fuso local do navegador.
- **Limitação da fonte:** a API pública documentada do DEX Screener não oferece candles OHLC nem stream de preço; o gráfico é agregado das observações do sistema, não equivalente a todos os trades/candles do site.

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
