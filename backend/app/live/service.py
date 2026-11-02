"""Lógica da atualização rápida (`live-1`): quem acompanhar, cotar, detectar golpe ao vivo.

- ACOMPANHA: tokens com posição registrada (sempre) + tokens cujo quadro "Quando vender"
  pediu o plano nos últimos `live_watch_ttl_seconds` (fechou a tela: para sozinho).
  Só Solana (a fonte é da Solana). Limite `live_max_tokens`, posições primeiro.
- COTA: a cada `live_interval_seconds` (10 s), 1 requisição por bloco de 50 tokens.
  Toda cotação recebida é gravada, mesmo com preço igual: a idade mostrada é "quando
  o preço foi conferido", não "quando mudou".
- GOLPE AO VIVO: compara só cotações rápidas entre si (mesma fonte, mesma medida).
  Liquidez nas 2 últimas cotações ≤ 40% do máximo dos últimos 15 min → retirada de
  liquidez; preço nas 2 últimas ≤ 60% do máximo dos últimos 5 min → despencou.
  Duas leituras seguidas evitam disparo por uma resposta isolada estranha.
"""
import math
import time
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.live import chain
from app.live.jupiter import MAX_IDS_PER_REQUEST, SOURCE_NAME, JupiterPriceClient, parse_quote
from app.models import LiveQuote, LiveWatch, PairSnapshot, Pair, Position, ServiceHeartbeat, Token

RULES_VERSION = "live-1"
SERVICE_NAME = "live"
CHAIN = "solana"
WATCH_WRITE_EVERY = timedelta(seconds=2)  # o quadro consulta a cada 1 s; 2 s bastam para saber que segue aberto
LIQ_WINDOW, LIQ_LEFT = timedelta(minutes=15), 0.40
PRICE_WINDOW, PRICE_LEFT = timedelta(minutes=5), 0.60
PEAK_ARM, PEAK_SELL_ALL = 0.10, 0.08  # arma com +10% e vende ao cair 8% do topo
FADE_MIN_GAIN, FADE_NEAR_TOP, FADE_MIN_TRADES, FADE_SELL_RATIO = 0.20, 0.05, 6, 1.5


# ---------------- Lista de acompanhamento ----------------
def request_watch(db: Session, token_id: int, now: datetime | None = None) -> None:
    """Registra que o quadro deste token está aberto. Grava no máximo a cada 2 s."""
    now = now or utcnow()
    w = db.get(LiveWatch, token_id)
    if w is None:
        db.add(LiveWatch(token_id=token_id, first_requested_at=now, last_requested_at=now))
    elif now - w.last_requested_at >= WATCH_WRITE_EVERY:
        if now - w.last_requested_at > timedelta(seconds=get_settings().live_watch_ttl_seconds):
            w.first_requested_at = now  # reaberto depois de expirar: conta como pedido novo
        w.last_requested_at = now
    else:
        return
    db.commit()


def watched_tokens(db: Session, now: datetime | None = None) -> list[Token]:
    s = get_settings()
    now = now or utcnow()
    with_position = db.scalars(
        select(Token).join(Position, Position.token_id == Token.id)
        .where(Token.chain_id == CHAIN, Position.quantity > 0).distinct()
    ).all()
    on_screen = db.scalars(
        select(Token).join(LiveWatch, LiveWatch.token_id == Token.id)
        .where(Token.chain_id == CHAIN, LiveWatch.last_requested_at >= now - timedelta(seconds=s.live_watch_ttl_seconds))
        .order_by(LiveWatch.last_requested_at.desc())
    ).all()
    out, seen = [], set()
    for t in [*with_position, *on_screen]:
        if t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out[: s.live_max_tokens]


def focused_tokens(db: Session, now: datetime | None = None) -> list[Token]:
    """Moedas abertas agora: têm prioridade máxima (preço a cada ~1 s)."""
    s = get_settings()
    now = now or utcnow()
    return list(db.scalars(
        select(Token).join(LiveWatch, LiveWatch.token_id == Token.id)
        .where(Token.chain_id == CHAIN, LiveWatch.last_requested_at >= now - timedelta(seconds=s.live_focus_ttl_seconds))
        .order_by(LiveWatch.last_requested_at.desc()).limit(s.live_focus_max_tokens)
    ))


