# Especificação do frontend

Complementa `DESIGN_SYSTEM.md` (visual) e `API_CONTRACT.md` (dados). Em caso de conflito: o contrato de API prevalece sobre este documento, e este prevalece sobre preferências de implementação.

## 1. Missão e usuários

Painel web privado para dois usuários (`natan`, `alisson`) investigarem memecoins: ver o que o motor monitora, entender **por que** cada token tem determinado risco/oportunidade, receber alertas e checar se os dados estão atualizados. A interface exibe **somente** dados vindos da API. Sem cadastro público, sem execução de ordens.

Regras inegociáveis:
- Nada de dados fictícios, placeholders numéricos ou respostas simuladas em tempo de execução.
- Todo número mostra (ou permite ver) sua idade/frescor quando vier de mercado.
- `null` → "—" com texto explicativo; nunca 0.
- Scores **não** são probabilidade de lucro; previsões são "não calibradas" enquanto `calibrated=false`.

## 2. Rotas e páginas

Há **exatamente quatro abas principais** na navegação (`routes` em `frontend/src/App.tsx`). As páginas internas são acessadas por links de conteúdo ou pela página Configurações, sem criar outras abas.

| Aba/rota | Página | Endpoints principais |
|---|---|---|
| `/` | Dashboard | `GET /dashboard/summary` |
| `/compre-agora` | Compre agora (ranking de oportunidades) | `GET /opportunities` |
| `/alerts` | Alertas | `GET /alerts`, `PATCH /alerts/{id}` |
| `/settings` | Configurações: saldo de simulação, som, fontes e custo, sistema, senha e sessão | `GET/PUT /auth/settings`, `GET /system/registry`, `GET /health`, `POST /auth/change-password`, `POST /auth/logout` |
| `/login` | Login | `POST /auth/login` |
| `/tokens` | Explorador interno, sem aba | `GET /tokens`, `GET /meta`, `POST /tokens/track` |
| `/tokens/:chainId/:address` | Detalhe do token interno, sem aba | `GET /tokens/{c}/{a}`, `/history`, `/exit-estimate`, `DELETE .../track` |
| `/alerts/:id` | Detalhe do alerta interno, sem aba | `GET /alerts/{id}` |
| `/predictions` | Previsões e desempenho interno, sem aba | `GET /predictions`, `GET /predictions/metrics` |
| `/system` | Saúde, fontes e execuções internas, sem aba | `GET /system/sources`, `GET /health` |
| `/account` | Compatibilidade: redireciona para `/settings` | — |
| `*` | 404 com link para `/` | — |

Todas, exceto `/login`, são protegidas: na inicialização, `GET /auth/me`; 401 → `/login?next=<rota>`. Qualquer 401 posterior limpa o cache do TanStack Query e redireciona.

## 3. Navegação

- Regra fixa: exibir **exatamente quatro abas principais** — Dashboard (`/`), Compre agora (`/compre-agora`), Alertas (`/alerts`) e Configurações (`/settings`). Desktop e drawer móvel mostram as mesmas quatro opções. Cada link da navegação principal expõe seu nome em `aria-label`.
- Explorador (`/tokens`), detalhe do token (`/tokens/:chainId/:address`), detalhe do alerta (`/alerts/:id`), previsões (`/predictions`) e sistema (`/system`) são páginas internas, não abas. As páginas de token ficam sob Compre agora como aba ativa; previsões e sistema ficam sob Dashboard. `/account` redireciona a `/settings`.
- Em telas largas, a navegação fica na sidebar; em telas estreitas, a top bar abre um drawer com as quatro abas. A top bar também mostra o estado das fontes (link para `/system`) e o sino de notificações.
- Banner global (abaixo da top bar) quando `must_change_password=true`: "Senha inicial em uso. Troque antes de expor o sistema." com link para `/settings`.
- Banner global quando `dexscreener.status == "down"`: "Fonte de mercado indisponível desde HH:MM. Valores exibidos podem estar desatualizados."

