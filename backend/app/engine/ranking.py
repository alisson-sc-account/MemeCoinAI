"""Níveis de oportunidade para a aba "Compre agora" (`rank-1`).

Separa três coisas que não devem virar um número só:
- **Bloqueio crítico (veto)**: evidência técnica validada que impede nível positivo.
- **Qualidade da decisão**: dados essenciais (preço, liquidez, frescor) utilizáveis?
  `no_reliable_signal` é exceção; dado secundário ausente (social, holders,
  carteiras) só reduz cobertura/confiança, nunca esvazia a lista.
- **Atratividade**: score de oportunidade, confiança e cobertura, mostrados separados.

O nível vem do sinal já estabilizado (com histerese em `signals.decide`):
compra forte → prioritária; compra moderada → possível; aguardar → observar;
vender/evitar → evitar. Vetos sempre prevalecem.
"""

RANKING_VERSION = "rank-1"
IMPOSSIBLE_CHANGE_PCT = 100_000.0  # +100.000%: nas moedas analisadas, sempre preço quebrado (ex.: +161 bilhões %)

TIER_ORDER = {"priority_buy": 0, "possible_buy": 1, "watch": 2, "avoid": 3}
TIER_LABELS = {
    "priority_buy": "Compra prioritária",
    "possible_buy": "Compra possível",
    "watch": "Observar",
    "avoid": "Evitar",
}

# Fatores de risco que bloqueiam qualquer nível positivo (evidência técnica ou de saída).
HARD_VETO_FACTORS = {
    "T1_mint_authority": "Autoridade de mint ativa",
    "T2_freeze_authority": "Autoridade de freeze ativa",
    "T3_token2022_extensions": "Extensões Token-2022 de risco",
    "L2_liquidity_drop_severe": "Liquidez caiu 60% ou mais em 1 h",
    "A4_price_crash": "Preço caiu 40% ou mais em 1 h",
    "R1_rugged": "Golpe detectado nesta moeda",
}

# Dados que nunca vêm das fontes gratuitas ativas: reduzem cobertura, não bloqueiam.
ALWAYS_MISSING_SECONDARY = [
    "Sinais sociais (nenhuma fonte social gratuita ativa)",
]

SECONDARY_CHECK_LABELS = {
    "holder_concentration": "Concentração de holders",
    "mint_authorities": "Autoridades do mint",
    "liquidity_history": "Histórico próprio de liquidez",
}


def classify(analysis, features: dict, signal_action: str | None, signal_strength: str | None,
             freshness_status: str) -> dict:
    """Classifica um token. `analysis` pode ser None (token ainda sem análise)."""
    if analysis is None:
        return {
            "tier": "watch", "decision_quality": "no_reliable_signal",
            "decision_quality_reason": "Token ainda não analisado (aguardando dados de mercado).",
            "critical_blocks": [], "reasons_for": [], "reasons_against": [],
            "missing_data": ["Dados de mercado"] + ALWAYS_MISSING_SECONDARY,
        }

    risk_factors = analysis.risk_factors or []
    critical = [HARD_VETO_FACTORS[f["id"]] for f in risk_factors if f["id"] in HARD_VETO_FACTORS]

    for key, label in (("price_change_h1", "1 h"), ("price_change_h6", "6 h"), ("price_change_h24", "24 h")):
        change = features.get(key)
        if change is not None and change > IMPOSSIBLE_CHANGE_PCT:  # preço ou par com dado quebrado na fonte
            critical = [*critical, f"Variação de preço impossível em {label}: dado suspeito"]
            break

    missing_essential = [name for key, name in (("price_usd", "Preço"), ("liquidity_usd", "Liquidez"))
                         if features.get(key) is None]
    missing_secondary = [
        f"{SECONDARY_CHECK_LABELS.get(c.get('check'), c.get('check'))}: {c.get('reason')}"
        for c in (analysis.checks_not_performed or [])
        if c.get("check") in SECONDARY_CHECK_LABELS
    ]

    if not features.get("available") or missing_essential:
        quality, why = "no_reliable_signal", "Dado essencial ausente: " + ", ".join(missing_essential or ["mercado"]) + "."
    elif freshness_status in ("stale", "no_data"):
        quality, why = "no_reliable_signal", "Cotação desatualizada: sem leitura confiável agora."
    elif missing_secondary:
        quality, why = "partial", "Análise parcial: " + "; ".join(missing_secondary) + "."
    else:
        quality, why = "ok", "Verificações planejadas executadas."

    if critical:
        tier = "avoid"
    elif quality == "no_reliable_signal":
        tier = "watch"
    elif signal_action in ("sell", "avoid"):
        tier = "avoid"
    elif signal_action == "buy":
        tier = "priority_buy" if signal_strength == "strong" else "possible_buy"
    else:
        tier = "watch"

    reasons_for = [f["label"] for f in (analysis.opportunity_factors or []) if f.get("points", 0) > 0]
    reasons_against = [f["label"] for f in risk_factors if f.get("category") != "data"]
    reasons_against += [f["label"] for f in (analysis.opportunity_factors or []) if f.get("points", 0) < 0]

    return {
        "tier": tier, "decision_quality": quality, "decision_quality_reason": why,
        "critical_blocks": critical, "reasons_for": reasons_for, "reasons_against": reasons_against,
        "missing_data": missing_essential + missing_secondary + ALWAYS_MISSING_SECONDARY,
    }


SORT_FIELDS = ("tier", "score", "score_change", "liquidity_usd", "volume_h24", "price_change_h1", "risk_score")


def sort_items(items: list[dict], sort: str = "tier") -> list[dict]:
    """`tier` (padrão): nível e depois score. Demais: pelo campo; risco em ordem crescente.

    Valores ausentes vão sempre para o fim (nunca são tratados como zero).
    """
    if sort == "tier":
        return sorted(items, key=lambda i: (TIER_ORDER[i["tier"]], -(i.get("score") or 0.0)))
    present = [i for i in items if i.get(sort) is not None]
    missing = [i for i in items if i.get(sort) is None]
    present.sort(key=lambda i: i[sort], reverse=(sort != "risk_score"))
    return present + missing
