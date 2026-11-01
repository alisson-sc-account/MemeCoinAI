# Contrato da API — v1

**Status:** todos os endpoints abaixo estão **implementados e cobertos por testes** (`backend/tests/test_flow.py`), salvo indicação "PLANEJADO".

Fontes da verdade, em ordem:
1. `docs/openapi.json` — gerado do código (`python -m app.cli openapi`). Use-o para gerar tipos TypeScript.
2. `backend/app/schemas.py` — definições Pydantic.
3. `docs/api-examples/*.json` — **respostas reais capturadas** da API em 2026-10-28 com dados reais do DEX Screener e do RPC Solana. Servem como referência de formato e como fixtures **somente em testes**; nunca como dados exibidos na interface.

Se este documento divergir do OpenAPI, o OpenAPI vale, e a divergência deve ser registrada em `CONTRACT_ISSUES.md`.

## Convenções

- Base: `/api/v1`. Em desenvolvimento, o frontend usa o proxy do Vite (`/api` → `http://127.0.0.1:8000`), portanto **mesma origem**.
- Autenticação: cookie `mcai_session` (httpOnly, SameSite=Lax), definido pelo login. O frontend **não lê nem armazena** o token. Todas as requisições devem usar `credentials: "include"` (ou `same-origin` via proxy).
- Todas as rotas exigem sessão, exceto `GET /health` e `POST /auth/login`.
- Datas: ISO 8601 em UTC com `Z` (ex.: `2026-10-28T22:57:52.389466Z`). Exiba no fuso local.
- Números: `float` em USD; percentuais de variação de preço (`price_change_*`) já estão **em pontos percentuais** (4.23 = +4,23%). Frações (`buy_ratio_h1`, `top10_share`, `price_impact`, `threshold`, `observed_*_return`, `probability`) vão de 0 a 1.
- `null` significa **dado indisponível**. Nunca exiba `null` como 0.
- Paginação: `?page=1&page_size=25` (máx. 100). Resposta `{ items, total, page, page_size }`.
- Listas em query string: parâmetro repetido (`?severity=high&severity=critical`).
- Versionamento: prefixo `/v1`. Mudança incompatível → `/v2`. Campos novos podem ser adicionados sem aviso; o frontend deve ignorar campos desconhecidos.

### Formato de erro

```json
{ "error": { "code": "invalid_credentials", "message": "Usuário ou senha inválidos", "details": null } }
```

| HTTP | `code` | Quando |
|---|---|---|
| 401 | `unauthenticated` | sem sessão / sessão expirada ou revogada → redirecionar para `/login` |
| 401 | `invalid_credentials` | login inválido |
| 400 | `invalid_current_password` | troca de senha |
| 404 | `token_not_found`, `alert_not_found`, `not_found_on_source`, `no_pair` | |
| 422 | `validation_error` (com `details[].loc/msg`), `invalid_sort`, `invalid_positions`, `invalid_target`, `chain_required` | |
| 429 | `too_many_attempts` | 5 falhas de login em 15 min |
| 502 | `source_error` | fonte externa falhou ao adicionar token |

## Estados de dados (usar em toda a UI)

`Freshness` aparece em itens de token e na estimativa de saída:

```json
{ "observed_at": "...Z" | null, "age_seconds": 322.3 | null,
  "status": "fresh" | "delayed" | "stale" | "no_data",
  "source": "dexscreener", "source_status": "ok" | "degraded" | "down" | "unknown" }
```

`fresh` ≤ 180 s, `delayed` ≤ 900 s, `stale` acima disso, `no_data` sem observação. Com fonte `down`, nada é `fresh`. Os limites estão em `GET /meta`.

---

## Autenticação

### `POST /auth/login`
Body `{ "username": string, "password": string }` → 200 `LoginResponse { user: UserOut, expires_at }` e define o cookie. Erros 401, 429, 422. Exemplo: `auth_login.json`.

### `POST /auth/logout` → 204 (revoga a sessão e apaga o cookie).
### `GET /auth/me` → `UserOut { id, username, must_change_password }`.
### `POST /auth/change-password`
Body `{ current_password, new_password (mín. 8) }` → 204; revoga as outras sessões do usuário. Erro 400 `invalid_current_password`.

## Sistema

### `GET /health` (público)
`{ status: "ok"|"degraded", database: "ok"|"error", version, time }`.

### `GET /system/sources`
`{ sources: SourceStatusOut[], recent_runs: CollectorRunOut[] (30 mais recentes) }`.
`SourceStatusOut { source, status, last_success_at, last_error_at, last_error, consecutive_failures, latency_ms_avg, rate_limited_recent }`. Fontes atuais: `dexscreener`, `solana_rpc`.