class FocusLane:
    """Lê as reservas das moedas abertas e transforma em preço, calibrado pela cotação mais recente."""

    def __init__(self, reader: chain.SolanaPoolReader | None = None):
        self.reader = reader or chain.SolanaPoolReader()
        self.pools: dict[int, tuple[str, chain.PoolRef | None]] = {}  # token -> (par, reservas ou None)
        self.k: dict[int, float] = {}

    def _anchor(self, db: Session, token: Token, now: datetime) -> tuple[float | None, float | None]:
        """(preço de referência, preço do SOL em US$): cotação de 10 s recente, senão o coletor."""
        snap = db.scalar(select(PairSnapshot).where(PairSnapshot.pair_id == token.primary_pair_id)
                         .order_by(PairSnapshot.received_at.desc()).limit(1))
        sol = snap.price_usd / snap.price_native if snap and snap.price_usd and snap.price_native else None
        q = db.scalar(select(LiveQuote).where(LiveQuote.token_id == token.id, LiveQuote.source == SOURCE_NAME,
                                              LiveQuote.received_at >= now - timedelta(seconds=30))
                      .order_by(LiveQuote.received_at.desc()).limit(1))
        return (q.price_usd if q else snap.price_usd if snap else None), sol

    def tick(self, db: Session, tokens: list[Token], now: datetime | None = None) -> dict:
        now = now or utcnow()
        wanted: dict[int, tuple[chain.PoolRef, str]] = {}
        for t in tokens:
            pair = db.get(Pair, t.primary_pair_id) if t.primary_pair_id else None
            if pair is None:
                continue
            known = self.pools.get(t.id)
            if known is None or known[0] != pair.pair_address:
                known = (pair.pair_address, self.reader.resolve(pair.pair_address, t.address))
                self.pools[t.id] = known
                self.k.pop(t.id, None)
            if known[1] is not None:
                wanted[t.id] = (known[1], t.address)
        reserves, error = self.reader.read(wanted)
        quoted = 0
        for t in tokens:
            r = reserves.get(t.id)
            if r is None:
                if t.id in wanted and error is None:
                    self.pools.pop(t.id, None)  # pool esvaziou ou migrou: resolve de novo
                continue
            anchor, sol = self._anchor(db, t, now)
            if not anchor:
                continue
            target = anchor / r["ratio"]
            # Recalibra aos poucos: a referência tem atraso, e um salto não é movimento de mercado.
            k = self.k[t.id] * 0.9 + target * 0.1 if t.id in self.k else target
            self.k[t.id] = k
            db.add(LiveQuote(token_id=t.id, source=chain.SOURCE_NAME, received_at=now, price_usd=r["ratio"] * k,
                             liquidity_usd=chain.liquidity_usd(r, sol)))
            quoted += 1
        if quoted:
            db.commit()
        return {"focused": len(tokens), "quoted": quoted, "error": error}


# ---------------- Ciclo ----------------
def tick(db: Session, client: JupiterPriceClient | None = None, tokens: list[Token] | None = None,
         now: datetime | None = None, record: bool = True) -> dict:
    """Cota os tokens acompanhados (ou os informados) e grava. Nunca levanta por erro da fonte.

    `record=False` (cotação imediata de um quadro recém-aberto) não conta como ciclo no batimento.
    """
    t0 = time.perf_counter()
    s = get_settings()
    client = client or JupiterPriceClient()
    tokens = watched_tokens(db, now) if tokens is None else tokens
    errors, quoted, requests = [], 0, 0
    for i in range(0, len(tokens), MAX_IDS_PER_REQUEST):
        chunk = tokens[i: i + MAX_IDS_PER_REQUEST]
        res = client.prices([t.address for t in chunk])
        requests += 1
        received = now or utcnow()
        if not res.ok:
            errors.append(res.error or "falha sem detalhe")
            continue
        for t in chunk:
            q = parse_quote(res.data.get(t.address))
            if q:
                db.add(LiveQuote(token_id=t.id, source=SOURCE_NAME, received_at=received, **q))
                quoted += 1
        db.commit()  # transação curta por bloco: não segura o banco
    result = {"watched": len(tokens), "quoted": quoted, "requests": requests, "errors": errors}
    if record:
        beat(db, interval=s.live_interval_seconds, watched=len(tokens), quoted=quoted,
             error="; ".join(errors) or None, duration_ms=round((time.perf_counter() - t0) * 1000, 1), now=now)
    return result


