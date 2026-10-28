"""Regras de alerta e deduplicação.

Deduplicação: chave = regra + token. Se já existe alerta aberto/reconhecido com
a mesma chave e a severidade não aumentou, apenas incrementamos `occurrences`
e atualizamos `last_occurrence_at` / evidência. Se a severidade aumentou, um
NOVO alerta é criado (mudanças importantes não ficam escondidas).
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Alert

RULES_VERSION = "alerts-1"
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

ALERT_TYPES = {
    "liquidity_drop": "risk",
    "mint_authority_active": "risk",
    "freeze_authority_active": "risk",
    "risky_token_extensions": "risk",
    "permission_change": "risk",
    "holder_concentration": "risk",
    "sell_pressure": "risk",
    "risk_high": "risk",
    "insufficient_data": "risk",
    "volume_spike": "opportunity",
    "opportunity_candidate": "opportunity",
    "source_unavailable": "system",
}


@dataclass
class AlertCandidate:
    alert_type: str
    severity: str
    title: str
    reason: str
    evidence: dict
    confidence: float
    event_at: datetime | None = None
    rule_id: str | None = None

    @property
    def category(self) -> str:
        return ALERT_TYPES[self.alert_type]


def evaluate_rules(features: dict, risk, opportunity, mint_check: dict | None, prev_mint_check: dict | None) -> list[AlertCandidate]:
    out: list[AlertCandidate] = []
    by_id = {f.id: f for f in risk.factors}
    observed = None
    if features.get("observed_at"):
        observed = datetime.fromisoformat(features["observed_at"])

    for fid in ("L2_liquidity_drop_severe", "L2_liquidity_drop"):
        if fid in by_id:
            f = by_id[fid]
            out.append(AlertCandidate(
                "liquidity_drop", "critical" if fid.endswith("severe") else "high",
                "Queda brusca de liquidez",
                f"Liquidez variou {f.evidence['change']:.0%} em relação ao máximo observado na última hora.",
                f.evidence, f.confidence, observed,
            ))
            break
    if "T1_mint_authority" in by_id:
        f = by_id["T1_mint_authority"]
        out.append(AlertCandidate("mint_authority_active", "high", "Autoridade de mint ativa",
            "O mint ainda possui autoridade capaz de emitir novos tokens.", f.evidence, f.confidence, observed))
    if "T2_freeze_authority" in by_id:
        f = by_id["T2_freeze_authority"]
        out.append(AlertCandidate("freeze_authority_active", "high", "Autoridade de freeze ativa",
            "O mint possui autoridade capaz de congelar contas de holders.", f.evidence, f.confidence, observed))
    if "T3_token2022_extensions" in by_id:
        f = by_id["T3_token2022_extensions"]
        out.append(AlertCandidate("risky_token_extensions", "high", "Extensões Token-2022 de risco",
            "O token usa extensões que podem restringir transferências ou permitir ações administrativas.", f.evidence, f.confidence, observed))
    if mint_check and prev_mint_check and mint_check["status"] in ("ok", "flagged") and prev_mint_check["status"] in ("ok", "flagged"):
        cur, prev = mint_check["result"], prev_mint_check["result"]
        changed = {
            k: {"before": prev.get(k), "after": cur.get(k)}
            for k in ("mint_authority", "freeze_authority")
            if prev.get(k) != cur.get(k)
        }
        if changed:
            out.append(AlertCandidate("permission_change", "high", "Permissões do mint alteradas",
                "As autoridades do mint mudaram entre duas verificações.", {"changes": changed}, 0.95, observed))
    for fid in ("C1_concentration_extreme", "C1_concentration_high"):
        if fid in by_id:
            f = by_id[fid]
            out.append(AlertCandidate("holder_concentration", "high" if "extreme" in fid else "medium",
                "Concentração elevada de supply",
                f"Top 10 contas de token detêm {f.evidence['top10_share']:.0%} do supply (inclui cofres de pools não classificados).",
                f.evidence, f.confidence, observed))
            break
    if "A1_sell_pressure" in by_id:
        f = by_id["A1_sell_pressure"]
        out.append(AlertCandidate("sell_pressure", "medium", "Concentração de vendas (possível distribuição)",
            "Número de vendas na última hora é pelo menos o dobro das compras.", f.evidence, f.confidence, observed))
    if risk.score >= 50:
        data_pts = sum(x.points for x in risk.factors if x.category == "data")
        reason = f"Score de risco {risk.score:.0f}/100"
        if data_pts:
            reason += f", dos quais {data_pts:.0f} pontos vêm de verificações não realizadas ou dados ausentes"
        evidence = {"risk_score": risk.score, "data_points": data_pts, "factors": [x.id for x in risk.factors]}
        critical = risk.score >= 75
        out.append(AlertCandidate("risk_high", "critical" if critical else "high",
            "Risco crítico" if critical else "Risco elevado", reason + ".", evidence, risk.confidence, observed))
    if risk.insufficient_data:
        out.append(AlertCandidate("insufficient_data", "low", "Dados insuficientes para avaliar",
            "Menos da metade das verificações planejadas pôde ser executada.", {"checks_not_performed": risk.checks_not_performed}, 1.0, observed))

    va = features.get("volume_accel_h1")
    liq = features.get("liquidity_usd")
    if va is not None and va >= 3 and liq is not None and liq >= 20_000:
        out.append(AlertCandidate("volume_spike", "info", "Pico de volume",
            f"Volume da última hora {va:.1f}x a média horária de 6h.", {"volume_accel_h1": round(va, 3), "liquidity_usd": liq, "volume_h1": features.get("volume_h1")}, 0.7, observed))
    if opportunity.score >= 60 and risk.score < 50 and not risk.insufficient_data:
        out.append(AlertCandidate("opportunity_candidate", "high" if opportunity.score >= 75 else "medium",
            "Oportunidade candidata",
            f"Score de oportunidade {opportunity.score:.0f}/100 com risco {risk.score:.0f}/100. Não é probabilidade de lucro.",
            {"opportunity_score": opportunity.score, "risk_score": risk.score, "factors": [x.id for x in opportunity.factors]},
            opportunity.confidence, observed))
    for c in out:
        c.rule_id = c.rule_id or c.alert_type
    return out


def upsert_alert(
    db: Session, cand: AlertCandidate, token_id: int | None, pair_id: int | None, analysis_id: int | None
) -> tuple[Alert, bool]:
    """Retorna (alerta, criado_novo)."""
    key = f"{cand.alert_type}:{token_id if token_id is not None else 'system'}"
    existing = db.scalar(
        select(Alert)
        .where(Alert.dedup_key == key, Alert.status.in_(("open", "acknowledged")))
        .order_by(Alert.detected_at.desc())
        .limit(1)
    )
    now = utcnow()
    if existing and SEVERITY_ORDER[cand.severity] <= SEVERITY_ORDER[existing.severity]:
        existing.occurrences += 1
        existing.last_occurrence_at = now
        existing.evidence = cand.evidence
        existing.analysis_id = analysis_id or existing.analysis_id
        return existing, False
    alert = Alert(
        token_id=token_id, pair_id=pair_id, analysis_id=analysis_id, alert_type=cand.alert_type,
        category=cand.category, severity=cand.severity, status="open", title=cand.title, reason=cand.reason,
        evidence=cand.evidence, confidence=cand.confidence, rule_id=cand.rule_id or cand.alert_type,
        rule_version=RULES_VERSION, event_at=cand.event_at, detected_at=now, dedup_key=key,
        occurrences=1, last_occurrence_at=now,
    )
    db.add(alert)
    db.flush()
    return alert, True


def resolve_absent(db: Session, token_id: int, active_types: set[str]) -> int:
    """Alertas de condição (não-evento) somem quando a condição deixa de valer.

    Apenas tipos de condição contínua são auto-resolvidos; eventos pontuais
    (permission_change, liquidity_drop) permanecem até ação do usuário.
    """
    condition_types = {
        "mint_authority_active", "freeze_authority_active", "risky_token_extensions", "holder_concentration",
        "sell_pressure", "risk_high", "insufficient_data", "volume_spike", "opportunity_candidate",
    }
    to_resolve = db.scalars(
        select(Alert).where(
            Alert.token_id == token_id,
            Alert.status == "open",
            Alert.alert_type.in_(condition_types - active_types),
        )
    ).all()
    now = utcnow()
    for a in to_resolve:
        a.status = "resolved"
        a.status_changed_at = now
        a.evidence = {**(a.evidence or {}), "auto_resolved": "condição deixou de ser observada"}
    return len(to_resolve)
