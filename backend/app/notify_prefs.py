"""Preferências do aviso no celular, editáveis pelo site.

Ficam em `data/notify_prefs.json` (fora do Git). O worker relê o arquivo quando ele muda: salvar no site vale
na próxima volta do aviso (~3 s), sem reiniciar. Arquivo ausente ou inválido = padrão (igual ao comportamento antigo).
"""
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import BACKEND_DIR

Priority = Literal["min", "low", "default", "high", "urgent"]
Severity = Literal["info", "low", "medium", "high", "critical"]
SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]
PLACEHOLDERS = ["symbol", "name", "reason", "score", "risk", "liquidity", "address", "chain", "kind"]
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Rule(BaseModel):
    enabled: bool = True
    priority: Priority = "high"
    tags: str = Field("", max_length=120, description="Emojis do ntfy separados por vírgula, ex.: rocket,green_circle")
    title: str = Field("{kind} {symbol}", max_length=120)
    min_severity: Severity = "high"  # só para disparo e risco (alertas)


def _rules() -> dict[str, Rule]:
    return {
        "burst": Rule(priority="urgent", tags="rocket", title="DISPARO {symbol}", min_severity="critical"),
        "buy_strong": Rule(priority="high", tags="green_circle", title="COMPRA FORTE {symbol}"),
        "buy": Rule(enabled=False, priority="default", tags="large_blue_circle", title="COMPRA {symbol}"),
        "sell": Rule(enabled=False, priority="default", tags="red_circle", title="VENDA {symbol}"),
        "risk": Rule(enabled=False, priority="default", tags="warning", title="RISCO {symbol}", min_severity="high"),
    }


KINDS = {"burst": "Disparo", "buy_strong": "Compra forte", "buy": "Compra", "sell": "Venda", "risk": "Risco"}


class Quiet(BaseModel):
    enabled: bool = False
    start: str = "23:00"
    end: str = "07:00"
    allow_urgent: bool = True  # aviso com prioridade "urgent" passa mesmo no silêncio

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not HHMM.match(v):
            raise ValueError("use HH:MM, ex.: 23:00")
        return v


class NotifyPrefs(BaseModel):
    enabled: bool = True
    server: str = Field("", max_length=200, description="Vazio = NTFY_BASE_URL do .env (https://ntfy.sh)")
    topic: str = Field("", max_length=64, description="Vazio = canal secreto sorteado")
    rules: dict[str, Rule] = Field(default_factory=_rules)
    body: str = Field("{reason}", max_length=500)
    min_opportunity_score: float = Field(0, ge=0, le=100)
    max_risk_score: float = Field(100, ge=0, le=100)
    min_liquidity_usd: float = Field(0, ge=0)
    token_cooldown_minutes: int = Field(60, ge=0, le=1440)
    max_per_hour: int = Field(30, ge=1, le=500)
    daily_cap: int = Field(200, ge=1, le=200)
    quiet: Quiet = Field(default_factory=Quiet)
    muted: list[str] = Field(default_factory=list, max_length=500, description="Endereços ou símbolos silenciados")
    favorites_only: bool = False
    favorites_bypass_filters: bool = True  # favorita ignora score/liquidez/risco mínimos

    @field_validator("server")
    @classmethod
    def _server(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not re.match(r"^https?://[\w.\-:]+(/[\w.\-/]*)?$", v):
            raise ValueError("endereço do servidor inválido")
        return v

    @field_validator("topic")
    @classmethod
    def _topic(cls, v: str) -> str:
        v = v.strip()
        if v and not re.match(r"^[\w\-]{8,64}$", v):
            raise ValueError("canal: 8 a 64 letras, números, - ou _")
        return v

    @field_validator("rules")
    @classmethod
    def _complete(cls, v: dict[str, Rule]) -> dict[str, Rule]:
        unknown = set(v) - set(KINDS)
        if unknown:
            raise ValueError(f"tipo desconhecido: {', '.join(sorted(unknown))}")
        return {**_rules(), **v}

    @field_validator("muted")
    @classmethod
    def _muted(cls, v: list[str]) -> list[str]:
        return sorted({x.strip() for x in v if x.strip()})


def prefs_path() -> Path:
    return BACKEND_DIR / "data" / "notify_prefs.json"


_cache: dict = {"key": None, "prefs": None}


def load() -> NotifyPrefs:
    path = prefs_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return NotifyPrefs()
    if _cache["key"] == key:
        return _cache["prefs"]
    try:
        prefs = NotifyPrefs.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        prefs = NotifyPrefs()
    _cache.update(key=key, prefs=prefs)
    return prefs


def save(prefs: NotifyPrefs) -> NotifyPrefs:
    path = prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(prefs.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    _cache.update(key=None, prefs=None)
    return load()


def severity_ok(severity: str, minimum: str) -> bool:
    try:
        return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(minimum)
    except ValueError:
        return False


def in_quiet(q: Quiet, hhmm: str) -> bool:
    if not q.enabled or q.start == q.end:
        return False
    return q.start <= hhmm < q.end if q.start < q.end else hhmm >= q.start or hhmm < q.end


def render(template: str, values: dict) -> str:
    """Troca {campo} pelo valor; campo desconhecido fica como está (sem acesso a atributos)."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template).strip()
