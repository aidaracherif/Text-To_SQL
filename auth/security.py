"""
auth/security.py — Hashage des mots de passe + génération de tokens JWT.

Contient toute la logique cryptographique. Aucun couplage avec FastAPI ni
PostgreSQL : c'est de la logique pure, facile à tester unitairement.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from config.settings import (
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
)


# =============================================================================
# HASHAGE DES MOTS DE PASSE (bcrypt)
# =============================================================================

def hash_password(password: str) -> str:
    """
    Hash un mot de passe avec bcrypt.
    Le sel est généré automatiquement et inclus dans le hash retourné.
    """
    if not password:
        raise ValueError("Le mot de passe ne peut pas être vide.")
    # bcrypt opère sur des bytes
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)   # 12 = bon compromis sécurité/perf
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie qu'un mot de passe en clair correspond à son hash.
    Retourne False si l'un des arguments est invalide (jamais d'exception levée).
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # Hash mal formé : on refuse, on ne crashe pas
        return False


# =============================================================================
# JWT (JSON Web Tokens)
# =============================================================================

def create_access_token(
    *,
    user_id: int,
    username: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Crée un token JWT signé avec les infos minimales de l'utilisateur.

    Claims standards :
      - sub : subject (username, identifiant unique)
      - exp : expiration (timestamp UTC)
      - iat : issued at (date d'émission)

    Claims custom :
      - user_id : id BDD
      - role    : 'user' ou 'admin'
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "user_id": user_id,
        "role": role,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Décode et vérifie un token JWT.
    Retourne le payload (claims) si valide.

    Lève :
      - jwt.ExpiredSignatureError : token expiré
      - jwt.InvalidTokenError     : token invalide (signature, format, etc.)
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])