## 4. Hierarquia visual

Cada página: `h1` + subtítulo `small` muted com o frescor da página ("Dados de 19:57 · atualiza a cada 60 s"). Primeiro os sinais acionáveis (alertas críticos, riscos), depois as listas e por fim os detalhes técnicos (features, JSON de evidência recolhido).

## 5–7. Paleta, tipografia, espaçamentos
Conforme `DESIGN_SYSTEM.md`. Não criar cores fora dos tokens.

## 8. Componentes reutilizáveis (mínimo)

`AppShell`, `Sidebar`, `TopBar`, `NotificationBell`, `SourceStatusIndicator`, `Card`, `KpiCard`, `DataTable`, `TokenCell` (imagem 20 px opcional + símbolo + nome + `Address`), `RiskBadge`, `SeverityBadge`, `FreshnessBadge`, `ScoreMeter`, `FactorList`, `Address`, `Timestamp`, `PriceText`, `PercentText`, `UsdText`, `Pagination`, `FilterBar`, `EmptyState`, `ErrorState`, `Skeleton`, `Modal`, `Drawer`, `Toast`, `PriceChart`, `ConfirmDialog`.

## 9. Cards

- Visão geral, 1ª linha de KPIs (grid de 4 em `lg`, 2 em `sm`, 1 em `xs`): Tokens monitorados (`tokens_tracked`, rodapé "N com dados atualizados"), Alertas abertos (`alerts_open_total`, rodapé com contagem crítica/alta), Riscos críticos (`critical_risk_tokens`), Oportunidades candidatas (`opportunity_candidates`).
- 2ª linha: Liquidez agregada e Volume 24h agregado (rodapé obrigatório: "soma apenas de tokens com dados atualizados"; `null` → "—"), Previsões (pendentes/avaliadas/inavaliáveis, link para `/predictions`), Fontes (lista compacta de `sources[]`).
- 3ª linha: duas listas lado a lado (empilhadas < 1024): "Maiores scores de oportunidade" e "Maiores scores de risco" (`top_*`); cada linha clicável → `link`. Mostrar sempre os dois scores, a liquidez e o frescor, para não confundir oportunidade com risco baixo.
- 4ª linha: "Alertas recentes" (`GET /alerts?status=open&page_size=8`).

## 10. Tabelas

- `DataTable` genérica: cabeçalho fixo (`position: sticky`), ordenação por clique no cabeçalho (`aria-sort`), linhas clicáveis (a linha inteira é um link real `<a>` ou tem `role="link"` + Enter), números alinhados à direita com `tabular-nums`.
- Overflow ≥ 768 px: container com `overflow-x: auto`, primeira coluna fixa.
- < 768 px: cada linha vira um **card empilhado** (sem rolagem horizontal), com os campos essenciais definidos por tabela.
- Explorador (colunas ≥ 1024): Token, Preço, Δ1h, Δ24h, Liquidez, Volume 24h, Idade do par, Risco (badge + número), Oportunidade (`ScoreMeter`), Alertas, Frescor. Card mobile: Token; preço + Δ24h; liquidez; risco + oportunidade; frescor.
- Alertas (colunas): Severidade, Título, Token, Tipo, Detectado, Ocorrências, Estado. Card mobile: severidade + título; token; detectado; estado.

## 11. Gráficos

