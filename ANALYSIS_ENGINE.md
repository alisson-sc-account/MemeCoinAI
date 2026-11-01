# Motor analítico

Versão atual: `ENGINE_VERSION = risk-1+opp-1+f-1`, alertas `alerts-1`, previsão `heuristic-logit` v1, slippage `slip-1`, verificações Solana `sol-1`, normalizador `dexs-1`.

**Status de validação:** regras implementadas e cobertas por testes unitários/integração; **nenhum peso ou probabilidade foi validado historicamente**. Nada aqui é recomendação de investimento.

## 1. Features (`engine/features.py`, `f-1`)

Calculadas com `as_of`: somente snapshots com `received_at ≤ as_of` (proteção contra vazamento, testada em `test_features_ignore_future_snapshots`).

| Feature | Definição |
|---|---|
| `volume_accel_h1` | volume_h1 / (volume_h6 / 6) |
| `volume_accel_m5` | volume_m5 / (volume_h1 / 12) |
| `txn_accel_h1` | txns_h1 / (txns_h6 / 6) |
| `buy_ratio_h1` | buys_h1 / (buys_h1 + sells_h1) — **contagem de transações**, não de carteiras únicas |
| `avg_trade_usd_h1` | volume_h1 / txns_h1 |
| `liquidity_to_mcap` | liquidity_usd / market_cap (ou FDV) |
| `volume_h24_to_liquidity` | volume_h24 / liquidity_usd |
| `liquidity_change_vs_max_1h` | (liq atual − máx. da última hora) / máx. — histórico **próprio** |
| `liquidity_trend_1h` | (liq atual − liq mais antiga da última hora) / mais antiga |
| `pair_age_hours`, `history_points`, `data_age_seconds` | idade e qualidade dos dados |

Valores `None` quando o denominador é ausente/zero: nunca imputados.

## 2. Score de risco (`risk-1`)

Soma de pontos, limitada a 100. Nível: `<25 low`, `<50 moderate`, `<75 high`, `≥75 critical`. Cobertura = verificações realizadas / 4 (`market_data`, `liquidity_history`, `mint_authorities`, `holder_concentration`); `risk_confidence = 0,3 + 0,7·cobertura`; `insufficient_data` se cobertura < 0,5.

| ID | Categoria | Condição | Pontos | Confiança |
|---|---|---|---|---|
| D0_no_market_data | data | sem snapshot | 40 | 1,0 |
| D1_liquidity_missing | data | liquidez ausente | 20 | 1,0 |
| L1_liquidity_very_low / low / moderate | liquidity | < 5k / < 20k / < 50k USD | 30 / 18 / 8 | 0,9 |
| L3_thin_vs_mcap | liquidity | liq/mcap < 2% | 10 | 0,7 |
| L2_liquidity_drop / _severe | liquidity | queda ≥ 30% / ≥ 60% vs máx. 1h | 25 / 40 | 0,8 / 0,85 |
| A1_sell_pressure | activity | sells_h1 ≥ 2×buys_h1 e txns_h1 ≥ 30 | 12 | 0,6 |
| A2_few_large_trades | activity | média > US$ 5k, txns_h1 < 20, vol_h1 > 20k | 10 | 0,5 |
| A3_volume_vs_liquidity | activity | vol24h > 50× liquidez (possível wash trading) | 10 | 0,4 |
| A4_price_crash | market | variação 1h ≤ −40% | 15 | 0,9 |
| D2_very_young / age_unknown | data | par < 1h / idade desconhecida | 10 / 5 | 1,0 |
| T1_mint_authority | technical | mintAuthority ≠ null (Solana) | 35 | 0,95 |
| T2_freeze_authority | technical | freezeAuthority ≠ null | 30 | 0,95 |
| T3_token2022_extensions | technical | extensões de risco (permanentDelegate, transferHook com programa, nonTransferable, pausableConfig, defaultAccountState=frozen, transferFeeConfig, mintCloseAuthority) | 25 cada, máx. 40 | 0,9 |
| D3_technical_unchecked | data | verificação técnica não realizada/indisponível/rede não suportada | 15 | 1,0 |
| C1_concentration_high / _extreme | concentration | top-10 **contas** > 50% / > 80% do supply | 20 / 30 | 0,4 |
| D4_concentration_unchecked | data | concentração não verificada | 5 | 1,0 |

Limitação da concentração: são contas de token (incluem cofres de pool, queima, contratos), não proprietários. Por isso a confiança é baixa.

## 3. Score de oportunidade (`opp-1`)

Não é probabilidade de lucro. Fatores positivos (máx. 100):

