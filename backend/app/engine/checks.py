"""Verificações técnicas específicas por rede (Camada B).

Somente Solana (SPL Token / Token-2022) é suportada nesta versão. Para outras
redes o resultado é `not_applicable` e o motor registra que a verificação
não foi feita (falta de evidência NÃO é tratada como segurança).
"""
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.ingest.service import collector_run, record_fetch
from app.models import Analysis, RiskCheck, Token
from app.sources import solana_rpc
from app.sources.solana_rpc import SolanaRpcClient

METHOD_VERSION = "sol-1"
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

CHECK_MINT = "solana_mint_account"
CHECK_HOLDERS = "solana_largest_accounts"

# Extensões Token-2022 que podem prejudicar holders, com motivo.
RISKY_EXTENSIONS = {
    "permanentDelegate": "delegado permanente pode transferir/queimar tokens de qualquer conta",
    "transferHook": "programa externo executado em toda transferência (pode bloquear vendas)",
    "nonTransferable": "token não transferível",
    "pausableConfig": "transferências podem ser pausadas pela autoridade",
    "defaultAccountState": "novas contas podem nascer congeladas",
    "transferFeeConfig": "taxa de transferência configurável",
    "mintCloseAuthority": "autoridade pode fechar o mint",
}

RECHECK_INTERVAL = timedelta(hours=1)
RATE_LIMITED_RETRY = timedelta(minutes=15)


HOLDERS_PAUSE_SECONDS = 600.0  # getTokenLargestAccounts vive em 429 no RPC público
_holders_paused_until = 0.0


def parse_mint_account(value: dict | None) -> tuple[str, dict]:
    """Interpreta a resposta de getAccountInfo(jsonParsed) de um mint."""
    if value is None:
        return "error", {"reason": "conta do mint não encontrada"}
    owner = value.get("owner")
    data = value.get("data")
    if not isinstance(data, dict) or data.get("parsed", {}).get("type") != "mint":
        return "error", {"reason": "conta não é um mint SPL", "owner_program": owner}
    info = data["parsed"].get("info", {})
    extensions = []
    for ext in info.get("extensions") or []:
        name = ext.get("extension")
        state = ext.get("state") or {}
        entry = {"extension": name}
        if name in RISKY_EXTENSIONS:
            entry["risk_reason"] = RISKY_EXTENSIONS[name]
        if name == "transferFeeConfig":
            newer = state.get("newerTransferFee") or {}
            entry["transfer_fee_bps"] = newer.get("transferFeeBasisPoints")
        if name == "defaultAccountState":
            entry["state"] = state.get("accountState")
            if entry["state"] != "frozen":
                entry.pop("risk_reason", None)
        if name == "permanentDelegate" and not state.get("delegate"):
            entry.pop("risk_reason", None)
        if name == "transferHook" and not state.get("programId"):
            entry.pop("risk_reason", None)
        extensions.append(entry)
    result = {
        "program": "token-2022" if owner == TOKEN_2022_PROGRAM else "spl-token" if owner == SPL_TOKEN_PROGRAM else owner,
        "mint_authority": info.get("mintAuthority"),
        "freeze_authority": info.get("freezeAuthority"),
        "supply_raw": info.get("supply"),
        "decimals": info.get("decimals"),
        "extensions": extensions,
        "risky_extensions": [e for e in extensions if e.get("risk_reason")],
    }
    flagged = bool(result["mint_authority"] or result["freeze_authority"] or result["risky_extensions"])
    return ("flagged" if flagged else "ok"), result


def parse_largest_accounts(value: list | None, supply_raw: str | None, decimals: int | None) -> tuple[str, dict]:
    if value is None or supply_raw is None or decimals is None:
        return "error", {"reason": "dados insuficientes (contas ou supply ausentes)"}
    supply = int(supply_raw) / (10**decimals)
    if supply <= 0:
        return "error", {"reason": "supply zero"}
    amounts = []
    for acc in value:
        ui = acc.get("uiAmountString") or acc.get("uiAmount")
        try:
            amounts.append((acc.get("address"), float(ui)))
        except (TypeError, ValueError):
            continue
    amounts.sort(key=lambda x: x[1], reverse=True)
    top1 = amounts[0][1] / supply if amounts else 0.0
    top10 = sum(a for _, a in amounts[:10]) / supply
    result = {
        "supply": supply,
        "accounts_returned": len(amounts),
        "top1_share": round(top1, 6),
        "top10_share": round(top10, 6),
        "top_accounts": [{"token_account": a, "share": round(v / supply, 6)} for a, v in amounts[:10]],
        "limitations": (
            "Contas de token, não proprietários. Inclui cofres de pools, endereços de queima "
            "e contratos sem classificação; a concentração real entre holders pode ser menor ou maior."
        ),
    }
    flagged = top10 > 0.5
    return ("flagged" if flagged else "ok"), result