- Página do token: `PriceChart` com seletor de intervalo `1h | 6h | 24h | 7d` (padrão 24h), candles verdes/vermelhos e leitura do agente ao selecionar um candle. O seletor usa candles de 1 min, 5 min, 15 min e 1 h, respectivamente; OHLC é agregado dos snapshots do sistema e das cotações rápidas realmente observadas. Não afirmar que os candles representam todos os negócios da DEX nem desenhar volume sem dados.
- Um clique num candle marca "Começamos aqui" e mostra o sinal vigente, motivos e estimativas empíricas já fornecidas pela API. Se não houver sinal/estimativa, explicar que os dados estão indisponíveis/insuficientes. Não gerar previsão nova na interface.
- A simulação recebe um valor em USD e um preço inicial escolhido no gráfico (ou preço atual via "Começar agora"). Mostrar quantidade calculada de tokens, valor atual, lucro/prejuízo e retorno percentual, sem enviar ordem e sem alterar a posição registrada. Informar que o resultado é bruto e não inclui taxas ou slippage.
- O preço rápido usa o feed existente da Jupiter a cada 10 s para Solana; para as outras redes ou quando o serviço estiver indisponível, usar somente o último snapshot do coletor e exibir sua idade. Não prometer atualização instantânea.
- Converter UTC para o fuso horário local apenas na exibição do eixo e do cursor; manter os timestamps originais para ordenar e calcular candles. Se `downsampled=true`, mostrar "histórico amostrado".
- Sem pontos: `EmptyState` "Sem histórico neste intervalo" (não desenhar eixo vazio).
- O gráfico, campo e painel lateral devem caber em 320 px de largura sem rolagem horizontal.

## 12. Notificações

- `NotificationBell`: consulta `GET /alerts?status=open&severity=high&severity=critical&page_size=10` a cada 60 s (pausa com a aba oculta). O badge mostra `total` (máx. "99+").
- Ao clicar, abre um popover (≥ 768) ou drawer (< 768) com a lista; cada item mostra severidade, título, token e tempo relativo, e **navega para `alert.link`** (token correto) e marca como visto localmente.
- "Novo" = `id` maior que o último id visto, guardado em `localStorage` por usuário (conveniência; tolerar falhas de acesso com try/catch).
- Link "Ver todos" → `/alerts?status=open`.
- Não há push nem e-mail (não implementados).

## 13. Detalhe do token (`/tokens/:chainId/:address`)

Ordem das seções (uma coluna < 1024; em `lg+`, principal 8/12 + lateral 4/12):
1. **Cabeçalho:** imagem, símbolo, nome, `Address` com copiar, rede, DEX + rótulos do par, link externo para `pair.url` (abre em nova aba, `rel="noopener noreferrer"`), `FreshnessBadge` + "observado há X". Botão "Parar de monitorar" (`DELETE .../track`, com `ConfirmDialog`).
2. **Mercado:** preço (`PriceText`), variações 5m/1h/6h/24h, liquidez, market cap, FDV, volume 5m/1h/6h/24h, compras/vendas 1h e 24h (rótulo: "transações", não "carteiras").
3. **Gráfico** (§11).
4. **Scores:** dois cards lado a lado: Risco (score, nível, confiança, cobertura, aviso se `insufficient_data`) e Oportunidade (score, confiança, texto fixo "Não é probabilidade de lucro"). `horizon_note` abaixo.
5. **Fatores** (`FactorList`): risco e oportunidade separados, ordenados por |pontos|; cada fator mostra rótulo, categoria, pontos (+/−), severidade, confiança e um expansor "Evidência" com `evidence` formatado em chave/valor (JSON bruto só como fallback).
6. **Verificações não realizadas:** lista `checks_not_performed` com o motivo. Texto fixo: "Ausência de alerta não significa segurança."
7. **Verificações técnicas:** `technical_checks`: autoridade de mint, de freeze, programa, extensões de risco; concentração (top-1/top-10, com `limitations` sempre visível). Para `unavailable`, mostrar o motivo (ex.: rate limit).
8. **Condições de invalidação:** lista `invalidation_conditions`.
9. **Cenários de saída:** `exit_estimate`. Se `available`: tabela posição → impacto % → valor estimado recebido; campo opcional para valores personalizados (até 10, separados por vírgula) que chama `/exit-estimate?positions=`; sempre mostrar `pool_model_note`, `unknown_costs`, "taxas não incluídas" e `disclaimer`. Se não estiver disponível: `reason`. Título: "Cenários genéricos de saída (nenhuma posição registrada)".
10. **Alertas do token:** `recent_alerts` (link "ver todos" → `/alerts?chain_id=&address=`).
11. **Previsões do token:** `recent_predictions` (§Previsões).
12. **Carteiras e social:** exibir `wallet_intelligence.note` e `social.note` + links. Sem gráficos nem números.