| ID | Pontos |
|---|---|
| O1_volume_accel | 20 × clip((accel_h1 − 1)/2) |
| O2_volume_accel_5m | 10 × clip((accel_m5 − 1)/3) |
| O3_buy_pressure | 15 × clip((buy_ratio − 0,5)/0,25) |
| O4_txn_accel | 15 × clip((txn_accel − 1)/2) |
| O5_momentum | 15 × clip(Δ1h/30) se 0 < Δ1h ≤ 100%; Δ1h > 200% → `O5_exhaustion` (0 pts) |
| O6_depth | 15 se liq ≥ 50k; 8 se ≥ 20k |
| O7_liquidity_growth | 10 se liquidez +10% em 1h |

Ajustes: `P1_risk_penalty` = −0,5 × max(0, risco − 25); `P2_shallow_pool_cap`: liquidez < 10k → máx. 30; `P3_insufficient_data_cap`: máx. 40. Cada análise traz `invalidation_conditions` (ex.: "liquidez cair abaixo de US$ X").

## 4. Alertas (`alerts-1`)

| Tipo | Categoria | Severidade | Regra |
|---|---|---|---|
| liquidity_drop | risk | high / critical | L2 |
| mint_authority_active / freeze_authority_active | risk | high | T1 / T2 |
| risky_token_extensions | risk | high | T3 |
| permission_change | risk | high | autoridades mudaram entre duas verificações válidas |
| holder_concentration | risk | medium / high | C1 |
| sell_pressure | risk | medium | A1 |
| risk_high | risk | high (≥50) / critical (≥75) | evidência inclui `data_points` (parte do score que vem de falta de dados) |
| insufficient_data | risk | low | cobertura < 50% **após 1 h** de monitoramento |
| volume_spike | opportunity | info | accel_h1 ≥ 3 e liq ≥ 20k |
| opportunity_candidate | opportunity | medium / high (≥75) | opp ≥ 60, risco < 50, dados suficientes |
| source_unavailable | system | high | ≥ 3 falhas consecutivas da fonte |

Deduplicação: ver DECISIONS D-009.

## 5. Previsões (`heuristic-logit` v1)

| Alvo | Sucesso | Horizonte |
|---|---|---|
| `up_20pct_6h` | máx. preço observado em (t, t+6h] ≥ ref × 1,20 | 6 h |
| `down_30pct_6h` | mín. preço observado em (t, t+6h] ≤ ref × 0,70 | 6 h |

- `p = σ(a + b·opp/100 + c·risco/100)`; up: a=−2,2, b=2,5, c=−0,8; down: a=−2,0, b=0, c=2,4. **A priori, não calibrado.**
- Criada só com liquidez ≥ US$ 5 mil e preço disponível; no máximo 1 por alvo/token a cada 3 h.
- Baseline: taxa-base `(acertos+1)/(n+2)` das previsões avaliadas **antes** do instante; `None` até 20 amostras.
- Avaliação: só depois de `resolve_at`; exige ≥ 3 observações e a última a ≤ 30 min do fim; senão `unevaluable` (contabilizada nas métricas, nunca descartada → reduz viés de sobrevivência).
- Limitações: preço amostrado a cada ~60 s (picos entre coletas são perdidos); alvo bruto, sem custos; não há retorno líquido hipotético ainda.
- Métricas (`GET /predictions/metrics`): Brier do modelo vs. baseline (no mesmo subconjunto), precisão/recall/falsos positivos em 0,3/0,5/0,7, curva de calibração em 10 faixas, desempenho por faixa de liquidez, `sufficient_sample` (≥ 100).

## 6. Saída/slippage (`slip-1`)

Só x*y=k: impacto = Δx/(x+Δx), preço médio = spot × (1 − impacto). Sem taxas. Cenários padrão: US$ 100, 500, 1k, 5k, 10k, 50k. Sem posição registrada = **cenários genéricos** (registro de posição não implementado).

## 9. Sinais acionáveis (`sig-1`) — `engine/signals.py`

Avaliados nesta ordem (o primeiro que valer decide):

| Ação | Força | Regra |
|---|---|---|
| AGUARDAR | — | dados não frescos (> 180 s): nunca comprar nem vender sobre cotação velha |
| VENDER | forte | `L2_liquidity_drop_severe` ou `A4_price_crash` ou **risco observado** ≥ 75 (soma dos fatores fora da categoria `data`) |
| VENDER | moderado | `L2_liquidity_drop`, ou `A1_sell_pressure` com variação 1 h ≤ −10% |
| EVITAR | moderado | risco ≥ 60 ou autoridade de mint/freeze ou extensões Token-2022 de risco |
| COMPRAR | forte | sem `insufficient_data`, liquidez ≥ 20 mil, risco < 50, oportunidade ≥ 60; rebaixado a moderado se o histórico de 1 h de casos parecidos tiver mediana ≤ 0 e P(máx ≥ +10%) < 30% |
| COMPRAR | moderado | liquidez ≥ 10 mil, risco < 50, oportunidade ≥ 45 |
| AGUARDAR | — | demais casos (motivos listados) |

