"""Regras e varredura de segurança (`sec-1`). Limiares fixos e explícitos, não calibrados.

PERIGO (bloqueia compra): golpe já detectado; mint/freeze ativos; liquidez destravada em pool onde
isso é confiável; um dono com ≥ 20%; 10 maiores com ≥ 50%; rede de insiders com ≥ 20%; carteiras
novas ou de mesma origem com ≥ 30%; liquidez < 2% do valor de mercado em moeda de menos de 7 dias
valendo ≥ US$ 1 mi; atividade artificial nas duas medidas ao mesmo tempo.
ATENÇÃO (compra no máximo moderada): os mesmos sinais em nível menor, ou nome que imita algo oficial.
SEM ALERTAS: nada encontrado no que foi possível verificar. Não significa seguro.
"""
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.live import service as live
from app.models import Analysis, Pair, PairSnapshot, Position, SecurityReport, ServiceHeartbeat, Signal, Token, WalletProfile
from app.safety.sources import RugCheckClient, WalletRpc, parse_report

RULES_VERSION = "sec-1"
SERVICE_NAME = "security"
LABELS = {"danger": "Perigo", "caution": "Atenção", "clear": "Sem alertas", "unknown": "Sem dados"}
ORDER = {"unknown": 0, "ok": 0, "warn": 1, "danger": 2}
FRESH_HOURS = 48
CANDIDATE_RECHECK = timedelta(minutes=10)
DEEP_WALLETS = 10
ACTIVITY_WINDOW = timedelta(hours=6)
RECHECK_OPEN = timedelta(minutes=2)
RECHECK_BUY = timedelta(minutes=5)
RECHECK_OTHER = timedelta(hours=6)
WALLET_RECHECK = timedelta(hours=6)
OFFICIAL_NAMES = re.compile(r"\b(united states|treasury|federal|government|\bgov\b|official|sec\b|etf|dividend fund|reserve)\b", re.I)
STABLE_TICKER = re.compile(r"^(usd[a-z0-9]{0,2}|[a-z]usd|tether|dai)$", re.I)
LIMITATIONS = [
    "Nenhuma verificação garante que a moeda é segura: golpes novos passam despercebidos.",
    "Carteira nova só conta quando confirmada no histórico completo do RPC oficial, que é bem limitado: muitas ficam como idade desconhecida.",
    "Carteiras muito ativas (100 transações ou mais em ~63 h) também ficam sem idade conhecida.",
    "Origem do dinheiro vem da 1ª transação da carteira. Duas carteiras pagas pela mesma corretora podem parecer ligadas sem ser.",
    "Só as maiores carteiras são analisadas. Muitas carteiras pequenas não aparecem no mapa.",
    "Liquidez travada pode vir zerada em pools Meteora; nesses casos conta só como atenção.",
]


