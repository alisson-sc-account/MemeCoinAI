"""Normalização de pares do DEX Screener para o modelo interno.

Regras:
- Campos ausentes viram None (nunca 0) e são listados em `missing_fields`.
- Strings numéricas ("0.000003187") são convertidas para float.
- `pairCreatedAt` vem em milissegundos Unix -> datetime UTC.
- Endereços: em Solana são case-sensitive (base58) e preservados como vieram;
  em cadeias EVM são normalizados para minúsculas.
"""
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

NORMALIZER_VERSION = "dexs-1"

EVM_CHAINS = {"ethereum", "bsc", "base", "arbitrum", "polygon", "avalanche", "optimism", "blast", "robinhood"}

WINDOWS = ("m5", "h1", "h6", "h24")


def normalize_address(chain_id: str, address: str) -> str:
    address = address.strip()
    return address.lower() if chain_id in EVM_CHAINS else address


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _int(value: Any) -> int | None:
    f = _num(value)
    return int(f) if f is not None else None


@dataclass
class NormalizedPair:
    chain_id: str
    pair_address: str
    dex_id: str | None
    labels: list[str]
    base_address: str
    base_symbol: str | None
    base_name: str | None
    quote_address: str | None
    quote_symbol: str | None
    url: str | None
    pair_created_at: datetime | None
    image_url: str | None
    links: list[dict]
    metrics: dict[str, float | int | None]
    missing_fields: list[str]
    payload_hash: str
    raw: dict = field(repr=False)


class NormalizationError(ValueError):
    pass


def normalize_pair(raw: dict) -> NormalizedPair:
    if not isinstance(raw, dict):
        raise NormalizationError("par não é objeto")
    chain_id = raw.get("chainId")
    pair_address = raw.get("pairAddress")
    base = raw.get("baseToken") or {}
    if not chain_id or not pair_address or not base.get("address"):
        raise NormalizationError("par sem chainId/pairAddress/baseToken.address")
    quote = raw.get("quoteToken") or {}
    txns = raw.get("txns") or {}
    volume = raw.get("volume") or {}
    change = raw.get("priceChange") or {}
    liq = raw.get("liquidity") or {}

    metrics: dict[str, float | int | None] = {
        "price_usd": _num(raw.get("priceUsd")),
        "price_native": _num(raw.get("priceNative")),
        "liquidity_usd": _num(liq.get("usd")),
        "liquidity_base": _num(liq.get("base")),
        "liquidity_quote": _num(liq.get("quote")),
        "fdv": _num(raw.get("fdv")),
        "market_cap": _num(raw.get("marketCap")),
    }
    for w in WINDOWS:
        metrics[f"volume_{w}"] = _num(volume.get(w))
        metrics[f"price_change_{w}"] = _num(change.get(w))
        t = txns.get(w) or {}
        metrics[f"buys_{w}"] = _int(t.get("buys"))
        metrics[f"sells_{w}"] = _int(t.get("sells"))

    missing = sorted(k for k, v in metrics.items() if v is None)

    created_ms = _num(raw.get("pairCreatedAt"))
    pair_created_at = datetime.fromtimestamp(created_ms / 1000, tz=UTC) if created_ms else None
    if pair_created_at is None:
        missing.append("pair_created_at")

    info = raw.get("info") or {}
    links = [
        {"type": s.get("type"), "url": s.get("url")} for s in (info.get("socials") or []) if s.get("url")
    ] + [
        {"type": "website", "url": w.get("url"), "label": w.get("label")}
        for w in (info.get("websites") or [])
        if w.get("url")
    ]

    # Hash dos campos de mercado: detecta respostas repetidas (cache da fonte).
    payload_hash = hashlib.sha256(
        json.dumps({"m": metrics, "p": pair_address}, sort_keys=True, default=str).encode()
    ).hexdigest()

    return NormalizedPair(
        chain_id=chain_id,
        pair_address=normalize_address(chain_id, pair_address),
        dex_id=raw.get("dexId"),
        labels=[str(x) for x in (raw.get("labels") or [])],
        base_address=normalize_address(chain_id, base["address"]),
        base_symbol=base.get("symbol"),
        base_name=base.get("name"),
        quote_address=normalize_address(chain_id, quote["address"]) if quote.get("address") else None,
        quote_symbol=quote.get("symbol"),
        url=raw.get("url"),
        pair_created_at=pair_created_at,
        image_url=info.get("imageUrl"),
        links=links,
        metrics=metrics,
        missing_fields=missing,
        payload_hash=payload_hash,
        raw=raw,
    )
