"""Previsões favoritadas (`fav-1`): registro do ganho no momento do clique e relatório para análise.

- Ao favoritar, grava uma FOTO imutável: preço, ganho até ali, pior e melhor momento desde o
  sinal, e as especificações do motor naquele instante (scores, fatores, mercado, regras).
- GANHO = variação do preço desde o preço de referência do sinal (preço quando foi emitido).
  É bruto: sem taxas nem slippage. Em sinal de VENDER/EVITAR, queda significa que o sinal acertou.
- Depois do clique o ganho NÃO continua contando: o favorito guarda só aquele instante.
  Sem dado, o valor fica nulo: nunca é preenchido com zero.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, Favorite, LiveQuote, Pair, PairSnapshot, SecurityReport, Signal, Token, User

RULES_VERSION = "fav-1"
LIVE_MAX_AGE = timedelta(seconds=30)
DISCLAIMER = "Ganhos brutos, sem taxas nem slippage. Registro informativo; resultado passado não garante resultado futuro."
TIER_LABELS = {("buy", "strong"): "Compra prioritária", ("buy", "moderate"): "Compra possível"}
ACTION_LABELS = {"buy": "Compra possível", "sell": "Venda (queda)", "avoid": "Evitar", "hold": "Observar"}
PREDICTIONS = {"buy": "Deve subir", "sell": "Deve descer", "avoid": "Risco alto: evitar", "hold": "Sem sinal claro"}
SNAPSHOT_MARKET = ("price_usd", "price_native", "liquidity_usd", "liquidity_base", "liquidity_quote", "fdv", "market_cap",
                   "volume_m5", "volume_h1", "volume_h6", "volume_h24", "buys_m5", "sells_m5", "buys_h1", "sells_h1",
                   "buys_h6", "sells_h6", "buys_h24", "sells_h24", "price_change_m5", "price_change_h1",
                   "price_change_h6", "price_change_h24")


def tier_label(action: str | None, strength: str | None) -> str:
    return TIER_LABELS.get((action, strength)) or ACTION_LABELS.get(action or "", "Sem sinal")


def gain(price: float | None, reference: float | None) -> float | None:
    return round(price / reference - 1, 6) if price and reference else None


def latest_snapshot(db: Session, token: Token) -> PairSnapshot | None:
    if not token.primary_pair_id:
        return None
    return db.scalar(select(PairSnapshot).where(PairSnapshot.pair_id == token.primary_pair_id)
                     .order_by(PairSnapshot.received_at.desc()).limit(1))


def current_price(db: Session, token: Token, now: datetime) -> dict:
    """Cotação rápida de até 30 s; senão, o último preço do coletor."""
    q = db.scalar(select(LiveQuote).where(LiveQuote.token_id == token.id).order_by(LiveQuote.received_at.desc()).limit(1))
    if q is not None and now - q.received_at <= LIVE_MAX_AGE:
        return {"price": q.price_usd, "source": q.source, "at": q.received_at}
    snap = latest_snapshot(db, token)
    if snap is not None and snap.price_usd:
        return {"price": snap.price_usd, "source": snap.source, "at": snap.received_at}
    return {"price": None, "source": None, "at": None}


def extremes(db: Session, token: Token, start: datetime, end: datetime) -> dict:
    """Maior e menor preço observados na janela (coletor + cotações rápidas)."""
    points: list[tuple[float, datetime]] = []
    if token.primary_pair_id:
        for col in (PairSnapshot.price_usd.desc(), PairSnapshot.price_usd.asc()):
            row = db.execute(select(PairSnapshot.price_usd, PairSnapshot.received_at)
                             .where(PairSnapshot.pair_id == token.primary_pair_id, PairSnapshot.price_usd.is_not(None),
                                    PairSnapshot.received_at >= start, PairSnapshot.received_at <= end)
                             .order_by(col).limit(1)).first()
            if row:
                points.append((row[0], row[1]))
    for col in (LiveQuote.price_usd.desc(), LiveQuote.price_usd.asc()):
        row = db.execute(select(LiveQuote.price_usd, LiveQuote.received_at)
                         .where(LiveQuote.token_id == token.id, LiveQuote.received_at >= start, LiveQuote.received_at <= end)
                         .order_by(col).limit(1)).first()
        if row:
            points.append((row[0], row[1]))
    if not points:
        return {"max": None, "max_at": None, "min": None, "min_at": None}
    hi, lo = max(points, key=lambda p: p[0]), min(points, key=lambda p: p[0])
    return {"max": hi[0], "max_at": hi[1], "min": lo[0], "min_at": lo[1]}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def capture(db: Session, user: User, token: Token, signal: Signal | None, now: datetime) -> Favorite:
    """Grava a foto da previsão no momento do clique."""
    px = current_price(db, token, now)
    signal_at = signal.created_at if signal else now
    reference = (signal.reference_price_usd if signal else None) or px["price"]
    ext = extremes(db, token, signal_at, now)
    snap = latest_snapshot(db, token)
    a = db.scalar(select(Analysis).where(Analysis.token_id == token.id).order_by(Analysis.computed_at.desc()).limit(1))
    pair = db.get(Pair, token.primary_pair_id) if token.primary_pair_id else None
    sec = db.get(SecurityReport, token.id)
    specs = {
        "market": {k: getattr(snap, k) for k in SNAPSHOT_MARKET} | {"observed_at": _iso(snap.received_at)} if snap else None,
        "pair": {"address": pair.pair_address, "dex_id": pair.dex_id, "labels": pair.labels, "quote": pair.quote_symbol,
                 "created_at": _iso(pair.pair_created_at), "url": pair.url} if pair else None,
        "token": {"name": token.name, "symbol": token.symbol, "discovered_via": token.discovered_via,
                  "first_seen_at": _iso(token.first_seen_at)},
        "signal": {"id": signal.id, "status": signal.status, "headline": signal.headline, "reasons": signal.reasons,
                   "risk_score": signal.risk_score, "risk_level": signal.risk_level, "opportunity_score": signal.opportunity_score,
                   "estimates": signal.estimates, "rules_version": signal.rules_version,
                   "last_confirmed_at": _iso(signal.last_confirmed_at)} if signal else None,
        "analysis": {"computed_at": _iso(a.computed_at), "engine_version": a.engine_version, "risk_score": a.risk_score,
                     "risk_level": a.risk_level, "risk_confidence": a.risk_confidence,
                     "opportunity_score": a.opportunity_score, "opportunity_confidence": a.opportunity_confidence,
                     "risk_factors": a.risk_factors, "opportunity_factors": a.opportunity_factors,
                     "checks_not_performed": a.checks_not_performed, "data_quality": a.data_quality,
                     "features": a.features, "invalidation_conditions": a.invalidation_conditions} if a else None,
        "security": {"verdict": sec.verdict, "checked_at": _iso(sec.checked_at), "checks": sec.checks, "holders": sec.holders, "facts": sec.facts} if sec else None,
        "rugged_at": _iso(token.rugged_at),
        "price_source_at_favorite": px["source"], "price_observed_at_favorite": _iso(px["at"]),
    }
    fav = Favorite(
        user_id=user.id, token_id=token.id, signal_id=signal.id if signal else None, favorited_at=now, signal_at=signal_at,
        action=signal.action if signal else None, strength=signal.strength if signal else None,
        headline=signal.headline if signal else None, reasons=(signal.reasons if signal else []) or [],
        reference_price_usd=reference, price_at_favorite=px["price"], gain_at_favorite=gain(px["price"], reference),
        max_gain_until_favorite=gain(ext["max"], reference), min_gain_until_favorite=gain(ext["min"], reference),
        liquidity_at_favorite=snap.liquidity_usd if snap else None, specs=specs, rules_version=RULES_VERSION,
    )
    db.add(fav)
    db.commit()
    return fav


def evaluate(fav: Favorite, token: Token) -> dict:
    """Um favorito como foi gravado no clique. Nada aqui é recalculado depois."""
    return {
        "id": fav.id, "token": token, "link": f"/tokens/{token.chain_id}/{token.address}", "signal_id": fav.signal_id,
        "action": fav.action, "strength": fav.strength, "tier_label": tier_label(fav.action, fav.strength),
        "prediction": PREDICTIONS.get(fav.action or "", "Sem sinal"), "headline": fav.headline, "reasons": fav.reasons or [],
        "signal_at": fav.signal_at, "favorited_at": fav.favorited_at,
        "seconds_signal_to_favorite": round((fav.favorited_at - fav.signal_at).total_seconds(), 1),
        "reference_price_usd": fav.reference_price_usd, "price_at_favorite": fav.price_at_favorite,
        "gain_at_favorite": fav.gain_at_favorite, "max_gain_until_favorite": fav.max_gain_until_favorite,
        "min_gain_until_favorite": fav.min_gain_until_favorite,
        "value_of_100_usd_at_favorite": round(100 * (1 + fav.gain_at_favorite), 2) if fav.gain_at_favorite is not None else None,
        "liquidity_at_favorite": fav.liquidity_at_favorite, "specs": fav.specs or {},
    }


def summarize(items: list[dict]) -> dict:
    rated = [i for i in items if i["gain_at_favorite"] is not None]
    gains = [i["gain_at_favorite"] for i in rated]
    best = max(rated, key=lambda i: i["gain_at_favorite"]) if rated else None
    worst = min(rated, key=lambda i: i["gain_at_favorite"]) if rated else None
    return {"count": len(items), "with_gain": len(rated), "positive": sum(1 for g in gains if g > 0),
            "negative": sum(1 for g in gains if g < 0),
            "avg_gain_at_favorite": round(sum(gains) / len(gains), 6) if gains else None,
            "best_gain": best["gain_at_favorite"] if best else None, "best_symbol": best["token"].symbol if best else None,
            "worst_gain": worst["gain_at_favorite"] if worst else None, "worst_symbol": worst["token"].symbol if worst else None}


def _pct(v: float | None) -> str:
    return "sem dado" if v is None else f"{v * 100:+.2f}%"


def _usd(v: float | None) -> str:
    return "sem dado" if v is None else f"US$ {v:,.10g}"


def _dt(v: datetime | None) -> str:
    return "sem dado" if v is None else f"{v.strftime('%Y-%m-%d %H:%M:%S')} UTC"


def report_text(items: list[dict], summary: dict, now: datetime) -> str:
    """Texto completo para colar na conversa: resumo legível e os dados crus em JSON."""
    lines = ["# MemeCoinAI: previsões favoritadas", f"Gerado em {_dt(now)} · regras {RULES_VERSION}", DISCLAIMER, "",
             "## Resumo",
             f"Favoritos: {summary['count']} ({summary['with_gain']} com ganho registrado)",
             f"Com ganho: {summary['positive']} · Com perda: {summary['negative']}",
             f"Ganho médio no clique: {_pct(summary['avg_gain_at_favorite'])}",
             f"Melhor: {summary['best_symbol'] or 'sem dado'} {_pct(summary['best_gain'])} · Pior: {summary['worst_symbol'] or 'sem dado'} {_pct(summary['worst_gain'])}"]
    for n, i in enumerate(items, 1):
        t = i["token"]
        lines += ["", f"## {n}. {t.symbol or t.name or 'Token'} ({t.chain_id})", f"Endereço: {t.address}",
                  f"Previsão: {i['tier_label']} · {i['prediction']} · {i['headline'] or 'sem título'}",
                  f"Sinal emitido: {_dt(i['signal_at'])}",
                  f"Favoritado: {_dt(i['favorited_at'])} ({i['seconds_signal_to_favorite']:.0f} s depois do sinal)",
                  "",
                  "Ganho registrado no clique (não muda depois):",
                  f"- Preço de referência do sinal: {_usd(i['reference_price_usd'])}",
                  f"- Preço ao favoritar: {_usd(i['price_at_favorite'])}",
                  f"- Ganho até ali: {_pct(i['gain_at_favorite'])}",
                  f"- Melhor momento até ali: {_pct(i['max_gain_until_favorite'])} · Pior momento até ali: {_pct(i['min_gain_until_favorite'])}",
                  f"- US$ 100 no preço do sinal valiam no clique: {_usd(i['value_of_100_usd_at_favorite'])}",
                  f"- Liquidez no clique: {_usd(i['liquidity_at_favorite'])}"]
        if i["reasons"]:
            lines += ["", "Motivos do sinal:", *[f"- {r}" for r in i["reasons"]]]
    raw = [{**{k: v for k, v in i.items() if k != "token"}, "symbol": i["token"].symbol, "address": i["token"].address,
            "chain_id": i["token"].chain_id} for i in items]
    lines += ["", "## Dados completos e especificações (JSON)", "```json",
              json.dumps(raw, ensure_ascii=False, indent=1, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)), "```"]
    return "\n".join(lines)