def _check(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _by_limit(value: float, warn: float, danger: float) -> str:
    return "danger" if value >= danger else "warn" if value >= warn else "ok"


def activity_facts(snaps: list[PairSnapshot]) -> dict:
    """Atividade artificial: operações muito pequenas e contagem por hora constante demais."""
    pts = [s for s in snaps if s.buys_h1 is not None and s.sells_h1 is not None]
    if not pts:
        return {"available": False}
    last = pts[-1]
    txns = last.buys_h1 + last.sells_h1
    avg = last.volume_h1 / txns if last.volume_h1 and txns else None
    span = (pts[-1].received_at - pts[0].received_at).total_seconds() / 3600
    counts = [p.buys_h1 + p.sells_h1 for p in pts]
    cv = statistics.pstdev(counts) / statistics.mean(counts) if len(pts) >= 6 and span >= 2 and statistics.mean(counts) else None
    return {"available": True, "txns_h1": txns, "avg_trade_usd": round(avg, 2) if avg else None,
            "micro": bool(avg is not None and txns >= 500 and avg < 15),
            "constant": bool(cv is not None and txns >= 300 and cv < 0.05), "count_cv": round(cv, 4) if cv is not None else None}


def assess(token: Token, rc: dict | None, wallets: dict | None, activity: dict, market: dict) -> tuple[str, list[dict]]:
    """Regra pura: dos fatos para o veredito e a lista de itens. Sem dado vira "unknown", nunca "ok"."""
    c: list[dict] = []
    if token.rugged_at:
        c.append(_check("rugged", "Golpe", "danger", f"Golpe detectado: {token.rug_reason or 'queda brusca de preço e liquidez'}."))
    if rc is None:
        c.append(_check("rugcheck", "Liquidez e donos", "unknown", "RugCheck não respondeu nesta verificação."))
    else:
        if rc["rugged"]:
            c.append(_check("rugcheck_rug", "Golpe", "danger", "A RugCheck marcou esta moeda como golpe."))
        auth = [n for n, v in (("mint", rc["mint_authority"]), ("freeze", rc["freeze_authority"])) if v]
        c.append(_check("authority", "Autoridades", "danger", f"Autoridade de {' e '.join(auth)} ativa: o dono pode criar moedas ou travar sua carteira.") if auth
                 else _check("authority", "Autoridades", "ok", "Mint e freeze revogados."))
        lp = rc["lp"]
        if not lp or lp["locked_pct"] is None:
            c.append(_check("lp", "Liquidez travada", "unknown", "Sem dado de liquidez travada (moeda ainda na curva ou sem pool)."))
        else:
            pct = lp["locked_pct"]
            status = "ok" if pct >= 90 else ("danger" if lp["reliable"] and pct < 50 else "warn")
            c.append(_check("lp", "Liquidez travada", status, f"{pct:.0f}% travada ({lp['type']}). O que não está travado pode ser retirado."))
        holders = rc["holders"]
        if holders:
            top = max(h["pct"] for h in holders)
            top10 = sum(h["pct"] for h in sorted(holders, key=lambda h: -h["pct"])[:10])
            c.append(_check("top1", "Maior dono", _by_limit(top, 10, 20), f"A maior carteira tem {top:.1f}% das moedas (sem contar a pool)."))
            c.append(_check("top10", "10 maiores", _by_limit(top10, 30, 50), f"As 10 maiores têm {top10:.1f}% das moedas."))
        else:
            c.append(_check("top1", "Maiores donos", "unknown", "Lista de donos indisponível."))
        nets = [n for n in rc["networks"] if n["pct"] is not None]
        if nets:
            biggest = max(nets, key=lambda n: n["pct"])
            c.append(_check("insiders", "Insiders", _by_limit(biggest["pct"], 10, 20), f"Rede de {biggest['size']} carteiras ligadas com {biggest['pct']:.1f}% das moedas."))
        elif rc["insiders_detected"]:
            c.append(_check("insiders", "Insiders", "warn", f"{rc['insiders_detected']:.0f} carteiras ligadas detectadas."))
        else:
            c.append(_check("insiders", "Insiders", "ok", "Nenhuma rede de carteiras detectada pela RugCheck."))
    if wallets is None:
        c.append(_check("fresh", "Carteiras novas", "unknown", "Ainda não analisadas nesta moeda."))
    else:
        if wallets["analyzed"]:
            c.append(_check("fresh", "Carteiras novas", _by_limit(wallets["fresh_pct"], 15, 30),
                            f"{wallets['fresh_count']} de {wallets['analyzed']} carteiras analisadas têm menos de {FRESH_HOURS} h e somam {wallets['fresh_pct']:.1f}%."))
        else:
            c.append(_check("fresh", "Carteiras novas", "unknown", "Nenhuma carteira grande com idade conhecida."))
        if wallets["cluster_size"] >= 2:
            c.append(_check("cluster", "Mesma origem", _by_limit(wallets["cluster_pct"], 10, 30),
                            f"{wallets['cluster_size']} carteiras receberam da mesma origem e somam {wallets['cluster_pct']:.1f}%."))
    liq_cap, age, cap = market.get("liq_to_mcap"), market.get("age_hours"), market.get("market_cap")
    if liq_cap is None:
        c.append(_check("depth", "Liquidez x valor", "unknown", "Sem dado de mercado."))
    else:
        young_big = bool(age is not None and age < 24 * 7 and cap is not None and cap >= 1_000_000)
        status = "danger" if liq_cap < 0.02 and young_big else "warn" if liq_cap < 0.05 else "ok"
        c.append(_check("depth", "Liquidez x valor", status, f"Liquidez é {liq_cap * 100:.1f}% do valor de mercado."))
    if not activity.get("available"):
        c.append(_check("activity", "Atividade", "unknown", "Sem histórico de operações."))
    else:
        flags = int(activity["micro"]) + int(activity["constant"])
        detail = {2: "Parece robô: operações minúsculas e quantidade por hora quase igual.", 1: "Operações minúsculas." if activity["micro"] else "Quantidade de operações por hora quase igual."}.get(flags, "Sem padrão artificial nas medidas disponíveis.")
        c.append(_check("activity", "Atividade", {2: "danger", 1: "warn"}.get(flags, "ok"), detail))
    text = f"{token.name or ''}"
    if OFFICIAL_NAMES.search(text) or STABLE_TICKER.match(token.symbol or ""):
        c.append(_check("name", "Nome", "warn", f"\"{token.symbol or text}\" imita algo oficial ou uma stablecoin."))
    statuses = {x["status"] for x in c}
    if "danger" in statuses:
        return "danger", c
    if "warn" in statuses:
        return "caution", c
    # Sem a fonte principal não há base para dizer "sem alertas".
    return ("unknown" if rc is None else "clear"), c


def _wallet_facts(db: Session, holders: list[dict], rpc: WalletRpc, now: datetime) -> dict:
    top = sorted(holders, key=lambda h: -h["pct"])[:DEEP_WALLETS]
    fresh_pct, fresh_count, analyzed = 0.0, 0, 0
    for h in top:
        prof = db.get(WalletProfile, h["owner"])
        stale = prof is not None and not prof.complete and now - prof.checked_at > (CANDIDATE_RECHECK if prof.signatures < 100 else WALLET_RECHECK)
        if prof is None or stale:
            got = rpc.profile(h["owner"])
            if got is None:
                continue
            first = datetime.fromtimestamp(got["first_seen_ts"], tz=now.tzinfo) if got["first_seen_ts"] else None
            prof = prof or WalletProfile(address=h["owner"], checked_at=now, signatures=0, complete=False)
            prof.first_seen_at, prof.signatures, prof.complete, prof.funder, prof.checked_at = first, got["signatures"], got["complete"], got["funder"], now
            db.merge(prof)
            db.commit()
        h["funder"] = prof.funder
        h["signatures"] = prof.signatures
        if prof.complete:
            age = (now - prof.first_seen_at).total_seconds() / 3600 if prof.first_seen_at else None
            h["age_hours"] = round(age, 1) if age is not None else None
            # Sem data e definitivo = parada desde antes da janela do histórico.
            h["fresh"] = age is not None and age < FRESH_HOURS
            analyzed += 1
            if h["fresh"]:
                fresh_count += 1
                fresh_pct += h["pct"]
    funders = Counter(h["funder"] for h in top if h.get("funder"))
    group, size = funders.most_common(1)[0] if funders else (None, 0)
    cluster_pct = sum(h["pct"] for h in top if group and h.get("funder") == group) if size >= 2 else 0.0
    for h in top:
        if size >= 2 and h.get("funder") == group:
            h["cluster"] = 1
    return {"analyzed": analyzed, "fresh_count": fresh_count, "fresh_pct": round(fresh_pct, 2), "cluster_size": size if size >= 2 else 0,
            "cluster_pct": round(cluster_pct, 2)}


def scan(db: Session, token: Token, deep: bool, client: RugCheckClient | None = None, rpc: WalletRpc | None = None,
         now: datetime | None = None) -> SecurityReport:
    now = now or utcnow()
    res = (client or RugCheckClient()).report(token.address)
    rc = parse_report(res.data) if res.ok else None
    previous = db.get(SecurityReport, token.id)
    wallets = None
    holders = rc["holders"] if rc else []
    if rc and deep and holders:
        wallets = _wallet_facts(db, holders, rpc or WalletRpc(), now)
    elif previous and previous.facts.get("wallets"):
        wallets = previous.facts["wallets"]
    pair = db.get(Pair, token.primary_pair_id) if token.primary_pair_id else None
    snaps = list(db.scalars(select(PairSnapshot).where(PairSnapshot.pair_id == pair.id, PairSnapshot.received_at >= now - ACTIVITY_WINDOW)
                            .order_by(PairSnapshot.received_at))) if pair else []
    last = snaps[-1] if snaps else None
    mcap = (last.market_cap or last.fdv) if last else None
    market = {"liq_to_mcap": last.liquidity_usd / mcap if last and last.liquidity_usd is not None and mcap else None,
              "market_cap": mcap, "age_hours": (now - pair.pair_created_at).total_seconds() / 3600 if pair and pair.pair_created_at else None}
    activity = activity_facts(snaps)
    verdict, checks = assess(token, rc, wallets, activity, market)
    if rc and rc["rugged"] and not token.rugged_at:
        token.rugged_at, token.rug_reason = now, "marcada como golpe pela RugCheck"
    # Falha da fonte não apaga o último mapa bom.
    keep_holders = holders or (previous.holders if previous else [])
    report = previous or SecurityReport(token_id=token.id)
    report.checked_at, report.verdict, report.checks, report.holders = now, verdict, checks, sorted(keep_holders, key=lambda h: -h["pct"])[:30]
    report.facts = {"wallets": wallets, "activity": activity, "market": market, "rugcheck_score": rc["score_normalised"] if rc else None,
                    "total_holders": rc["total_holders"] if rc else None, "networks": rc["networks"] if rc else [],
                    "rugcheck_risks": rc["risks"] if rc else [], "rugcheck_error": None if res.ok else res.error}
    report.rules_version = RULES_VERSION
    db.add(report)
    db.commit()
    return report


def next_target(db: Session, now: datetime | None = None) -> tuple[Token, bool] | None:
    """Próxima moeda: aberta agora > com sinal de compra ou posição > mais quentes sem verificação."""
    now = now or utcnow()
    done = {tid: at for tid, at in db.execute(select(SecurityReport.token_id, SecurityReport.checked_at))}
    due = lambda t, age: t.id not in done or now - done[t.id] >= age  # noqa: E731
    for t in live.focused_tokens(db, now):
        if due(t, RECHECK_OPEN):
            return t, True
    urgent = db.scalars(select(Token).join(Signal, Signal.token_id == Token.id)
                        .where(Signal.status == "active", Signal.action == "buy", Token.chain_id == "solana")).all()
    urgent = [*urgent, *db.scalars(select(Token).join(Position, Position.token_id == Token.id).where(Token.chain_id == "solana"))]
    # Primeiro o veredito rápido de todas (segundos); as carteiras, mais demoradas, vêm depois.
    never = [t for t in urgent if t.id not in done]
    if never:
        return never[0], False
    no_wallets = [t for t in urgent if not (db.get(SecurityReport, t.id).facts or {}).get("wallets")]
    if no_wallets:
        return no_wallets[0], True
    pending = [t for t in urgent if due(t, RECHECK_BUY)]
    if pending:
        return min(pending, key=lambda t: done[t.id]), True
    hot = db.scalars(select(Token).where(Token.is_tracked.is_(True), Token.chain_id == "solana").order_by(Token.heat.desc()).limit(1500)).all()
    for t in hot:
        if due(t, RECHECK_OTHER):
            return t, False
    return None


def beat(db: Session, error: str | None = None, now: datetime | None = None) -> None:
    now = now or utcnow()
    hb = db.get(ServiceHeartbeat, SERVICE_NAME) or ServiceHeartbeat(name=SERVICE_NAME, started_at=now, interval_seconds=5, watched=0, quoted=0)
    hb.last_tick_at, hb.last_error = now, error
    if error is None:
        hb.last_ok_at = now
    db.add(hb)
    db.commit()


def running(db: Session, now: datetime | None = None) -> bool:
    hb = db.get(ServiceHeartbeat, SERVICE_NAME)
    return bool(hb and hb.last_tick_at and (now or utcnow()) - hb.last_tick_at <= timedelta(minutes=3))


# ---------------- O que o resto do sistema usa ----------------
def apply_to_decision(decision: dict, verdict: str | None) -> dict:
    """Trava da compra: sem verificação ou com atenção, no máximo moderada; com perigo, não compra."""
    if decision.get("action") != "buy":
        return decision
    if verdict == "danger":
        return {**decision, "action": "avoid", "strength": "moderate", "headline": "Evitar: sinais de golpe", "reasons": ["Verificação de segurança encontrou perigo"]}
    if decision.get("strength") == "strong" and verdict != "clear":
        why = "Verificação de segurança encontrou pontos de atenção" if verdict == "caution" else "Segurança ainda não verificada"
        return {**decision, "strength": "moderate", "reasons": [*decision.get("reasons", []), why]}
    return decision


def mark_past_rugs(db: Session) -> list[Token]:
    """Aplica `detect_rug` ao histórico de análises: golpes de antes desta regra também ficam marcados."""
    rows = db.execute(select(Analysis.token_id, Analysis.computed_at, Analysis.features).where(
        func.json_extract(Analysis.features, "$.price_change_h1") <= -70,
        func.json_extract(Analysis.features, "$.liquidity_change_vs_max_1h") <= -0.6,
    ).order_by(Analysis.computed_at)).all()
    marked = []
    for token_id, at, features in rows:
        token = db.get(Token, token_id)
        reason = detect_rug(features or {})
        if token and reason and not token.rugged_at:
            token.rugged_at, token.rug_reason = at, reason
            marked.append(token)
    db.commit()
    return marked


def detect_rug(features: dict) -> str | None:
    """Queda conjunta de preço e liquidez em 1 h: padrão de retirada de liquidez."""
    price, liq = features.get("price_change_h1"), features.get("liquidity_change_vs_max_1h")
    if features.get("history_points_1h", 0) >= 2 and price is not None and liq is not None and price <= -70 and liq <= -0.6:
        return f"preço caiu {abs(price):.0f}% e a liquidez {abs(liq) * 100:.0f}% em 1 h"
    return None
