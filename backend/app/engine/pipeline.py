"""Orquestra a análise de um token: features -> scores -> alertas -> previsões."""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SecurityReport
from app.safety.service import apply_to_decision, detect_rug
from app.engine.scoring import Factor, risk_level
from app.config import get_settings
from app.db import utcnow
from app.engine import burst, checks, outcomes, signals
from app.engine.alerts import AlertCandidate, evaluate_rules, resolve_absent, upsert_alert
from app.engine.features import SnapshotView, compute_features
from app.engine.predict import maybe_create_predictions
from app.engine.scoring import ENGINE_VERSION, score_opportunity, score_risk
from app.ingest.service import source_status
from app.models import Alert, Analysis, Pair, PairSnapshot, RiskCheck, Signal, Token

log = logging.getLogger(__name__)

FEATURE_LOOKBACK = timedelta(hours=2)
# Só persiste nova análise se mudou de forma relevante ou passou este intervalo.
MIN_PERSIST_INTERVAL = timedelta(minutes=5)
MIN_SCORE_DELTA = 5.0
INSUFFICIENT_DATA_GRACE = timedelta(hours=1)


def fresh_enough(features: dict) -> bool:
    age = features.get("data_age_seconds")
    return age is not None and age <= get_settings().fresh_max_age_seconds


def _check_dict(c: RiskCheck | None) -> dict | None:
    if c is None:
        return None
    return {"status": c.status, "result": c.result or {}, "checked_at": c.checked_at.isoformat()}


def _mint_checks(db: Session, token_id: int, as_of: datetime) -> tuple[RiskCheck | None, RiskCheck | None]:
    rows = db.scalars(
        select(RiskCheck)
        .where(
            RiskCheck.token_id == token_id,
            RiskCheck.check_type == checks.CHECK_MINT,
            RiskCheck.status.in_(("ok", "flagged")),
            RiskCheck.checked_at <= as_of,
        )
        .order_by(RiskCheck.checked_at.desc(), RiskCheck.id.desc())
        .limit(2)
    ).all()
    latest_any = db.scalar(
        select(RiskCheck)
        .where(RiskCheck.token_id == token_id, RiskCheck.check_type == checks.CHECK_MINT, RiskCheck.checked_at <= as_of)
        .order_by(RiskCheck.checked_at.desc(), RiskCheck.id.desc())
        .limit(1)
    )
    # Se a última tentativa falhou, ainda usamos a última verificação válida.
    cur = rows[0] if rows else latest_any
    prev = rows[1] if len(rows) > 1 else None
    return cur, prev


def _latest_holders(db: Session, token_id: int, as_of: datetime) -> RiskCheck | None:
    valid = db.scalar(
        select(RiskCheck)
        .where(
            RiskCheck.token_id == token_id,
            RiskCheck.check_type == checks.CHECK_HOLDERS,
            RiskCheck.status.in_(("ok", "flagged")),
            RiskCheck.checked_at <= as_of,
        )
        .order_by(RiskCheck.checked_at.desc(), RiskCheck.id.desc())
        .limit(1)
    )
    if valid:
        return valid
    return db.scalar(
        select(RiskCheck)
        .where(RiskCheck.token_id == token_id, RiskCheck.check_type == checks.CHECK_HOLDERS, RiskCheck.checked_at <= as_of)
        .order_by(RiskCheck.checked_at.desc(), RiskCheck.id.desc())
        .limit(1)
    )


def build_analysis(db: Session, token: Token, as_of: datetime | None = None) -> tuple[dict, object, object, dict | None, dict | None, PairSnapshot | None, Pair | None]:
    as_of = as_of or utcnow()
    pair = db.get(Pair, token.primary_pair_id) if token.primary_pair_id else None
    snaps: list[PairSnapshot] = []
    if pair:
        snaps = db.scalars(
            select(PairSnapshot)
            .where(
                PairSnapshot.pair_id == pair.id,
                PairSnapshot.received_at <= as_of,
                PairSnapshot.received_at >= as_of - FEATURE_LOOKBACK,
            )
            .order_by(PairSnapshot.received_at)
        ).all()
    features = compute_features([SnapshotView.from_model(s) for s in snaps], pair.pair_created_at if pair else None, as_of)
    mint_cur, mint_prev = _mint_checks(db, token.id, as_of)
    holders = _latest_holders(db, token.id, as_of)
    mint_d, prev_d, holders_d = _check_dict(mint_cur), _check_dict(mint_prev), _check_dict(holders)
    risk = score_risk(features, mint_d, holders_d, token.chain_id)
    opp = score_opportunity(features, risk)
    return features, risk, opp, mint_d, prev_d, (snaps[-1] if snaps else None), pair


