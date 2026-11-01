"""Segurança das moedas (`sec-1`): subsistema próprio contra rug pull e manipulação.

Função: dizer, antes da compra, se a moeda tem sinais de golpe. Processo `python -m app.safety`,
trava própria, tabelas próprias (`security_reports`, `wallet_profiles`).

Fontes, todas grátis e sem chave, cada uma com seu limite (listados em `report.limitations`):
- RugCheck: liquidez travada, maiores donos, redes de insiders, autoridades. ~15 req por janela.
- RPC Solana: idade e origem do dinheiro das maiores carteiras (carteira nova, mesma origem).
- Histórico próprio: atividade artificial e liquidez muito baixa para o valor de mercado.

NUNCA diz "seguro": o melhor resultado é "Sem alertas". Sem dado é "Sem dados", não aprovação.
Bubblemaps não é usado: a API pública respondeu sem mapa e a oficial é paga. O mapa de carteiras
vem dos dados acima.
"""