### `GET /meta`
Enumerações para filtros: `chains`, `alert_types` (tipo → categoria), `severities`, `risk_levels`, `token_sort_fields`, `prediction_targets` (alvo → descrição), `engine_version`, `freshness_thresholds_seconds`.

### `GET /dashboard/summary`
`DashboardSummary`: `generated_at`, `tokens_tracked`, `tokens_with_fresh_data`, `alerts_open_total`, `alerts_open_by_severity {info,low,medium,high,critical}` (abertos + reconhecidos), `critical_risk_tokens`, `opportunity_candidates`, `aggregate_liquidity_usd` e `aggregate_volume_h24_usd` (**apenas tokens `fresh`**; `null` se nenhum), `predictions {pending,evaluated,unevaluable}`, `last_refresh_at`, `sources[]`, `top_opportunities[]` e `top_risks[]` (5 cada; `RankedToken { token, risk_score, risk_level, opportunity_score, liquidity_usd, freshness_status, link }`).

## Tokens

### `GET /tokens`
| Parâmetro | Tipo | Padrão |
|---|---|---|
| `q` | ticker, nome (contém, sem distinção de maiúsculas) ou endereço exato | — |
| `chain_id` | string | — |
| `tracked` | bool | `true` |
| `min_liquidity`, `max_liquidity`, `min_volume_h24` | número ≥ 0 | — |
| `min_age_hours`, `max_age_hours` | idade do par | — |
| `risk_level` | repetível: `low`, `moderate`, `high`, `critical` | — |
| `freshness_status` | repetível | — |
| `sort` | `opportunity_score`, `risk_score`, `liquidity_usd`, `volume_h24`, `volume_h1`, `price_change_h1`, `price_change_h24`, `market_cap`, `pair_age_hours`, `first_seen_at`, `observed_at` | `opportunity_score` |
| `order` | `asc` / `desc` | `desc` |
| `page`, `page_size` | | 1, 25 |

Itens sem valor no campo de ordenação vêm **sempre ao final**. Filtros numéricos excluem itens com valor `null`.

`TokenListItem`: `token {chain_id, address, symbol, name, image_url}`, `discovered_via` (`watchlist` | `dexscreener_profiles` | `dexscreener_boosts`), `first_seen_at`, `is_tracked`, `pair` (`PairOut` | null), `pair_age_hours`, `market` (`MarketOut` | null), `freshness`, `scores` (`ScoresOut` | null), `open_alerts`.

`ScoresOut { computed_at, engine_version, risk_score 0–100, risk_level, risk_confidence 0–1, insufficient_data, opportunity_score 0–100, opportunity_confidence 0–1 }`.

### `POST /tokens/track`
Body `{ chain_id, address }` → 201 `TokenListItem`. Consulta a fonte real antes de inserir. Erros 404 `not_found_on_source`, 502 `source_error`. As verificações técnicas rodam depois, no worker.

### `DELETE /tokens/{chain_id}/{address}/track` → 204 (para de monitorar; o histórico é mantido).

### `GET /tokens/{chain_id}/{address}`
`TokenDetail` = `TokenListItem` + :
- `links[]` (declarados na fonte, não verificados), `pairs[]`
- `analysis` (`AnalysisOut` | null): scores + `risk_factors[]`, `opportunity_factors[]` (`FactorOut { id, category, label, points, severity, confidence, evidence }`; pontos negativos = penalidades), `checks_not_performed[] { check, reason }`, `data_quality`, `invalidation_conditions[]`, `features`, `horizon_note`
- `technical_checks { supported, note, mint: CheckOut|null, holders: CheckOut|null }`; `CheckOut.status`: `ok` | `flagged` | `unavailable` | `error` | `not_applicable`
- `recent_alerts[]` (20), `recent_predictions[]` (10)
- `exit_estimate` (`ExitEstimateOut` | null)
- `wallet_intelligence { status: "not_implemented", note }` — **PLANEJADO**
- `social { status: "links_only", note, links }`

Exemplo: `token_detail_bonk.json`.

### `GET /tokens/{chain_id}/{address}/history?range=1h|6h|24h|7d&max_points=500`
`{ token, pair_address, range, points: [{ t, price_usd, liquidity_usd, market_cap, volume_h1, buys_h1, sells_h1 }], downsampled, source, note }`. Os pontos são snapshots coletados por este sistema (cerca de 1/min enquanto o worker roda), **não candles**. Pode haver lacunas, que não devem ser interpoladas.

### `GET /tokens/{chain_id}/{address}/exit-estimate?positions=100,500`
`ExitEstimateOut { available, reason, method_version, pool_model, pool_model_note, spot_price_usd, liquidity_usd, fees_included:false, unknown_costs[], scenarios[ { position_usd, tokens_sold, price_impact, estimated_avg_price_usd, estimated_received_usd, share_of_pool_base } ], freshness, disclaimer }`. Com `available=false`, mostre `reason`. Exemplos: `token_exit_estimate_cp.json`, `token_exit_estimate_unavailable.json`.