def analyze_token(db: Session, token: Token, as_of: datetime | None = None, force: bool = False) -> Analysis | None:
    as_of = as_of or utcnow()
    features, risk, opp, mint_d, prev_d, snap, pair = build_analysis(db, token, as_of)
    if not token.rugged_at and (rug := detect_rug(features)):
        token.rugged_at, token.rug_reason = as_of, rug
    if token.rugged_at:  # a marca nunca expira: a janela de 1 h das outras regras esquecia o golpe
        risk.factors.append(Factor("R1_rugged", "market", f"Golpe detectado: {token.rug_reason or 'queda brusca'}", 100, "critical", 0.9, {}))
        risk.score, risk.level = 100.0, risk_level(100.0)

    last = db.scalar(
        select(Analysis).where(Analysis.token_id == token.id).order_by(Analysis.computed_at.desc()).limit(1)
    )
    if not force and last is not None:
        recent = as_of - last.computed_at < MIN_PERSIST_INTERVAL
        similar = (
            abs(last.risk_score - risk.score) < MIN_SCORE_DELTA
            and abs(last.opportunity_score - opp.score) < MIN_SCORE_DELTA
            and last.risk_level == risk.level
        )
        if recent and similar:
            return None

    analysis = Analysis(
        token_id=token.id, pair_id=pair.id if pair else None, snapshot_id=snap.id if snap else None,
        computed_at=as_of, engine_version=ENGINE_VERSION,
        risk_score=risk.score, risk_level=risk.level, risk_confidence=risk.confidence,
        opportunity_score=opp.score, opportunity_confidence=opp.confidence,
        risk_factors=[f.as_dict() for f in risk.factors],
        opportunity_factors=[f.as_dict() for f in opp.factors],
        checks_not_performed=risk.checks_not_performed,
        data_quality={
            "coverage": risk.coverage,
            "insufficient_data": risk.insufficient_data,
            "history_points": features.get("history_points", 0),
            "history_span_minutes": features.get("history_span_minutes"),
            "data_age_seconds": features.get("data_age_seconds"),
            "missing_fields": snap.missing_fields if snap else None,
        },
        features=features,
        invalidation_conditions=opp.invalidation_conditions,
    )
    db.add(analysis)
    db.flush()

    candidates = evaluate_rules(features, risk, opp, mint_d, prev_d)
    if as_of - token.first_seen_at < INSUFFICIENT_DATA_GRACE:
        # Todo token novo começa sem histórico/verificações; só alerta se persistir.
        candidates = [c for c in candidates if c.alert_type != "insufficient_data"]

    detected = burst.detect(features)
    if detected and fresh_enough(features) and not token.rugged_at:
        stats = burst.pattern_stats(db, as_of)
        extreme = detected["strength"] == "extreme"
        candidates.append(AlertCandidate(
            "pump_burst", "critical" if extreme else "high",
            "Disparo agora: alta forte em andamento" if extreme else "Disparo agora: volume e compras acelerando",
            "; ".join(detected["reasons"]),
            {**detected["evidence"], "strength": detected["strength"], "pattern_stats": stats},
            0.5, snap.received_at if snap else None,
        ))

    estimates = outcomes.estimate(db, analysis.opportunity_score, analysis.risk_score, as_of)
    prev = db.scalar(select(Signal).where(Signal.token_id == token.id, Signal.status == "active").limit(1))
    decision = signals.decide(analysis, features, estimates, fresh_enough(features),
                              previous=(prev.action, prev.strength) if prev else None)
    if get_settings().security_gate:
        report = db.get(SecurityReport, token.id)
        decision = apply_to_decision(decision, report.verdict if report else None)
    sig, _ = signals.upsert_signal(db, token.id, analysis, decision, estimates, features.get("price_usd"))
    sig_alert = signals.alert_for(sig)
    if sig_alert:
        candidates.append(sig_alert)
    for c in candidates:
        upsert_alert(db, c, token.id, pair.id if pair else None, analysis.id)
    resolve_absent(db, token.id, {c.alert_type for c in candidates})
    if pair:
        maybe_create_predictions(db, token.id, pair.id, analysis, features, snap.id if snap else None)
    db.commit()
    return analysis


def analyze_tokens(db: Session, token_ids: set[int] | list[int], as_of: datetime | None = None) -> int:
    n = 0
    for tid in token_ids:
        tok = db.get(Token, tid)
        if tok is None:
            continue
        try:
            if analyze_token(db, tok, as_of) is not None:
                n += 1
        except Exception:
            db.rollback()
            log.exception("falha ao analisar token %s", tid)
    return n


def sync_source_alerts(db: Session, sources: tuple[str, ...]) -> None:
    """Abre alerta de sistema quando a fonte cai; resolve quando volta."""
    for src in sources:
        st = source_status(db, src)
        key = f"source_unavailable:system:{src}"
        open_alert = db.scalar(
            select(Alert).where(Alert.dedup_key == key, Alert.status.in_(("open", "acknowledged"))).limit(1)
        )
        if st["status"] == "down":
            if open_alert:
                open_alert.occurrences += 1
                open_alert.last_occurrence_at = utcnow()
                open_alert.evidence = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in st.items()}
            else:
                cand = AlertCandidate(
                    "source_unavailable", "high", f"Fonte indisponível: {src}",
                    f"{st['consecutive_failures']} falhas consecutivas. Dados desta fonte podem estar desatualizados.",
                    {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in st.items()}, 1.0,
                )
                a, _ = upsert_alert(db, cand, None, None, None)
                a.dedup_key = key
        elif open_alert and st["status"] == "ok":
            open_alert.status = "resolved"
            open_alert.status_changed_at = utcnow()
    db.commit()
