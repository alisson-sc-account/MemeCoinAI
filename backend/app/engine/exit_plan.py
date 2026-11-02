"""Plano de venda: quando vender e quanto (`exit-1`).

Regras fixas e explícitas (não calibradas historicamente):
- URGÊNCIA: "vender agora" com sinal de VENDER forte, veto crítico de saída (queda
  de liquidez ≥ 60% ou de preço ≥ 40% em 1 h), alerta da atualização rápida
  (`app.live`: liquidez retirada ou preço despencando em minutos) ou preço abaixo do stop; "reduzir" com
  VENDER moderado ou EVITAR; senão "manter com alvos".
- REFERÊNCIA: preço médio de compra da posição, se houver; senão o preço em que o
  sinal atual foi emitido; senão o preço atual.
- O aviso de saída perto do topo vem de `app.live.service.peak_call`, por ter rendido mais no backtest.
- ALVOS de realização parcial: +20% (ou a faixa alta típica de 1 h, se maior) vende
  30%; +50% vende mais 30%; +100% vende o restante.
- STOP: −15% da referência vende tudo.
- GATILHOS: condições observáveis que mudariam o plano.
É informativo: o sistema não executa ordens.
"""
RULES_VERSION = "exit-1"
STOP_LOSS = 0.15
TAKE_PROFITS = ((0.20, 30), (0.50, 30), (1.00, 40))  # (ganho, % da posição vendida)
EXIT_VETOES = {
    "L2_liquidity_drop_severe": "Liquidez caiu 60% ou mais em 1 h",
    "A4_price_crash": "Preço caiu 40% ou mais em 1 h",
    "R1_rugged": "Golpe detectado nesta moeda",
}


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.0f}%".replace("+-", "-")


def build(price: float | None, liquidity: float | None, analysis, signal, position, estimates: list[dict],
          advice: dict | None = None, live_alerts: list[str] | None = None, peak: tuple[int, str] | None = None) -> dict:
    base = {"version": RULES_VERSION,
            "disclaimer": "Plano automático por regras fixas, não calibradas. Não é garantia nem ordem; o sistema não executa vendas."}
    if not price:
        return {**base, "urgency": "no_data", "headline": "Sem preço atual: não dá para montar o plano de venda.",
                "sell_percent_now": None, "keep_percent": None, "reference_price_usd": None, "reference_kind": None,
                "take_profits": [], "stop": None, "triggers": [], "reasons": []}

    if position and position.entry_price_usd:
        ref, kind = position.entry_price_usd, "seu preço médio de compra"
    elif signal and signal.reference_price_usd:
        ref, kind = signal.reference_price_usd, "preço quando o sinal atual foi emitido"
    else:
        ref, kind = price, "preço atual"

    risk_ids = {f["id"] for f in (analysis.risk_factors if analysis else [])}
    if peak and peak[0] >= 100:
        live_alerts = [*(live_alerts or []), peak[1]]
    vetoes = list(live_alerts or []) + [label for fid, label in EXIT_VETOES.items() if fid in risk_ids]
    stop_price = ref * (1 - STOP_LOSS)
    below_stop = price <= stop_price
    action = signal.action if signal else "hold"
    strength = signal.strength if signal else "none"

    reasons: list[str] = []
    if vetoes:
        reasons += vetoes
    if below_stop:
        reasons.append(f"Preço abaixo do stop ({_fmt_pct(price / ref - 1)} desde a referência)")
    if action == "sell":
        reasons += (signal.reasons or [])[:2] or ["Sinal de venda ativo"]

    if vetoes or below_stop or (action == "sell" and strength == "strong"):
        urgency, sell_now = "sell_now", 100
        headline = "Vender agora: venda total sugerida"
    elif peak:
        urgency, sell_now = "reduce", peak[0]
        headline = f"Vender {peak[0]}%: o preço virou"
        reasons.append(peak[1])
    elif action in ("sell", "avoid"):
        urgency, sell_now = "reduce", 50
        headline = "Reduzir: vender metade e proteger o restante"
        if action == "avoid" and not reasons:
            reasons.append("Risco alto para manter a posição inteira")
    else:
        urgency, sell_now = "hold", 0
        headline = "Manter com alvos: ainda sem motivo para vender"

    # Com posição registrada, a sugestão personalizada (lucro realizado etc.) prevalece se for maior.
    if advice and advice.get("has_position") and advice.get("sell_percent") is not None:
        if advice["sell_percent"] > sell_now:
            sell_now = advice["sell_percent"]
            reasons += [r for r in advice.get("reasons", []) if r not in reasons]
            if urgency == "hold":
                urgency, headline = "reduce", f"Realizar parte: vender {sell_now}%"

    e1h = next((e for e in estimates if e.get("horizon") == "1h" and e.get("basis") in ("similar", "general")), None)
    first_gain = max(TAKE_PROFITS[0][0], e1h["end_p75"]) if e1h and e1h.get("end_p75") is not None else TAKE_PROFITS[0][0]
    gains = [first_gain] + [g for g, _ in TAKE_PROFITS[1:]]
    take_profits = []
    for (gain, pct), g in zip(TAKE_PROFITS, gains):
        target = ref * (1 + g)
        take_profits.append({
            "label": f"Alvo {_fmt_pct(g)}", "price_usd": target, "change_from_reference": round(g, 4),
            "change_from_now": round(target / price - 1, 4), "sell_percent": pct, "reached": price >= target,
        })

    triggers = [f"Vender tudo se o preço cair abaixo de US$ {stop_price:.10g} ({_fmt_pct(-STOP_LOSS)} da referência)"]
    if liquidity:
        triggers.append(f"Vender tudo se a liquidez cair abaixo de US$ {liquidity * 0.4:,.0f} (queda de 60%)".replace(",", "."))
    triggers += [
        "Reduzir se as vendas superarem o dobro das compras na última hora com o preço caindo",
        "Vender tudo se surgir autoridade de mint/freeze ou queda brusca de liquidez",
    ]
    return {**base, "urgency": urgency, "headline": headline, "sell_percent_now": sell_now,
            "keep_percent": 100 - sell_now, "reference_price_usd": ref, "reference_kind": kind,
            "current_price_usd": price, "change_from_reference": round(price / ref - 1, 4),
            "take_profits": take_profits,
            "stop": {"price_usd": stop_price, "change_from_reference": -STOP_LOSS,
                     "change_from_now": round(stop_price / price - 1, 4), "sell_percent": 100, "reached": below_stop},
            "triggers": triggers, "reasons": reasons}
