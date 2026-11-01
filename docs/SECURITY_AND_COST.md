# Segurança e custo zero

## Custo zero (D-013)

- Nenhuma assinatura, API paga, crédito, nuvem ou banco gerenciado é necessário. O caminho principal usa só DEX Screener e o RPC público Solana (classe A em [`DATA_SOURCES.md`](DATA_SOURCES.md)).
- Fontes que exigem chave, plano ou condição não verificada ficam **desligadas** (classes B/C/D). O teste `test_cost_policy_only_class_a_enabled` falha se alguma for ligada.
- O sistema inicia sem nenhuma chave de API. Não existe código de upgrade, cobrança ou ativação de créditos.
- No limite de uma fonte: espera com backoff, reduz as consultas e marca os dados como atrasados. Nunca troca de plano.

## Execução local

- A API escuta só em `127.0.0.1` (`run-local.ps1` usa `--host 127.0.0.1`). Não exponha a porta na rede nem no roteador.
- Interface e API na mesma origem; CORS só para o Vite em desenvolvimento.
- Sem telemetria remota. Banco, logs e histórico ficam no computador.

## Contas e dados

- Dois usuários locais (`natan`, `alisson`), senha com hash Argon2id e sessão em cookie httpOnly. A senha inicial é fraca: troque em **Configurações → Trocar senha**.
- O saldo é **simulação**: o sistema não conecta carteira, não pede seed phrase nem chave privada e não envia transações.
- Posições são informadas à mão e ficam por usuário.
- Segredos só em `backend/.env`, que fica fora do Git; `.env.example` não tem segredos.

## Limites honestos

- Scores e níveis são regras heurísticas, não probabilidade de lucro. "Confiança" mede a qualidade dos dados, não a chance de acerto.
- Detector de disparo = movimento em andamento, não previsão.
- Ausência de alerta não significa segurança.
