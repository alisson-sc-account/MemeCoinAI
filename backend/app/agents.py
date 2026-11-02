"""Mapa dos agentes por categoria e o batimento de cada um.

Cada agente faz uma coisa só, com o próprio orçamento de API. Um lento não atrasa os outros:
rodam em threads ou processos separados, e cada fonte tem seu limitador global.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ServiceHeartbeat


@dataclass(frozen=True)
class AgentInfo:
    name: str
    category: str
    label: str
    source: str
    process: str


REGISTRY = (
    AgentInfo("market_hot", "Mercado", "Moedas quentes: sinal, posição, radar e mais volume", "DEX Screener", "worker"),
    AgentInfo("market_cold", "Mercado", "Demais moedas, em rodízio", "DEX Screener", "worker"),
    AgentInfo("scout", "Radar", "Puxa para a frente o que começou a ser negociado agora", "Jupiter", "worker"),
    AgentInfo("discover_lists", "Descoberta", "Perfis e impulsionados", "DEX Screener", "worker"),
    AgentInfo("discover_search", "Descoberta", "Buscas por termos", "DEX Screener", "worker"),
    AgentInfo("discover_gecko", "Descoberta", "Pools novas e em alta", "GeckoTerminal", "worker"),
    AgentInfo("discover_jupiter", "Descoberta", "Mais negociados e recém-criados", "Jupiter", "worker"),
    AgentInfo("tape", "Tempo real", "Cada negociação de pump.fun e PumpSwap: disparo sem atraso e carteiras", "Solana ao vivo", "tape"),
    AgentInfo("notify", "Avisos", "Manda disparo extremo e compra forte para o celular", "ntfy.sh", "worker"),
    AgentInfo("analysis", "Análise", "Score, sinais e disparo, moedas quentes primeiro", "banco local", "worker"),
    AgentInfo("checks", "Segurança", "Autoridades do contrato", "RPC Solana", "worker"),
    AgentInfo("security", "Segurança", "Liquidez travada, donos, insiders e carteiras novas", "RugCheck, RPC", "safety"),
    AgentInfo("live", "Tempo real", "Preço a cada 10 s das moedas abertas e com posição", "Jupiter", "live"),
    AgentInfo("evaluate", "Avaliação", "Mede o que aconteceu depois de cada previsão", "banco local", "worker"),
    AgentInfo("prune", "Manutenção", "Tira moedas mortas do monitoramento", "banco local", "worker"),
    AgentInfo("retention", "Manutenção", "Limpa dados antigos", "banco local", "worker"),
    AgentInfo("board", "Painel", "Prepara as listas do site em segundo plano", "banco local", "board"),
)


def beat(db: Session, name: str, interval: float, error: str | None = None, items: int = 0, duration_ms: float | None = None,
         now: datetime | None = None) -> None:
    now = now or utcnow()
    hb = db.get(ServiceHeartbeat, name)
    if hb is None:
        hb = ServiceHeartbeat(name=name, started_at=now, interval_seconds=int(interval), watched=0, quoted=0)
        db.add(hb)
    hb.last_tick_at, hb.last_error, hb.interval_seconds, hb.watched, hb.last_duration_ms = now, error, int(interval), items, duration_ms
    if error is None:
        hb.last_ok_at = now
    db.commit()


def status_list(db: Session, now: datetime | None = None) -> list[dict]:
    """running = bateu dentro de 3 intervalos (mínimo 3 min); o agente longo não parece parado à toa."""
    now = now or utcnow()
    beats = {h.name: h for h in db.scalars(select(ServiceHeartbeat))}
    out = []
    for a in REGISTRY:
        h = beats.get(a.name)
        if h is None or h.last_tick_at is None:
            status, age = "unknown", None
        else:
            age = (now - h.last_tick_at).total_seconds()
            status = "running" if age <= max(3 * h.interval_seconds, timedelta(minutes=3).total_seconds()) else "stopped"
        out.append({"name": a.name, "category": a.category, "label": a.label, "source": a.source, "process": a.process, "status": status,
                    "last_tick_at": h.last_tick_at if h else None, "age_seconds": round(age, 1) if age is not None else None,
                    "interval_seconds": h.interval_seconds if h else None, "items": h.watched if h else 0,
                    "last_duration_ms": h.last_duration_ms if h else None, "last_error": h.last_error if h else None})
    return out