## Alertas

### `GET /alerts`
Filtros repetíveis: `status` (`open`, `acknowledged`, `resolved`), `severity`, `category` (`risk`, `opportunity`, `system`), `alert_type`; também `chain_id` + `address`, `since` (ISO), `page`, `page_size`. Ordenação fixa: `detected_at` desc. Sem filtro de status, retorna todos.

`AlertOut { id, alert_type, category, severity, status, title, reason, evidence, confidence, rule_id, rule_version, event_at, detected_at, last_occurrence_at, occurrences, status_changed_at, token: TokenRef|null, pair_address, link }`. `link` é a rota do frontend (`/tokens/{chain}/{address}` ou `/system` para alertas de sistema).

### `GET /alerts/{id}` → `AlertOut`.
### `PATCH /alerts/{id}` body `{ status: "open"|"acknowledged"|"resolved" }` → `AlertOut`.

## Previsões

### `GET /predictions`
Filtros: `status` (repetível: `pending`, `evaluated`, `unevaluable`), `target`, `chain_id` + `address`, paginação. `PredictionOut { id, token, target, target_description, horizon_seconds, threshold, created_at, resolve_at, probability, calibrated, baseline_probability, model_id, model_version, reference_price_usd, status, outcome (null enquanto pendente/inavaliável), observed_max_return, observed_min_return, observed_end_return, observations_count, outcome_detail, evaluated_at }`.

### `GET /predictions/metrics?target=`
Lista de `PredictionMetricsOut` por alvo: contagens, `observed_rate`, `brier_model`, `brier_baseline`, `brier_model_where_baseline`, `thresholds[]` (precisão/recall/FP), `calibration_bins[]`, `by_liquidity[]`, `sufficient_sample`, `notes[]`.

## Sinais, estimativas e posição (implementado em 2026-10-28, sessão 3)

### `GET /signals`
Filtros: `action` (repetível: `buy`, `sell`, `avoid`, `hold`), `strength` (repetível: `strong`, `moderate`, `none`), `status` (`active`, padrão, ou `all`), `after_id` (somente id maior; usado pelo alerta global), paginação. Ordem: id desc.
`SignalOut { id, token, action, strength, status, headline, reasons[], risk_score, risk_level, opportunity_score, reference_price_usd, estimates: HorizonEstimateOut[], created_at, last_confirmed_at, rules_version, link }`. Um sinal ativo por token; um sinal novo (id novo) só surge quando a ação muda ou a força aumenta.

### `GET /signals/{id}` → `SignalOut`. `GET /signals/performance` → acerto histórico por ação, força e horizonte (`SignalPerformanceOut { action, strength, horizon, n, hit_rate, big_move_rate, median_end_return, definition }`).

### `HorizonEstimateOut`
`{ horizon: "15m"|"1h"|"6h", horizon_seconds, basis: "similar"|"general"|"insufficient", n, needed, end_p25, end_median, end_p75, max_median, p_up_10, p_up_20, p_up_50, p_down_20, p_end_positive, method_version }`. Retornos e probabilidades são **frações** (0.12 = +12%). Com `basis = insufficient`, os campos numéricos são `null` e `needed` informa quantos casos faltam.

### Posições (por usuário; informadas manualmente)
- `GET /positions` → `PositionOut[] { token, quantity, entry_price_usd, current_price_usd, value_usd, pnl, updated_at, link }`.
- `PUT /positions/{chain_id}/{address}` body `{ quantity > 0, entry_price_usd?: > 0 }` → `PositionOut`.
- `DELETE /positions/{chain_id}/{address}` → 204.

### Campos novos em `GET /tokens/{chain}/{address}`
`signal` (`SignalOut` | null), `estimates` (`HorizonEstimateOut[]`), `position` (`PositionOut` | null), `advice` (`AdviceOut { version, has_position, action: buy|sell|hold|none, summary, reasons[], sell_percent, keep_percent, buy_percent_of_plan, position_value_usd, pnl, slippage_note, disclaimer }`).

Novos tipos de alerta: `buy_signal` (opportunity) e `sell_signal` (risk).