def prune(db: Session, now: datetime | None = None) -> int:
    s = get_settings()
    now = now or utcnow()
    n = db.execute(delete(LiveQuote).where(LiveQuote.received_at < now - timedelta(hours=s.live_retention_hours))).rowcount
    db.execute(delete(LiveWatch).where(LiveWatch.last_requested_at < now - timedelta(hours=1)))
    db.commit()
    return n or 0


# ---------------- Batimento ----------------
def beat(db: Session, interval: int, watched: int = 0, quoted: int = 0, error: str | None = None,
         duration_ms: float | None = None, now: datetime | None = None, started: bool = False) -> None:
    now = now or utcnow()
    hb = db.get(ServiceHeartbeat, SERVICE_NAME)
    if hb is None:
        hb = ServiceHeartbeat(name=SERVICE_NAME, started_at=now, interval_seconds=interval)
        db.add(hb)
    if started:
        hb.started_at, hb.last_error = now, None
    else:
        hb.last_tick_at, hb.watched, hb.quoted, hb.last_error = now, watched, quoted, error
        if error is None:
            hb.last_ok_at = now
        if duration_ms is not None:
            hb.last_duration_ms = duration_ms
    hb.interval_seconds = interval
    db.commit()


def service_status(db: Session, now: datetime | None = None) -> dict:
    """running = bateu nos últimos 3 intervalos; stopped = já bateu, mas parou; unknown = nunca rodou."""
    now = now or utcnow()
    interval = get_settings().live_interval_seconds
    hb = db.get(ServiceHeartbeat, SERVICE_NAME)
    if hb is None or hb.last_tick_at is None:
        return {"status": "unknown", "last_tick_at": None, "age_seconds": None, "interval_seconds": interval,
                "watched": 0, "quoted": 0, "last_error": None, "source": SOURCE_NAME}
    age = (now - hb.last_tick_at).total_seconds()
    return {"status": "running" if age <= max(3 * hb.interval_seconds, 30) else "stopped",
            "last_tick_at": hb.last_tick_at, "age_seconds": round(age, 1), "interval_seconds": hb.interval_seconds,
            "watched": hb.watched, "quoted": hb.quoted, "last_error": hb.last_error, "source": SOURCE_NAME}


# ---------------- Leitura para a API ----------------
def _recent(db: Session, token_id: int, since: datetime) -> list[LiveQuote]:
    return list(db.scalars(
        select(LiveQuote).where(LiveQuote.token_id == token_id, LiveQuote.received_at >= since)
        .order_by(LiveQuote.received_at)
    ))


def _minutes(delta: timedelta) -> int:
    return max(1, math.ceil(delta.total_seconds() / 60))


def _same_source(quotes: list[LiveQuote]) -> list[LiveQuote]:
    """Compara só leituras da fonte mais recente: as fontes medem liquidez de jeitos diferentes."""
    return [q for q in quotes if q.source == quotes[-1].source] if quotes else []


def peak_call(db: Session, token_id: int, reference: float | None = None, flow: dict | None = None, now: datetime | None = None) -> tuple[int, str] | None:
    """Saída perto do topo: (percentual a vender, motivo).

    Backtest em 601 disparos, com 3% de custo: sair ao cair 8% do topo depois de subir 10% rendeu +23,6% de
    média, contra +3,2% da escada de alvos (mediana de -3,0% e -3,1%: poucas moedas puxam o ganho).
    1. Subiu 10% ou mais e caiu 8% do topo, em 2 leituras seguidas: vender tudo.
    2. Subiu 20% ou mais, ainda perto do topo, e vendas superam compras em 1,5x nos últimos 30 s: vender 50%.
       É o aviso antes da queda. Limiar não testado: o fluxo só existe a partir de agora.
    """
    now = now or utcnow()
    quotes = _same_source(_recent(db, token_id, now - LIQ_WINDOW))
    if len(quotes) < 3:
        return None
    base = reference or quotes[0].price_usd
    top = max(q.price_usd for q in quotes[:-2])
    price = max(q.price_usd for q in quotes[-2:])
    drop = 1 - price / top
    if top >= base * (1 + PEAK_ARM) and drop >= PEAK_SELL_ALL:
        return 100, f"Subiu {(top / base - 1) * 100:.0f}% e já caiu {drop * 100:.0f}% do topo"
    if (flow and price >= base * (1 + FADE_MIN_GAIN) and drop < FADE_NEAR_TOP and flow["buys"] + flow["sells"] >= FADE_MIN_TRADES
            and flow["sell_usd"] >= flow["buy_usd"] * FADE_SELL_RATIO):
        return 50, f"Subiu {(price / base - 1) * 100:.0f}% e os vendedores estão superando os compradores"
    return None


