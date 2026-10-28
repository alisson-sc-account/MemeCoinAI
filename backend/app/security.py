"""Hash de senha (Argon2id) e tokens de sessão opacos.

Nada aqui registra senhas ou tokens em log.
"""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Hash fixo usado para gastar o mesmo tempo quando o usuário não existe
# (evita enumeração de usuários por tempo de resposta).
DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
