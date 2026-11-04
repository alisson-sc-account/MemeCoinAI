# Observabilidade e carteiras (modo observação)

## Medições (`app/metrics.py`)
- Cada processo (worker, live, tape, safety, board, api-<pid>) guarda as últimas 500 medições por nome e grava
  um resumo a cada ~10 s em `backend/data/metrics/<processo>.json` (fora do Git).
- Leitura: `GET /api/v1/system/metrics` (exige login). Percentis nulos = amostra insuficiente
  (p50/p90: 20+, p95: 100+, p99: 300+).
- Nomes principais: `job.<agente>`, `queue.wait.hot|cold`, `queue.*_size|*_oldest_s|coalesced_total`,
  `cold.yield_wait`, `pipeline.analyze`, `pipeline.received_to_decision`, `signal.received_to_decision`,
  `notify.decision_to_send.signal|alert`, `api.<MÉTODO> <rota>`, `http.<host>` (+ `.429`, `.timeout`, `.error`),
  `db.locked`, `live.full_tick`, `live.focus_tick`, `live.focused`, `board.build|rows|items|dashboard|write`,
  `tape.reconnects`, `tape.trades_period`, `tape.duplicates_total`.

## Correlação
Sem coluna nova: a cadeia já gravada é a correlação. Logs usam `corr=s<snapshot>/a<análise>/g<sinal>`
(motor) e `corr=a<análise>/s<sinal>` ou `/a<alerta>` (aviso no celular). `snapshot.received_at` -> decisão ->
envio dá o atraso de cada etapa.

## Tela aberta
`GET /tokens/{c}/{a}/exit-plan` agora só lê. A tela chama `POST /tokens/{c}/{a}/watch` a cada 2 s, só com a
aba visível (`useLiveWatch` em `frontend/src/features/sellplan.tsx`). Gravação continua limitada a 1 a cada 2 s
por moeda. `LiveWatch` segue global por moeda (sistema de uso pessoal, 2 contas): a mesma moeda aberta em várias
abas gera uma única coleta.

## Carteiras que costumam acertar (`app/engine/smart_confirm.py`, `smart-1`)
- Reaproveita `tape.db` (`smart_wallets`, `smart_buys`). `WalletProfile` (idade/origem de holder) é outra coisa e não é usado.
- Estados: `confirmed_secondary` (2+ carteiras distintas em 15 min, nenhuma com 80%+ do valor),
  `weak_confirmation`, `no_confirmation`, `expired`, `insufficient_data` (menos de 10 carteiras boas conhecidas ou
  sem registro), `unsupported_source` (DEX fora de pump.fun/PumpSwap).
- Sem olhar o futuro: só compras com `ts <= instante`; `smart_buys` só grava compra de carteira que já era boa na hora.
- Exposto em `exit-plan.smart_confirmation` (`influences_signal` sempre `false`).
- Registro por sinal de compra em `tape.db/smart_confirmations` (job `evaluate`), comparação em
  `GET /api/v1/system/smart-wallets/shadow` (retorno bruto em 1 h por estado; amostra < 30 marcada).
- Chave geral: `SMART_WALLET_SHADOW=false`. Não há chave de peso: influência no sinal só depois de semanas de
  comparação mostrarem valor fora da amostra.