## 14. Filtros

- Explorador: busca (debounce 300 ms), rede (de `/meta.chains`), liquidez mín./máx., volume 24h mín., idade mín./máx. (horas), nível de risco (multi), frescor (multi), ordenação + direção, e "incluir não monitorados" (`tracked`). Estado **na URL** (query string) para permitir compartilhar e voltar. Botão "Limpar filtros".
- Alertas: estado (padrão `open`), severidade, categoria, tipo (de `/meta.alert_types`), token (`chain_id`+`address` vindos do link do token).
- Previsões: estado, alvo.
- "Adicionar token" (Explorador): modal com rede + endereço → `POST /tokens/track`; 404 → "Nenhum par encontrado para este endereço como token-base"; 502 → "Fonte indisponível, tente novamente"; sucesso → navegar ao detalhe.

## 15. Tratamento de erros

- `ErrorState` por seção (não derrubar a página inteira): mensagem do `error.message` + botão "Tentar novamente" (`refetch`).
- 401 → logout local + `/login?next=`. 422 → mostrar `details` junto aos campos. 429 no login → "Muitas tentativas. Aguarde alguns minutos." 5xx/rede → toast + `ErrorState`.
- `ErrorBoundary` de rota com botão "Recarregar".

## 16. Carregamento

- `Skeleton` com as mesmas dimensões do conteúdo final (sem salto de layout). Recarga em segundo plano (polling) **não** mostra skeleton: mostra um indicador discreto "atualizando…" no cabeçalho do card.
- Botões de ação: estado `loading` e bloqueio de duplo clique.

## 17. Estados vazios

- Explorador sem tokens: "Nenhum token monitorado ainda. O coletor adiciona tokens automaticamente quando está rodando; você também pode adicionar um endereço." + botão Adicionar.
- Filtros sem resultado: "Nenhum token corresponde aos filtros" + Limpar filtros.
- Alertas: "Nenhum alerta com esses filtros."
- Previsões: "Nenhuma previsão ainda. Previsões são criadas para tokens com liquidez ≥ US$ 5 mil."
- Métricas com `evaluated == 0`: "Ainda não há previsões avaliadas; métricas aparecem após o horizonte de 6 h."

## 18. Dados desatualizados

- `FreshnessBadge` em toda linha/cabeçalho de token. `delayed`: texto "Atrasado (há X min)" em `--stale`; `stale`: "Desatualizado (há X)" + valores de mercado com opacidade 0,7; `no_data`: "Sem dados".
- Nunca mostrar a cotação de um token `stale` em destaque sem o badge ao lado.
- O frescor relativo é recalculado no cliente a cada 30 s a partir de `observed_at` (não depender só de `age_seconds`).

## 19. Autenticação

- Formulário: usuário, senha (`type=password`, `autocomplete=current-password`), botão Entrar com loading. Sem "lembrar senha" próprio, sem "criar conta", sem "esqueci a senha".
- A senha só é enviada no `POST /auth/login`; nunca é guardada em estado global, `localStorage` ou logs.
- `/account`: troca de senha (atual, nova ≥ 8, confirmação) e "Sair".

## 20. Dispositivos móveis

- Testar em 360×800, 390×844, 768×1024, 1366×768, 1920×1080.
- Sem rolagem horizontal da página em nenhuma rota (exceção: dentro de containers de tabela ≥ 768 px).
- Áreas de toque ≥ 44×44 px; nada depende de hover (tooltips também acessíveis por foco/toque).
- Modais/drawers dentro da viewport (`100dvh`).

## 21. Acessibilidade básica

- Navegação completa por teclado; anel de foco visível (`:focus-visible`); "Pular para o conteúdo" como primeiro elemento focável.
- Landmarks: `nav`, `main`, `header`; um `h1` por página.
- Contraste AA. Cores sempre com texto/ícone.
- Gráficos com `aria-label` descritivo e resumo textual (último preço, variação no intervalo).
- `aria-live="polite"` para o contador de notificações e os toasts.