### `GET /opportunities` (aba "Compre agora", `rank-1`)
Filtros: `tier` (repetível: `priority_buy`, `possible_buy`, `watch`, `avoid`; padrão todos), `sort` (`tier` padrão, `score`, `score_change`, `liquidity_usd`, `volume_h24`, `price_change_h1`, `risk_score`), `min_liquidity`, `max_age_hours`, `page`, `page_size` (até 100). Valores ausentes ficam no fim da ordenação.
Resposta `OpportunityPage { items, total, page, page_size, counts {tier: n}, generated_at, ranking_version, disclaimer }`. Cada item: `token`, `link`, `tier`, `tier_label`, `decision_quality` (`ok` | `partial` | `no_reliable_signal`), `decision_quality_reason`, `score`, `score_previous`, `score_change`, `confidence`, `coverage`, `risk_score`, `risk_level`, `critical_blocks[]`, `reasons_for[]`, `reasons_against[]`, `missing_data[]`, `price_usd`, `price_change_h1`, `price_change_h24`, `liquidity_usd`, `volume_h24`, `pair_age_hours`, `dex_id`, `freshness`, `signal_headline`, `signal_since`, `allocation`, `computed_at`, `ranking_version`. Score, confiança e cobertura são campos separados; `no_reliable_signal` só ocorre com preço/liquidez ausentes ou cotação velha.

### `GET /system/registry`
36 fontes do fluxograma: `{ key, name, role, access_class: A|B|C|D, access_label, enabled, integration, needs_key, verified_on, verification, limits, fallback }`.

### `GET /health` (público) — campo novo
`worker { status: running|stopped|unknown, last_cycle_at, age_seconds, expected_interval_seconds }`, derivado da última coleta concluída. `status` geral fica `degraded` quando o worker não está rodando.

### Erro 503 `database_busy`
Quando o SQLite está ocupado por uma escrita do coletor, a API responde 503 com `Retry-After: 2` em vez de 500.

### `GET /accuracy` (aba Acertos, `acc-1`)
Parâmetros: `horizon` (`15m`, `1h` padrão, `6h`), `action` (`buy`, `sell`), `result` (`hit`, `miss`, `pending`, `unevaluable`), paginação. Resposta `AccuracyPage { horizon, summary[horizonte][buy|sell|all] = {hits, misses, evaluated, pending, unevaluable, hit_rate}, items[], total, rules_version, definition }`. Item: `signal_id, token, link, action, prediction ("Deve subir"/"Deve descer"), strength, headline, created_at, reference_price_usd, results[horizonte] = {status, resolves_at, end_return, max_return, min_return, end_price_usd}`.

### `GET /tokens/{chain_id}/{address}/exit-plan` (`exit-1`)
`ExitPlanOut { urgency: sell_now|reduce|hold|no_data, headline, sell_percent_now, keep_percent, reference_price_usd, reference_kind, current_price_usd, change_from_reference, take_profits[{label, price_usd, change_from_reference, change_from_now, sell_percent, reached}], stop{...}, triggers[], reasons[], has_position, freshness, live, generated_at, disclaimer }`. Leve, para atualizar a cada 10 s.
- Cada consulta mantém o token na atualização rápida (`app.live`, D-016) por mais 60 s.
- `live: LiveFeedOut { status: live|waiting|unavailable|off, source, interval_seconds, observed_at, age_seconds, price_usd, liquidity_usd, note, rules_version }`. Com `live`, `current_price_usd` e `freshness` vêm da cotação rápida (`freshness.source = "jupiter_price"`); nos outros estados, do coletor.
- `reasons` pode trazer alertas ao vivo ("Liquidez retirada agora… padrão de golpe", "Preço despencou…"), que forçam `urgency = sell_now`.
- `GET /health` inclui `live: LiveServiceOut { status: running|stopped|unknown, last_tick_at, age_seconds, interval_seconds, watched, quoted, last_error, source }`.

### Favoritados (`fav-1`, por usuário)
- `POST /favorites` `{ chain_id, address, signal_id? }` → 201 `FavoriteOut`; sem `signal_id`, usa o sinal ativo; repetir devolve o registro original; 404 para token ou sinal desconhecido.
- `GET /favorites` → `FavoritePage { items, summary, generated_at, rules_version, disclaimer }`. Ganhos congelados no clique: frações (0,5 = +50%), brutos, e nulos sem dado.
- `GET /favorites/report` → `{ text, count, generated_at }`: resumo legível + JSON completo.
- `DELETE /favorites/{id}` → 204; 404 se for de outro usuário.

### Saldo para simulação (por usuário)
- `GET /auth/settings` → `AccountSettings { balance_amount: number|null, balance_currency: "BRL"|"USD", max_trade_percent: 0–100 (padrão 10) }`.
- `PUT /auth/settings` (mesmo corpo) → `AccountSettings`. 422 para saldo negativo ou percentual fora de (0, 100].
- `SignalOut.allocation` (`AllocationOut { percent_of_balance, amount, currency, max_trade_percent, rule }` | null) e `AdviceOut.buy_percent_of_balance`, `buy_amount`, `currency`: calculados para o usuário da sessão, só em sinais de compra e com saldo informado.

## PLANEJADO (não implementado — não criar telas funcionais para isso)

- Inteligência de carteiras (`/wallets/...`).
- Métricas sociais.
- Notificações push/e-mail.
