"""Comandos administrativos. Uso: `python -m app.cli <comando>`.

  openapi                 exporta o contrato OpenAPI para docs/openapi.json
  migrate                 aplica migrações (alembic upgrade head)
  seed-users [--reset]    cria usuários iniciais (SEED_USERNAMES / SEED_INITIAL_PASSWORD)
  track <chain> <addr>    adiciona token à watchlist (consulta a fonte real)
  discover                executa descoberta uma vez
  refresh                 coleta + análise uma vez
  checks [N]              verificações técnicas Solana pendentes (N tokens)
  evaluate                avalia previsões com horizonte encerrado
  retention [--apply]     mostra/aplica política de retenção (padrão: só mostra)
"""
import json
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select, update

from app.config import BACKEND_DIR, get_settings
from app.db import session_factory, utcnow
from app.logging_setup import setup_logging


def cmd_migrate(_args):
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")
    print("migrações aplicadas")


def cmd_seed_users(args):
    from app.models import User
    from app.security import hash_password

    s = get_settings()
    if not s.seed_initial_password:
        sys.exit("SEED_INITIAL_PASSWORD não definido (configure em backend/.env; nunca versione)")
    reset = "--reset" in args
    db = session_factory()()
    for name in s.seed_username_list:
        name = name.lower()
        user = db.scalar(select(User).where(User.username == name))
        if user and not reset:
            print(f"usuário {name}: já existe (use --reset para redefinir a senha)")
            continue
        if user is None:
            user = User(username=name, password_hash="", must_change_password=True)
            db.add(user)
        user.password_hash = hash_password(s.seed_initial_password)
        user.must_change_password = True
        print(f"usuário {name}: senha inicial definida (troca obrigatória recomendada)")
    db.commit()


def cmd_track(args):
    from app.engine.pipeline import analyze_token
    from app.ingest.service import track_token

    if len(args) != 2:
        sys.exit("uso: track <chain_id> <address>")
    db = session_factory()()
    token, res = track_token(db, args[0], args[1])
    if not res.ok:
        sys.exit(f"falha na fonte: {res.error}")
    if token is None:
        sys.exit("nenhum par encontrado na fonte para este token como token-base")
    a = analyze_token(db, token, force=True)
    print(json.dumps({"token_id": token.id, "symbol": token.symbol, "risk": a.risk_score, "opportunity": a.opportunity_score}))


def cmd_discover(_args):
    from app.ingest.service import discover

    db = session_factory()()
    print(f"novos tokens: {len(discover(db))}")


def cmd_refresh(_args):
    from app.worker import job_refresh

    print(job_refresh(session_factory()()))


def cmd_checks(args):
    from app.engine import checks
    from app.engine.pipeline import analyze_tokens

    db = session_factory()()
    ids = checks.run_due_checks(db, limit=int(args[0]) if args else 3)
    print({"checked": ids, "analyses": analyze_tokens(db, ids)})


def cmd_evaluate(_args):
    from app.worker import job_evaluate

    print(job_evaluate(session_factory()()))


def cmd_retention(args):
    from app.models import PairSnapshot

    s = get_settings()
    db = session_factory()()
    raw_cut = utcnow() - timedelta(days=s.raw_payload_retention_days)
    snap_cut = utcnow() - timedelta(days=s.snapshot_retention_days)
    raw_n = db.scalar(select(func.count()).select_from(PairSnapshot).where(PairSnapshot.received_at < raw_cut, PairSnapshot.raw.is_not(None)))
    old_n = db.scalar(select(func.count()).select_from(PairSnapshot).where(PairSnapshot.received_at < snap_cut))
    print(f"payloads brutos a limpar (> {s.raw_payload_retention_days} d): {raw_n}")
    print(f"snapshots além de {s.snapshot_retention_days} d (NÃO removidos automaticamente): {old_n}")
    if "--apply" in args:
        db.execute(update(PairSnapshot).where(PairSnapshot.received_at < raw_cut).values(raw=None))
        db.commit()
        print("payloads brutos antigos removidos (dados normalizados preservados)")


def cmd_openapi(_args):
    from app.main import create_app

    out = BACKEND_DIR.parent / "docs" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OpenAPI exportado para {out}")


COMMANDS = {
    "openapi": cmd_openapi,
    "migrate": cmd_migrate, "seed-users": cmd_seed_users, "track": cmd_track, "discover": cmd_discover,
    "refresh": cmd_refresh, "checks": cmd_checks, "evaluate": cmd_evaluate, "retention": cmd_retention,
}


def main(argv=None):
    setup_logging()
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    main()
