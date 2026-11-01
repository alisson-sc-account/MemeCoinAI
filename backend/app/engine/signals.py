"""Sinais acionáveis (`sig-1`) e sugestão de posição (`advice-1`).

Os sinais traduzem a análise em uma ação legível — COMPRAR, VENDER, EVITAR ou
AGUARDAR — com força, motivos e estimativas empíricas por horizonte. As regras
são explícitas (tabela em ANALYSIS_ENGINE.md §9) e o histórico de acerto de
cada tipo de sinal é medido em `performance()`. Nada aqui é garantia de
resultado nem executa ordens.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.alerts import AlertCandidate
from app.engine.outcomes import HORIZONS
from app.models import AnalysisOutcome, Signal

RULES_VERSION = "sig-1"
ADVICE_VERSION = "advice-1"

HEADLINES = {
    ("buy", "strong"): "Compre agora: sinal forte de alta",
    ("buy", "moderate"): "Possível entrada: sinal de alta",
    ("sell", "strong"): "Venda agora: risco de queda forte",
    ("sell", "moderate"): "Considere reduzir: sinais de queda",
    ("avoid", "moderate"): "Evite: risco alto",
    ("hold", "none"): "Aguardar: sem sinal claro",
}
STRENGTH_ORDER = {"none": 0, "moderate": 1, "strong": 2}


def _estimate_1h(estimates: list[dict]) -> dict | None:
    e = next((x for x in estimates if x["horizon"] == "1h"), None)
    return e if e and e.get("basis") in ("similar", "general") else None


# Histerese: um token que já está em COMPRAR só sai do nível quando a oportunidade
# cai este tanto abaixo do limiar de entrada. Evita "pisca-pisca" entre COMPRAR e
# AGUARDAR por oscilações pequenas do score a cada coleta.
BUY_MIN_OPPORTUNITY = 45.0
STRONG_MIN_OPPORTUNITY = 60.0
HYSTERESIS_POINTS = 5.0


def decide(analysis, features: dict, estimates: list[dict], freshness_ok: bool = True,
           previous: tuple[str, str] | None = None) -> dict:
    """`previous` = (ação, força) do sinal ativo anterior, usado só na histerese de compra."""
    """Retorna {action, strength, headline, reasons}."""
    risk, opp = analysis.risk_score, analysis.opportunity_score
    ids = {f["id"] for f in analysis.risk_factors}
    labels = {f["id"]: f["label"] for f in analysis.risk_factors}
    opp_labels = [f["label"] for f in analysis.opportunity_factors if f["points"] > 0]
    liq = features.get("liquidity_usd")
    pc1 = features.get("price_change_h1")
    insufficient = bool((analysis.data_quality or {}).get("insufficient_data"))
    # Parte do risco que vem de evidência observada (exclui pontos por falta de dados).
    observed_risk = sum(f["points"] for f in analysis.risk_factors if f.get("category") != "data")
    reasons: list[str] = []

    # Sem cotação recente não há base para comprar nem vender agora.
    if not freshness_ok:
        return {"action": "hold", "strength": "none", "headline": HEADLINES[("hold", "none")],
                "reasons": ["Dados desatualizados: sem sinal até a próxima cotação"]}

    # --- VENDER: deterioração observada ------------------------------------
    sell_strong = [i for i in ("L2_liquidity_drop_severe", "A4_price_crash") if i in ids]
    if observed_risk >= 75:
        sell_strong.append("risk")
    sell_moderate = [i for i in ("L2_liquidity_drop",) if i in ids]
    if "A1_sell_pressure" in ids and pc1 is not None and pc1 <= -10:
        sell_moderate.append("A1_sell_pressure")
    if sell_strong or sell_moderate:
        strength = "strong" if sell_strong else "moderate"
        for i in sell_strong + sell_moderate:
            reasons.append(f"Risco observado {observed_risk:.0f}/100" if i == "risk" else labels.get(i, i))
        return {"action": "sell", "strength": strength, "headline": HEADLINES[("sell", strength)], "reasons": reasons}

    # --- EVITAR: risco técnico/estrutural ----------------------------------
    technical = [i for i in ("T1_mint_authority", "T2_freeze_authority", "T3_token2022_extensions") if i in ids]
    if risk >= 60 or technical:
        reasons = [labels[i] for i in technical] or [f"Score de risco {risk:.0f}/100"]
        return {"action": "avoid", "strength": "moderate", "headline": HEADLINES[("avoid", "moderate")], "reasons": reasons}

    # --- COMPRAR ----------------------------------------------------------
    buy_floor, strong_floor = BUY_MIN_OPPORTUNITY, STRONG_MIN_OPPORTUNITY
    if previous and previous[0] == "buy":
        buy_floor -= HYSTERESIS_POINTS
        if previous[1] == "strong":
            strong_floor -= HYSTERESIS_POINTS
    can_buy = not insufficient and liq is not None and liq >= 10_000 and risk < 50 and opp >= buy_floor
    if can_buy:
        strength = "strong" if opp >= strong_floor and liq >= 20_000 else "moderate"
        e1 = _estimate_1h(estimates)
        if strength == "strong" and e1 and e1["end_median"] <= 0 and e1["p_up_10"] < 0.3:
            strength = "moderate"
            reasons.append("Histórico de casos parecidos não confirma alta em 1 h")
        reasons = opp_labels[:4] + reasons
        return {"action": "buy", "strength": strength, "headline": HEADLINES[("buy", strength)], "reasons": reasons}

    why = []
    if insufficient:
        why.append("Dados insuficientes")
    if liq is not None and liq < 10_000:
        why.append("Liquidez baixa para entrar e sair")
    if opp < 45:
        why.append(f"Oportunidade fraca ({opp:.0f}/100)")
    return {"action": "hold", "strength": "none", "headline": HEADLINES[("hold", "none")], "reasons": why}


def upsert_signal(db: Session, token_id: int, analysis, decision: dict, estimates: list[dict], price: float | None) -> tuple[Signal, bool]:
    """Novo sinal se a ação mudou ou a força aumentou; senão apenas confirma o atual."""
    now = analysis.computed_at
    cur = db.scalar(select(Signal).where(Signal.token_id == token_id, Signal.status == "active").limit(1))
    if cur and cur.action == decision["action"] and STRENGTH_ORDER[decision["strength"]] <= STRENGTH_ORDER[cur.strength]:
        cur.last_confirmed_at = now
        cur.analysis_id = analysis.id
        cur.estimates = estimates
        cur.reasons = decision["reasons"]
        cur.risk_score, cur.risk_level, cur.opportunity_score = analysis.risk_score, analysis.risk_level, analysis.opportunity_score
        if decision["strength"] != cur.strength:
            cur.strength = decision["strength"]
            cur.headline = decision["headline"]
        return cur, False
    if cur:
        cur.status = "superseded"
    sig = Signal(
        token_id=token_id, analysis_id=analysis.id, created_at=now, last_confirmed_at=now,
        action=decision["action"], strength=decision["strength"], status="active", headline=decision["headline"],
        reasons=decision["reasons"], risk_score=analysis.risk_score, risk_level=analysis.risk_level,
        opportunity_score=analysis.opportunity_score, reference_price_usd=price, estimates=estimates,
        rules_version=RULES_VERSION,
    )
    db.add(sig)
    db.flush()
    return sig, True


def alert_for(sig: Signal) -> AlertCandidate | None:
    if sig.action == "buy":
        sev = "high" if sig.strength == "strong" else "medium"
        return AlertCandidate("buy_signal", sev, sig.headline, "; ".join(sig.reasons) or "Sinal de compra",
                              {"signal_id": sig.id, "strength": sig.strength, "estimates": sig.estimates}, 0.5)
    if sig.action == "sell":
        sev = "critical" if sig.strength == "strong" else "high"
        return AlertCandidate("sell_signal", sev, sig.headline, "; ".join(sig.reasons) or "Sinal de venda",
                              {"signal_id": sig.id, "strength": sig.strength}, 0.7)
    return None


def performance(db: Session, since: datetime | None = None) -> list[dict]:
    """Acerto histórico por tipo de sinal e horizonte, usando os rótulos das análises."""
    q = select(Signal.action, Signal.strength, AnalysisOutcome.horizon_seconds, AnalysisOutcome.end_return,
               AnalysisOutcome.max_return, AnalysisOutcome.min_return).join(
        AnalysisOutcome, AnalysisOutcome.analysis_id == Signal.analysis_id
    ).where(AnalysisOutcome.status == "ok", Signal.action.in_(("buy", "sell")))
    if since:
        q = q.where(Signal.created_at >= since)
    groups: dict[tuple, list] = {}
    for action, strength, secs, end, mx, mn in db.execute(q):
        groups.setdefault((action, strength, secs), []).append((end, mx, mn))
    names = {v: k for k, v in HORIZONS.items()}
    out = []
    for (action, strength, secs), rows in sorted(groups.items()):
        n = len(rows)
        ends = sorted(r[0] for r in rows)
        if action == "buy":
            hit = sum(1 for r in rows if r[0] > 0) / n
            big = sum(1 for r in rows if r[1] >= 0.10) / n
        else:
            hit = sum(1 for r in rows if r[0] < 0) / n
            big = sum(1 for r in rows if r[2] <= -0.10) / n
        out.append({
            "action": action, "strength": strength, "horizon": names.get(secs, f"{secs}s"), "n": n,
            "hit_rate": round(hit, 4), "big_move_rate": round(big, 4), "median_end_return": round(ends[n // 2], 4),
            "definition": "compra: acerto = preço final acima da entrada; movimento forte = máx. ≥ +10%"
            if action == "buy" else "venda: acerto = preço final abaixo do sinal; movimento forte = mín. ≤ −10%",
        })
    return out


def money(amount: float, currency: str) -> str:
    s = f"{amount:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {s}" if currency == "BRL" else f"US$ {s}"


def allocation(action: str, strength: str, risk_score: float, balance: float | None, currency: str, max_pct: float) -> dict | None:
    """Quanto do saldo usar numa compra (`size-1`).

    Forte = teto por operação; moderado = metade. Risco ≥ 25 corta pela metade.
    Memecoins podem ir a zero: o teto padrão é 10% do saldo por operação.
    """
    if action != "buy" or not balance or balance <= 0:
        return None
    pct = max_pct if strength == "strong" else max_pct / 2
    if risk_score >= 25:
        pct /= 2
    pct = round(pct, 1)
    return {"percent_of_balance": pct, "amount": round(balance * pct / 100, 2), "currency": currency,
            "max_trade_percent": max_pct, "rule": "size-1"}


def advise(signal: Signal | None, position, price: float | None, exit_estimate: dict | None, user=None) -> dict:
    """Sugestão de % a vender (com posição) ou quanto do saldo usar para comprar."""
    base = {"version": ADVICE_VERSION, "disclaimer": (
        "Sugestão automática baseada em regras e no histórico do próprio sistema. "
        "Não é garantia nem recomendação financeira; o sistema não executa ordens.")}
    action = signal.action if signal else "hold"
    strength = signal.strength if signal else "none"
    reasons: list[str] = []
    alloc = None
    if signal is not None and user is not None:
        alloc = allocation(action, strength, signal.risk_score, user.balance_amount, user.balance_currency, user.max_trade_percent)
    if alloc:
        base.update(buy_percent_of_balance=alloc["percent_of_balance"], buy_amount=alloc["amount"], currency=alloc["currency"])
    if position is None:
        if action == "buy":
            pct = 50 if strength == "strong" else 25
            if alloc:
                verb = "Compre agora" if strength == "strong" else "Se quiser entrar, use"
                return {**base, "has_position": False, "action": "buy", "buy_percent_of_plan": pct, "sell_percent": None,
                        "summary": f"{verb} com {alloc['percent_of_balance']:g}% do seu saldo ({money(alloc['amount'], alloc['currency'])}).",
                        "reasons": [f"Teto de {alloc['max_trade_percent']:g}% do saldo por operação (configurável em Conta)",
                                    *(["Risco não é baixo: tamanho reduzido à metade"] if signal.risk_score >= 25 else [])]}
            return {**base, "has_position": False, "action": "buy", "buy_percent_of_plan": pct, "sell_percent": None,
                    "summary": f"Comprar {pct}% do valor que você planeja investir neste token agora; o restante só se o sinal se confirmar.",
                    "reasons": ["Entrada em partes reduz o impacto de um sinal falso",
                                "Informe seu saldo em Conta para ver a sugestão em % do saldo"]}
        msg = {"sell": "Sem posição registrada: não entrar.", "avoid": "Sem posição registrada: não entrar.",
               "hold": "Sem posição registrada: aguardar um sinal claro."}[action]
        return {**base, "has_position": False, "action": "none", "buy_percent_of_plan": 0, "sell_percent": None, "summary": msg, "reasons": []}

    value = position.quantity * price if price else None
    pnl = (price / position.entry_price_usd - 1) if price and position.entry_price_usd else None
    sell = 0
    if action == "sell":
        sell = 100 if strength == "strong" else 50
        reasons.append("Sinal de venda ativo")
    elif action == "avoid":
        sell = 50
        reasons.append("Risco alto para manter a posição inteira")
    elif pnl is not None and pnl >= 1.0:
        sell = 50
        reasons.append(f"Lucro de {pnl:.0%}: realizar metade recupera o capital investido")
    elif pnl is not None and pnl >= 0.5:
        sell = 25
        reasons.append(f"Lucro de {pnl:.0%}: realizar parte reduz a exposição")
    buy_more = 0
    if action == "buy" and sell == 0:
        buy_more = 25 if strength == "strong" else 0
        if buy_more:
            reasons.append("Sinal forte de compra: aumentar só uma fração")
    slippage_note = None
    if exit_estimate and value and sell:
        if exit_estimate.get("available"):
            liq_base = exit_estimate.get("scenarios", [{}])
            sell_usd = value * sell / 100
            impact = None
            if liq_base and exit_estimate.get("spot_price_usd"):
                # Reaproveita a reserva do pool implícita no primeiro cenário.
                s0 = liq_base[0]
                reserve = s0["tokens_sold"] / s0["share_of_pool_base"] if s0.get("share_of_pool_base") else None
                if reserve:
                    dx = sell_usd / exit_estimate["spot_price_usd"]
                    impact = dx / (reserve + dx)
            if impact is not None and impact > 0.03:
                slippage_note = f"Vender {sell}% de uma vez teria impacto estimado de {impact:.1%} no preço; considere vender em partes."
        else:
            slippage_note = "Impacto da venda no preço não estimável para este tipo de pool."
    if sell:
        summary = f"Vender {sell}% da posição e manter {100 - sell}%."
    elif buy_more and alloc:
        summary = f"Manter e, se quiser, aumentar com até {alloc['percent_of_balance']:g}% do seu saldo ({money(alloc['amount'], alloc['currency'])})."
    elif buy_more:
        summary = f"Manter e, se quiser, aumentar até {buy_more}% do valor que planeja investir."
    else:
        summary = "Manter a posição."
    return {**base, "has_position": True, "action": "sell" if sell else ("buy" if buy_more else "hold"),
            "sell_percent": sell, "buy_percent_of_plan": buy_more, "keep_percent": 100 - sell,
            "position_value_usd": round(value, 2) if value else None, "pnl": round(pnl, 4) if pnl is not None else None,
            "summary": summary, "reasons": reasons, "slippage_note": slippage_note}