Regressões cobertas por teste: sinal de venda sobre dado de 2 h atrás; "vender" causado só por falta de verificação.
Alertas: `buy_signal`/`sell_signal`. O alerta central da interface abre só para sinais **novos** de compra forte ou de venda.

## 10. Estimativas por horizonte (`out-1`) — `engine/outcomes.py`

- Rótulos: para cada análise cujo horizonte (15 min, 1 h, 6 h) **já terminou**, grava o retorno máximo, mínimo e final observado em (t, t+h]. Exige coleta sem lacunas > 5 min na janela (pelas execuções do coletor); sem snapshot novo com coleta ativa = preço inalterado. Sem cobertura → `unevaluable` (não descartado).
- Estimativa: análises dos últimos 7 dias, com rótulo conhecido antes de `as_of`, na mesma faixa de oportunidade (<20, 20–40, 40–60, ≥60) e de risco (<50, ≥50). ≥ 30 casos → `similar`; senão todos os casos (`general`); senão `insufficient`.
- Primeiro resultado real (2026-10-28): 135 rótulos de 15 min; mediana −0,75%, P(subir ≥ 20%) = 11,9%, P(cair ≥ 20%) = 17%. 1 h ainda sem casos válidos (lacuna de coleta).
- Limitações: amostras correlacionadas (mesmo token em instantes próximos); preço amostrado a cada coleta; retornos brutos. Previsões de 2 min não são oferecidas: a fonte gratuita tem atraso de até ~60 s.

## 11. Sugestão de posição (`advice-1`)

Com posição registrada: venda forte → vender 100%; venda moderada → 50%; evitar → 50%; lucro ≥ +100% → realizar 50%; lucro ≥ +50% → 25%; compra forte sem motivo de venda → pode aumentar até 25% do valor planejado. Aviso de slippage quando a venda teria impacto > 3% (pools x*y=k). Sem posição: compra forte → entrar com 50% do valor planejado; moderada → 25%. Sempre com aviso de que não é garantia.

## 12. Disparo em andamento (`burst-1`) — `engine/burst.py`

**Detecção, não previsão.** Dispara quando TODAS valem na janela de 5 min: liquidez ≥ US$ 5 mil; volume dos últimos 5 min ≥ 4x o ritmo da última hora; preço +2% ou mais em 5 min; ≥ 8 transações; compras ≥ 65% das transações; alta de 1 h ≤ 300% (evita entrada tardia). Força `extreme` com 10x e +8%.

Alerta `pump_burst` (categoria oportunidade, severidade alta/crítica), auto-resolvido quando a condição some — assim um disparo novo gera alerta novo. A evidência traz `pattern_stats`: o que aconteceu nos 15 min seguintes a disparos iguais já medidos (P(+10%), P(+20%), pico típico), usando só rótulos fechados antes do instante.

Limitações: a fonte atualiza a cada ~30 s e atrasa até ~60 s, então parte do movimento já passou quando o alerta sai; muitos disparos se desfazem.

## 13. Universo monitorado

Descoberta por 4 origens gratuitas: perfis recentes, impulsionados (latest e top) e **buscas rotacionadas** (8 termos por ciclo, de uma lista de 30; 30 pares por busca). A fonte **não tem** endpoint que liste todos os tokens — o universo é o que essas origens alcançam. Teto `MAX_TRACKED_TOKENS` = 600 (20 requisições por ciclo de 30 s, ~40/min contra o limite de 300/min).

`prune_inactive` deixa de monitorar tokens com mais de 3 h sem par, ou com liquidez < US$ 1,5 mil e volume 24 h < US$ 1 mil. Nunca remove tokens da watchlist nem com posição registrada; o histórico é mantido. As verificações de contrato (RPC gratuito) são priorizadas pela oportunidade recente, para que candidatos a compra sejam verificados primeiro.

## 7. Condições de invalidação gerais

- Mudanças de regra exigem nova versão (`risk-2`...) e registro em DECISIONS.
- Recalibrar pesos somente com divisão temporal (treino < validação < teste) e sem olhar o teste final.
- Não retreinar automaticamente.

## 8. Próximos passos do motor

1. Acumular ≥ 100 previsões avaliadas por alvo e comparar com a baseline.
2. Retorno líquido hipotético com slippage (pools x*y=k) e custo fixo estimado.
3. Classificar contas do top-holders (dono = pool/queima) com RPC dedicado.
4. Compradores únicos / carteiras: requer indexador (Fase 7).
