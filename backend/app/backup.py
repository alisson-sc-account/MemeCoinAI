"""Cópia de segurança do banco. Roda ao desligar, ao ligar se a última for antiga, e a cada 6 h.

`VACUUM INTO` gera uma cópia íntegra e compacta mesmo com o banco em uso. Fica em `data/backups/`, fora
do Git. Guarda as últimas `KEEP` cópias: cada uma tem o tamanho do banco.
"""
import logging
import sqlite3
import time
from pathlib import Path

from app.config import BACKEND_DIR, get_settings

log = logging.getLogger("backup")
KEEP = 5
PREFIX = "memecoinai-"


def backup_dir() -> Path:
    return BACKEND_DIR / "data" / "backups"


def _database_file() -> Path | None:
    url = get_settings().database_url
    return Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else None


def newest_age_hours() -> float | None:
    files = sorted(backup_dir().glob(f"{PREFIX}*.db"))
    return (time.time() - files[-1].stat().st_mtime) / 3600 if files else None


def make_backup() -> Path | None:
    source = _database_file()
    if source is None or not source.exists():
        return None
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{PREFIX}{time.strftime('%Y%m%d-%H%M%S')}.db"
    temp = target.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    con = sqlite3.connect(source, timeout=30)
    try:
        con.execute("VACUUM INTO ?", (str(temp),))
    finally:
        con.close()
    check = sqlite3.connect(temp)
    try:
        ok = check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        check.close()
    if not ok:  # cópia ruim não pode tomar o lugar das boas
        temp.unlink(missing_ok=True)
        raise RuntimeError("cópia do banco falhou na verificação")
    temp.replace(target)
    for old in sorted(folder.glob(f"{PREFIX}*.db"))[:-KEEP]:
        old.unlink()
    log.info("cópia do banco salva em %s", target.name)
    return target