## 22. Desempenho

- Bundle inicial ≤ 250 KB gzip; páginas com code splitting (`React.lazy`); `lightweight-charts` carregado só no detalhe do token.
- TanStack Query: `staleTime` 30 s; `refetchInterval` 60 s (dashboard, explorador, alertas, sino), 30 s (detalhe do token), desligado em previsões/sistema (botão atualizar); `refetchIntervalInBackground: false`.
- Listas paginadas no servidor (`page_size` 25).

## 23. Critérios de aceitação

1. Login com `alisson`/`natan` funciona contra o backend real; senha errada mostra o erro; rota protegida sem sessão vai para `/login` e volta para `next` após o login.
2. Nenhum valor exibido vem de dados fixos no código; com o backend parado, as páginas mostram `ErrorState`, nunca números.
3. Clicar numa notificação ou num alerta abre `/tokens/{chain}/{address}` do token correto (mesmo endereço).
4. Filtros e ordenação do Explorador alteram a query da API e persistem na URL; voltar no navegador restaura os filtros.
5. Tokens `stale`/`delayed` exibem o badge; com `dexscreener` `down`, o banner global aparece.
6. `PATCH` de estado do alerta reflete a resposta da API (sem atualização otimista sem rollback).
7. Detalhe do token mostra fatores com evidência, verificações não realizadas, limitações de concentração e cenários de saída com disclaimer.
8. Previsões mostram "Não calibrado", `pending` sem acerto/erro, e as métricas com as notas.
9. Sem rolagem horizontal da página em 360 px; tabelas viram cards < 768 px; drawer de navegação funciona.
10. Teclado: é possível logar, navegar, abrir um token e mudar o estado de um alerta sem mouse.
11. `npm run build`, `npm run typecheck`, `npm run lint` e `npm test` passam.

## 24. Executar e testar

```bash
# backend (terminal 1) — ver README
cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# coletor (terminal 2, opcional mas necessário para dados frescos)
cd backend && .venv\Scripts\python.exe -m app.worker
# frontend (terminal 3)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Produção: `npm run build` gera `frontend/dist/`, que a API serve na mesma origem (http://127.0.0.1:8000/). Sem hospedagem separada para o frontend e sem serviços pagos (decisão D-013, custo zero).

Scripts esperados em `frontend/package.json`: `dev`, `build`, `preview`, `typecheck` (`tsc --noEmit`), `lint`, `test` (Vitest), `test:e2e` (Playwright, exige backend rodando), `gen:api` (`openapi-typescript ../docs/openapi.json -o src/api/schema.d.ts`).

## 25. Convenções do repositório

- Frontend em `frontend/`; nada fora dessa pasta, exceto `CONTRACT_ISSUES.md` e `frontend/CODEX_LOG.md`.
- TypeScript estrito; sem `any` em dados da API (usar os tipos gerados).
- Estrutura: `src/api` (cliente + tipos gerados + hooks de query), `src/components`, `src/pages`, `src/styles`, `src/lib` (formatadores), `src/test`.
- Formatação (`src/lib/format.ts`), locale `pt-BR`:
  - USD: `< 1000` → `US$ 999,99`; compacto acima (`US$ 1,18 mi`, `US$ 2,3 bi`).
  - Preço: ≥ 1 → 2–4 casas; < 1 → 4 dígitos significativos; < 0,0001 → notação com zeros subscritos (`0,0₅3175`), com o valor completo no `title`.
  - Percentual de variação: sinal explícito, 2 casas (`+4,23%`), cor positiva/negativa.
  - Frações 0–1 → percentual (`0.65` → `65%`).
  - Datas: relativa + absoluta local (`28/10/2026 19:57:52`).
- Commits pequenos e descritivos; não commitar `node_modules`, `dist`, `.env`.
