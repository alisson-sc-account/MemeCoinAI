"""Negociações ao vivo (`tape-1`): cada compra e venda de pump.fun e PumpSwap, sem chave.

Lê os eventos pelo WebSocket público da Solana (`logsSubscribe`). Serve para três coisas:
- Disparo sem o atraso do DEX Screener: aplica a MESMA regra `burst.detect` sobre os 5 min reais.
- Fluxo de compra e venda da moeda aberta, que ajuda a avisar a venda perto do topo.
- Carteiras que costumam acertar: informação de apoio, nunca muda o sinal sozinha.

Grava em banco próprio (`data/tape.db`), para o volume de negociações não disputar o banco principal.
Limite: outras DEX (Raydium, Meteora, Orca) não entram; lá segue valendo o DEX Screener.
"""