def live_alerts(db: Session, token_id: int, now: datetime | None = None) -> list[str]:
    """Motivos de "vender tudo agora" vistos nas cotações rápidas (retirada de liquidez, preço despencando)."""
    now = now or utcnow()
    quotes = _same_source(_recent(db, token_id, now - LIQ_WINDOW))
    if len(quotes) < 3:
        return []
    out = []
    last2, before = quotes[-2:], quotes[:-2]
    liq_before = [q for q in before if q.liquidity_usd]
    if liq_before and all(q.liquidity_usd is not None for q in last2):
        top = max(liq_before, key=lambda q: q.liquidity_usd)
        if top.liquidity_usd >= 1000 and all(q.liquidity_usd <= top.liquidity_usd * LIQ_LEFT for q in last2):
            drop = 1 - last2[-1].liquidity_usd / top.liquidity_usd
            out.append(f"Liquidez retirada agora: caiu {drop * 100:.0f}% em {_minutes(now - top.received_at)} min "
                       "— padrão de golpe (rug pull)")
    price_before = [q for q in before if q.received_at >= now - PRICE_WINDOW]
    if price_before:
        top = max(price_before, key=lambda q: q.price_usd)
        if all(q.price_usd <= top.price_usd * PRICE_LEFT for q in last2):
            drop = 1 - last2[-1].price_usd / top.price_usd
            out.append(f"Preço despencou {drop * 100:.0f}% em {_minutes(now - top.received_at)} min")
    return out


def feed(db: Session, token: Token, now: datetime | None = None) -> dict:
    """Estado da cotação rápida de um token para o quadro "Quando vender"."""
    now = now or utcnow()
    svc = service_status(db, now)
    interval = svc["interval_seconds"]
    base = {"source": SOURCE_NAME, "interval_seconds": interval, "observed_at": None, "age_seconds": None,
            "price_usd": None, "liquidity_usd": None, "rules_version": RULES_VERSION}
    if token.chain_id != CHAIN:
        return {**base, "status": "unavailable", "note": "A atualização rápida só cobre Solana."}
    if svc["status"] != "running":
        return {**base, "status": "off",
                "note": "Atualização rápida desligada: mostrando o preço do coletor (atualiza a cada ~30–60 s)."}
    q = db.scalar(select(LiveQuote).where(LiveQuote.token_id == token.id, LiveQuote.source == chain.SOURCE_NAME,
                                          LiveQuote.received_at >= now - timedelta(seconds=5))
                  .order_by(LiveQuote.received_at.desc()).limit(1))
    if q is not None:
        interval = 1
    else:
        q = db.scalar(select(LiveQuote).where(LiveQuote.token_id == token.id)
                      .order_by(LiveQuote.received_at.desc()).limit(1))
    if q is not None and (now - q.received_at).total_seconds() <= 3 * interval:
        return {**base, "status": "live", "source": q.source, "interval_seconds": interval, "observed_at": q.received_at,
                "age_seconds": round((now - q.received_at).total_seconds(), 1),
                "price_usd": q.price_usd, "liquidity_usd": q.liquidity_usd,
                "note": f"Preço ao vivo, conferido a cada {interval} s."}
    w = db.get(LiveWatch, token.id)
    waited = (now - w.first_requested_at).total_seconds() if w else 0
    if w is not None and waited > 2 * interval + 5:
        return {**base, "status": "unavailable",
                "note": "A fonte rápida não tem preço para esta moeda agora: mostrando o preço do coletor."}
    return {**base, "status": "waiting", "note": "Buscando o preço ao vivo (alguns segundos)…"}
