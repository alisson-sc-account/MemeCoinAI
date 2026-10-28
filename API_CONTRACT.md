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

## PLANEJADO (não implementado — não criar telas funcionais para isso)

- Registro de posição do usuário e recomendação personalizada de saída.
- Inteligência de carteiras (`/wallets/...`).
- Métricas sociais.
- Notificações push/e-mail.
