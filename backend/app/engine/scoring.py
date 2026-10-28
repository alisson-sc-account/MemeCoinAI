"""Scores explicáveis de risco e oportunidade (regras versionadas).

Cada fator devolvido tem: id, category, label, points, severity, confidence,
evidence. A tabela completa de regras e pesos está em ANALYSIS_ENGINE.md.
Os pesos são escolhas a priori, AINDA NÃO validadas historicamente.

Princípio: falta de dados aumenta incerteza e soma pontos de risco na
categoria `data`; nunca reduz o risco.
"""
from dataclasses import dataclass, field

RISK_RULES_VERSION = "risk-1"
OPPORTUNITY_RULES_VERSION = "opp-1"
ENGINE_VERSION = f"{RISK_RULES_VERSION}+{OPPORTUNITY_RULES_VERSION}+f-1"

# Verificações planejadas que compõem a cobertura do score de risco.
PLANNED_CHECKS = ("market_data", "liquidity_history", "mint_authorities", "holder_concentration")


@dataclass
class Factor:
    id: str
    category: str  # technical | liquidity | concentration | activity | data | market
    label: str
    points: float
    severity: str  # info | low | medium | high | critical
    confidence: float
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "label": self.label, "points": round(self.points, 2),
            "severity": self.severity, "confidence": self.confidence, "evidence": self.evidence,
        }


@dataclass
class RiskResult:
    score: float
    level: str
    confidence: float
    coverage: float
    insufficient_data: bool
    factors: list[Factor]
    checks_not_performed: list[dict]


@dataclass
class OpportunityResult:
    score: float
    raw_score: float
    confidence: float
    factors: list[Factor]
    invalidation_conditions: list[str]


def risk_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "moderate"
    return "low"


