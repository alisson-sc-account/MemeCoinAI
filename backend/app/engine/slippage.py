"""Estimativa de impacto de saída (venda do token-base por quote).

Só é calculada para pools de produto constante (x*y=k), identificados por
dexId/labels observados no DEX Screener. Para CLMM/DLMM/Whirlpool/bonding
curve a fórmula não vale e a estimativa é marcada como indisponível.

Fórmula (sem taxas): vender Δx de base com reservas (x, y) rende
y·Δx/(x+Δx). Impacto de preço = Δx/(x+Δx). Taxas do pool NÃO incluídas
(a fonte não informa a taxa de cada pool).
"""
METHOD_VERSION = "slip-1"

DEFAULT_POSITIONS_USD = (100, 500, 1_000, 5_000, 10_000, 50_000)


def pool_model(dex_id: str | None, labels: list[str] | None) -> tuple[str, str]:
    labels_l = {x.lower() for x in (labels or [])}
    dex = (dex_id or "").lower()
    if labels_l & {"clmm", "dlmm", "wp", "v3", "v4"}:
        return "concentrated", "liquidez concentrada: profundidade depende das faixas de preço, não modelada"
    if labels_l & {"dyn", "dyn2"}:
        return "unsupported", "AMM dinâmico (Meteora): reservas parcialmente alocadas, não modelado"
    if dex == "pumpfun":
        return "bonding_curve", "curva de bonding pump.fun: não é um pool AMM"
    if labels_l & {"cpmm", "v2"} or dex == "pumpswap" or (dex == "raydium" and not labels_l):
        return "constant_product", "pool de produto constante (x*y=k)"
    return "unknown", f"tipo de pool não identificado (dex={dex_id}, labels={sorted(labels_l)})"


def estimate_exit(
    dex_id: str | None,
    labels: list[str] | None,
    price_usd: float | None,
    liquidity_base: float | None,
    liquidity_quote: float | None,
    liquidity_usd: float | None,
    positions_usd: tuple[float, ...] | list[float] = DEFAULT_POSITIONS_USD,
) -> dict:
    model, note = pool_model(dex_id, labels)
    base = {
        "method_version": METHOD_VERSION,
        "pool_model": model,
        "pool_model_note": note,
        "spot_price_usd": price_usd,
        "liquidity_usd": liquidity_usd,
        "fees_included": False,
        "unknown_costs": ["taxa do pool", "taxa de prioridade/gas da rede", "movimento de preço durante a execução"],
    }
    if model != "constant_product":
        return {**base, "available": False, "reason": note, "scenarios": []}
    if not price_usd or not liquidity_base or not liquidity_quote or liquidity_base <= 0 or liquidity_quote <= 0:
        return {**base, "available": False, "reason": "reservas ou preço ausentes na fonte", "scenarios": []}

    scenarios = []
    for usd in positions_usd:
        dx = usd / price_usd  # quantidade de token-base a vender
        impact = dx / (liquidity_base + dx)
        received_usd = usd * (1 - impact)
        scenarios.append({
            "position_usd": usd,
            "tokens_sold": dx,
            "price_impact": round(impact, 6),
            "estimated_avg_price_usd": price_usd * (1 - impact),
            "estimated_received_usd": round(received_usd, 2),
            "share_of_pool_base": round(dx / liquidity_base, 6),
        })
    return {**base, "available": True, "reason": None, "scenarios": scenarios}