def latest_check(db: Session, token_id: int, check_type: str) -> RiskCheck | None:
    return db.scalar(
        select(RiskCheck)
        .where(RiskCheck.token_id == token_id, RiskCheck.check_type == check_type)
        .order_by(RiskCheck.checked_at.desc(), RiskCheck.id.desc())
        .limit(1)
    )


def run_solana_checks(db: Session, token: Token, rpc: SolanaRpcClient | None = None) -> list[RiskCheck]:
    global _holders_paused_until
    rpc = rpc or SolanaRpcClient()
    created: list[RiskCheck] = []
    rate_limited = False
    with collector_run(db, solana_rpc.SOURCE_NAME, "token_checks") as run:
        res = rpc.get_mint_account(token.address)
        record_fetch(run, res)
        if res.ok:
            status, result = parse_mint_account((res.data or {}).get("value"))
            run.items_received += 1
        else:
            rate_limited |= res.rate_limited
            status, result = "unavailable", {"reason": res.error}
        mint_check = RiskCheck(
            token_id=token.id, check_type=CHECK_MINT, status=status, result=result,
            source=solana_rpc.SOURCE_NAME, method_version=METHOD_VERSION, checked_at=utcnow(),
        )
        db.add(mint_check)
        created.append(mint_check)

        if status in ("ok", "flagged") and time.monotonic() >= _holders_paused_until:
            res2 = rpc.get_token_largest_accounts(token.address)
            record_fetch(run, res2)
            if res2.rate_limited:  # método em 429: para de gastar a fila com ele por um tempo
                _holders_paused_until = time.monotonic() + HOLDERS_PAUSE_SECONDS
            if res2.ok:
                run.items_received += 1
                h_status, h_result = parse_largest_accounts(
                    (res2.data or {}).get("value"), result.get("supply_raw"), result.get("decimals")
                )
            else:
                rate_limited |= res2.rate_limited
                h_status, h_result = "unavailable", {"reason": res2.error}
            hc = RiskCheck(
                token_id=token.id, check_type=CHECK_HOLDERS, status=h_status, result=h_result,
                source=solana_rpc.SOURCE_NAME, method_version=METHOD_VERSION, checked_at=utcnow(),
            )
            db.add(hc)
            created.append(hc)
        run.items_stored = len(created)
    token.next_risk_check_at = utcnow() + (RATE_LIMITED_RETRY if rate_limited else RECHECK_INTERVAL)
    db.commit()
    return created


def run_due_checks(db: Session, limit: int = 3, rpc: SolanaRpcClient | None = None) -> list[int]:
    """Executa verificações dos tokens cujo prazo venceu. Retorna ids verificados.

    Com centenas de tokens monitorados o RPC gratuito não cobre todos: a fila é
    ordenada pela oportunidade recente, para que candidatos a compra tenham o
    contrato verificado antes dos demais.
    """
    now = utcnow()
    recent = (
        select(Analysis.token_id.label("token_id"), func.max(Analysis.opportunity_score).label("opp"))
        .where(Analysis.computed_at >= now - timedelta(minutes=15))
        .group_by(Analysis.token_id)
        .subquery()
    )
    tokens = db.scalars(
        select(Token)
        .outerjoin(recent, recent.c.token_id == Token.id)
        .where(
            Token.is_tracked.is_(True),
            Token.chain_id == "solana",
            (Token.next_risk_check_at.is_(None)) | (Token.next_risk_check_at <= now),
        )
        .order_by(func.coalesce(recent.c.opp, 0).desc(), Token.next_risk_check_at.is_not(None), Token.next_risk_check_at)
        .limit(limit)
    ).all()
    for t in tokens:
        run_solana_checks(db, t, rpc)
    return [t.id for t in tokens]