def score_risk(f: dict, mint_check: dict | None, holders_check: dict | None, chain_id: str) -> RiskResult:
    """`mint_check`/`holders_check`: {'status': ..., 'result': {...}, 'checked_at': iso} ou None."""
    factors: list[Factor] = []
    not_done: list[dict] = []
    done: set[str] = set()

    # --- Dados de mercado -------------------------------------------------
    if not f.get("available"):
        not_done.append({"check": "market_data", "reason": "nenhum snapshot de mercado disponível"})
        factors.append(Factor("D0_no_market_data", "data", "Sem dados de mercado", 40, "high", 1.0))
    else:
        done.add("market_data")
        liq = f.get("liquidity_usd")
        if liq is None:
            factors.append(Factor("D1_liquidity_missing", "data", "Liquidez não informada pela fonte", 20, "medium", 1.0))
        elif liq < 5_000:
            factors.append(Factor("L1_liquidity_very_low", "liquidity", "Liquidez muito baixa (< US$ 5 mil)", 30, "high", 0.9, {"liquidity_usd": liq}))
        elif liq < 20_000:
            factors.append(Factor("L1_liquidity_low", "liquidity", "Liquidez baixa (< US$ 20 mil)", 18, "medium", 0.9, {"liquidity_usd": liq}))
        elif liq < 50_000:
            factors.append(Factor("L1_liquidity_moderate", "liquidity", "Liquidez moderada (< US$ 50 mil)", 8, "low", 0.9, {"liquidity_usd": liq}))

        ltm = f.get("liquidity_to_mcap")
        if ltm is not None and ltm < 0.02:
            factors.append(Factor("L3_thin_vs_mcap", "liquidity", "Liquidez < 2% da capitalização (saída difícil)", 10, "medium", 0.7, {"liquidity_to_mcap": round(ltm, 5)}))

        # Histórico próprio de liquidez
        chg = f.get("liquidity_change_vs_max_1h")
        if f.get("history_points_1h", 0) >= 2 and chg is not None:
            done.add("liquidity_history")
            if chg <= -0.6:
                factors.append(Factor("L2_liquidity_drop_severe", "liquidity", "Queda de liquidez ≥ 60% em 1h", 40, "critical", 0.85, {"change": round(chg, 4), "prior_max_usd": f.get("liquidity_max_prior_1h")}))
            elif chg <= -0.3:
                factors.append(Factor("L2_liquidity_drop", "liquidity", "Queda de liquidez ≥ 30% em 1h", 25, "high", 0.8, {"change": round(chg, 4), "prior_max_usd": f.get("liquidity_max_prior_1h")}))
        else:
            not_done.append({"check": "liquidity_history", "reason": "histórico próprio insuficiente na última hora"})

        b, s_ = f.get("buys_h1"), f.get("sells_h1")
        txns = f.get("txns_h1")
        if b is not None and s_ is not None and txns and txns >= 30 and s_ >= 2 * max(b, 1):
            factors.append(Factor("A1_sell_pressure", "activity", "Vendas ≥ 2x compras na última hora", 12, "medium", 0.6, {"buys_h1": b, "sells_h1": s_}))

        avg = f.get("avg_trade_usd_h1")
        vol_h1 = f.get("volume_h1")
        if avg is not None and txns is not None and vol_h1 is not None and avg > 5_000 and txns < 20 and vol_h1 > 20_000:
            factors.append(Factor("A2_few_large_trades", "activity", "Volume concentrado em poucas transações grandes", 10, "medium", 0.5, {"avg_trade_usd_h1": round(avg, 2), "txns_h1": txns}))
        vtl = f.get("volume_h24_to_liquidity")
        if vtl is not None and vtl > 50:
            factors.append(Factor("A3_volume_vs_liquidity", "activity", "Volume 24h > 50x a liquidez (possível wash trading)", 10, "medium", 0.4, {"volume_h24_to_liquidity": round(vtl, 2)}))
        pc = f.get("price_change_h1")
        if pc is not None and pc <= -40:
            factors.append(Factor("A4_price_crash", "market", "Preço caiu ≥ 40% em 1h", 15, "high", 0.9, {"price_change_h1": pc}))

        age = f.get("pair_age_hours")
        if age is None:
            factors.append(Factor("D2_age_unknown", "data", "Idade do par desconhecida", 5, "low", 1.0))
        elif age < 1:
            factors.append(Factor("D2_very_young", "data", "Par com menos de 1h (pouco histórico)", 10, "medium", 1.0, {"pair_age_hours": round(age, 3)}))

    # --- Verificações técnicas (específicas da rede) ----------------------
    if chain_id != "solana":
        not_done.append({"check": "mint_authorities", "reason": f"rede {chain_id} sem verificação técnica implementada"})
        factors.append(Factor("D3_technical_unchecked", "data", "Permissões do contrato não verificadas", 15, "medium", 1.0))
    elif not mint_check or mint_check["status"] not in ("ok", "flagged"):
        reason = (mint_check or {}).get("result", {}).get("reason") if mint_check else "verificação ainda não executada"
        not_done.append({"check": "mint_authorities", "reason": reason or "indisponível"})
        factors.append(Factor("D3_technical_unchecked", "data", "Permissões do mint não verificadas", 15, "medium", 1.0))
    else:
        done.add("mint_authorities")
        r = mint_check["result"]
        ev = {"checked_at": mint_check.get("checked_at"), "program": r.get("program")}
        if r.get("mint_authority"):
            factors.append(Factor("T1_mint_authority", "technical", "Autoridade de mint ativa (supply pode aumentar)", 35, "high", 0.95, {**ev, "mint_authority": r["mint_authority"]}))
        if r.get("freeze_authority"):
            factors.append(Factor("T2_freeze_authority", "technical", "Autoridade de freeze ativa (contas podem ser congeladas)", 30, "high", 0.95, {**ev, "freeze_authority": r["freeze_authority"]}))
        risky = r.get("risky_extensions") or []
        if risky:
            pts = min(40, 25 * len(risky))
            factors.append(Factor("T3_token2022_extensions", "technical", "Extensões Token-2022 potencialmente prejudiciais", pts, "high", 0.9, {**ev, "extensions": risky}))

    if chain_id == "solana" and holders_check and holders_check["status"] in ("ok", "flagged"):
        done.add("holder_concentration")
        r = holders_check["result"]
        top10 = r.get("top10_share") or 0
        ev = {"top10_share": top10, "top1_share": r.get("top1_share"), "limitations": r.get("limitations")}
        if top10 > 0.8:
            factors.append(Factor("C1_concentration_extreme", "concentration", "Top 10 contas detêm > 80% do supply", 30, "high", 0.4, ev))
        elif top10 > 0.5:
            factors.append(Factor("C1_concentration_high", "concentration", "Top 10 contas detêm > 50% do supply", 20, "medium", 0.4, ev))
    else:
        reason = (holders_check or {}).get("result", {}).get("reason") if holders_check else None
        not_done.append({"check": "holder_concentration", "reason": reason or ("não suportado nesta rede" if chain_id != "solana" else "verificação ainda não executada")})
        factors.append(Factor("D4_concentration_unchecked", "data", "Concentração de holders não verificada", 5, "low", 1.0))

    score = min(100.0, sum(x.points for x in factors))
    coverage = len(done) / len(PLANNED_CHECKS)
    confidence = round(0.3 + 0.7 * coverage, 3)
    return RiskResult(
        score=round(score, 2), level=risk_level(score), confidence=confidence, coverage=round(coverage, 3),
        insufficient_data=coverage < 0.5, factors=factors, checks_not_performed=not_done,
    )


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_opportunity(f: dict, risk: RiskResult) -> OpportunityResult:
    factors: list[Factor] = []
    inval: list[str] = []
    if not f.get("available"):
        return OpportunityResult(0.0, 0.0, 0.0, [], ["sem dados de mercado"])

    required = ("volume_accel_h1", "buy_ratio_h1", "txn_accel_h1", "price_change_h1", "liquidity_usd")
    present = sum(1 for k in required if f.get(k) is not None)

    va = f.get("volume_accel_h1")
    if va is not None and va > 1:
        pts = 20 * _clip01((va - 1) / 2)
        factors.append(Factor("O1_volume_accel", "market", "Volume da última hora acima da média de 6h", pts, "info", 0.7, {"volume_accel_h1": round(va, 3)}))
        inval.append("volume horário voltar à média das últimas 6h")
    vm = f.get("volume_accel_m5")
    if vm is not None and vm > 1:
        factors.append(Factor("O2_volume_accel_5m", "market", "Volume dos últimos 5 min acima da média horária", 10 * _clip01((vm - 1) / 3), "info", 0.5, {"volume_accel_m5": round(vm, 3)}))
    br = f.get("buy_ratio_h1")
    if br is not None and br > 0.5:
        factors.append(Factor("O3_buy_pressure", "activity", "Mais compras que vendas na última hora", 15 * _clip01((br - 0.5) / 0.25), "info", 0.5, {"buy_ratio_h1": round(br, 3)}))
        inval.append("proporção de compras na última hora cair abaixo de 50%")
    ta = f.get("txn_accel_h1")
    if ta is not None and ta > 1:
        factors.append(Factor("O4_txn_accel", "activity", "Transações acelerando vs média de 6h", 15 * _clip01((ta - 1) / 2), "info", 0.6, {"txn_accel_h1": round(ta, 3)}))
    pc = f.get("price_change_h1")
    if pc is not None:
        if 0 < pc <= 100:
            factors.append(Factor("O5_momentum", "market", "Momento de preço positivo (1h)", 15 * _clip01(pc / 30), "info", 0.5, {"price_change_h1": pc}))
        elif pc > 200:
            factors.append(Factor("O5_exhaustion", "market", "Alta > 200% em 1h: risco de exaustão", 0, "low", 0.5, {"price_change_h1": pc}))
    liq = f.get("liquidity_usd")
    if liq is not None:
        if liq >= 50_000:
            factors.append(Factor("O6_depth", "liquidity", "Liquidez ≥ US$ 50 mil", 15, "info", 0.9, {"liquidity_usd": liq}))
        elif liq >= 20_000:
            factors.append(Factor("O6_depth", "liquidity", "Liquidez ≥ US$ 20 mil", 8, "info", 0.9, {"liquidity_usd": liq}))
        inval.append(f"liquidez cair mais de 30% (abaixo de US$ {liq * 0.7:,.0f})")
    lt = f.get("liquidity_trend_1h")
    if lt is not None and lt >= 0.1:
        factors.append(Factor("O7_liquidity_growth", "liquidity", "Liquidez crescendo ≥ 10% em 1h", 10, "info", 0.7, {"liquidity_trend_1h": round(lt, 4)}))

    raw = sum(x.points for x in factors)
    score = raw
    penalty = 0.5 * max(0.0, risk.score - 25)
    if penalty > 0:
        factors.append(Factor("P1_risk_penalty", "risk", "Penalidade pelo score de risco", -penalty, "info", 1.0, {"risk_score": risk.score}))
        score -= penalty
    if liq is None or liq < 10_000:
        if score > 30:
            factors.append(Factor("P2_shallow_pool_cap", "liquidity", "Pool raso: score limitado a 30 (saída pode ser inviável)", -(score - 30), "info", 1.0, {"liquidity_usd": liq}))
            score = 30
    if risk.insufficient_data and score > 40:
        factors.append(Factor("P3_insufficient_data_cap", "data", "Dados insuficientes: score limitado a 40", -(score - 40), "info", 1.0))
        score = 40
    inval.append("surgir autoridade de mint/freeze ou queda brusca de liquidez")
    confidence = round((present / len(required)) * (0.5 + 0.5 * risk.coverage), 3)
    return OpportunityResult(round(max(0.0, score), 2), round(raw, 2), confidence, factors, inval)
