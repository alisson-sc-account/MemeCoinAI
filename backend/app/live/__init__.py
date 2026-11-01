"""Atualização rápida ("fast lane"): primeiro subsistema dedicado a uma única função.

Função: manter o quadro "Quando vender" com preço de no máximo ~10 s, sem depender
do ciclo do coletor (600 tokens, ~60 s por volta, e o DEX Screener segura o mesmo
preço por ~30 s no cache dele).

Peças, todas isoladas do coletor:
- `jupiter.py`  fonte própria (Jupiter Price API v3, sem chave, cache de 5 s);
- `service.py`  lista de acompanhamento, ciclo de cotação, alertas de golpe ao vivo,
                 batimento e leitura para a API;
- `__main__.py` processo próprio (`python -m app.live`) com trava própria.

Contrato com a API: a API só LÊ `live_quotes`/`service_heartbeats` e registra pedidos
em `live_watch`. Se este processo estiver parado, a API volta sozinha para os dados do
coletor e diz isso na resposta (`live.status = "off"`), sem inventar preço.
"""
