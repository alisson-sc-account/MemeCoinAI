# Prompt e plano: orquestrador de agentes (2026-10-30)

## Prompt

Evoluir o MemeCoinAI para um sistema de agentes subdivididos por categoria, sem piorar o que já funciona.

1. **Regra número 1:** o detector "Disparo agora" (`burst-1`) está acertando. Regras e entradas dele não mudam. Medir antes e depois.
2. Limite de 20 mil tokens (+10 mil), todos atualizando sozinhos, sem sobrecarregar nenhuma API.
3. Orquestrador: cada agente tem uma função, um orçamento de API, batimento e categoria. Um agente lento não atrasa outro.
4. Site rápido: telas não podem calcular listas dentro da requisição.
5. Identificar antes o que vai subir, com mais precisão: só entra regra que provar resultado em dados que ela não viu.
6. ESC fecha a notificação.
7. Custo zero (D-013). Sem burlar limite de fonte: nada de proxies ou contas falsas para fugir de rate limit.

## Linha de base medida

| Medida | Valor |
|---|---|
| Disparo, 214 alertas | 15 min: 59% sobem, mediana +5,3%, 43% ≥ +20% |
| Disparo, melhor preço em 1 h | mediana +32,7%, 59% ≥ +20%, 41% ≥ +50% |
| Tokens monitorados | 6125 (só 1120 contados como "atualizados" no painel) |
| Tokens conferidos | 2728 em 3 min, 5728 em 15 min |
| Ciclo de coleta | 60 s (25 s de rede + 35 s de análise no mesmo laço) |
| Dashboard / Compre agora | 3,2 s toda vez / 6,2 s na 1ª carga |

## Limites reais (por que "todos ao mesmo tempo" não existe de graça)

| Fonte | Limite | Capacidade |
|---|---|---|
| DEX Screener | 300 req/min, 30 tokens por req | 9 mil tokens/min no teto; usamos 270 req/min |
| Jupiter | 5 chamadas/10 s no total | listas de 100 tokens: usada como radar |
| GeckoTerminal | ~30/min, na prática menos | descoberta |
| RugCheck | ~15 por janela | 1 moeda a cada ~5 s |
| RPC público / publicnode | baixo por método / ~63 h de histórico | carteiras e pool da moeda aberta |
| Análise (CPU) | ~20 moedas/s | fila com prioridade |

Com isso: 20 mil tokens não atualizam juntos. Meta: quentes a cada ~30 s; todos em ~4 min; radar puxa para a frente quem começar a se mexer.

## Resultado medido depois

| Medida | Antes | Depois |
|---|---|---|
| Dashboard | 3,2 s | 0,013 s |
| Compre agora | 6,2 s | ~0,11 s |
| Atualizados no painel | 1120 de 6133 | 6279 de 6728 em 3 min |
| Idade do dado na análise (mediana / p90) | 25 s / 44 s | 20 s / 39 s |
| Disparo em 15 min: sobe / mediana | 59% / +5,3% (n=213) | 72% / +11,2% (n=40, amostra pequena) |
| Pré-disparo (backtest) | — | rejeitado: 0% a 5% chegam a +20% |

## Plano

**Coleta sem travar:** separar rede de análise. Agente `market_hot` (urgentes e 1500 mais quentes, 30 s), `market_cold` (rodízio com o restante do orçamento), fila de análise com prioridade: disparo em moeda quente não espera moeda fria.

**Radar:** agente que lê as listas de "mais negociados agora" e promove essas moedas para quentes por 15 min. É o que mais antecipa disparo em moeda fria.

**Descoberta dividida:** listas, buscas, GeckoTerminal e Jupiter viram agentes separados.

**Painel em processo próprio:** `python -m app.board` calcula listas em segundo plano e grava num banco separado (`data/board.db`). A API só lê com filtro e ordem por índice. Sem o processo, a API volta ao cálculo atual.

**Contagem:** "atualizado" passa a considerar a última conferência na fonte, não só a última mudança. Só na exibição: `fresh_enough` e as entradas do disparo não mudam.

**Previsão antecipada:** backtest com divisão por tempo em `analysis_outcomes`. Candidatas só entram se baterem a taxa-base com folga na parte não vista. Sem prova, não entra.

**Interface:** painel de agentes por categoria; ESC fecha alertas.

**Testes:** regressão congelando `burst.detect`, suíte completa, comparação com a linha de base depois de rodar.
