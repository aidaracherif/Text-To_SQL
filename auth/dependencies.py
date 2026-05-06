"""
auth/dependencies.py — Dépendances FastAPI pour l'authentification.

Fournit deux dépendances utilisables avec Depends() :
  - get_current_user : extrait le user depuis le token JWT (rejette si invalide)
  - require_admin    : vérifie que le user a le rôle 'admin'

Usage :
    @router.get("/protected")
    async def protected(user: dict = Depends(get_current_user)):
        return {"hello": user["username"]}
"""

import logging
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from auth.security import decode_access_token
from infrastructure.database.user_repository import UserRepository

logger = logging.getLogger(__name__)


# =============================================================================
# Schéma OAuth2 pour Swagger : ajoute le bouton "Authorize 🔓" automatiquement
# =============================================================================

# tokenUrl = endpoint OAuth2 utilisé par Swagger pour le bouton "Authorize"
# Doit pointer sur l'endpoint qui accepte du form-data (/auth/token), PAS sur
# l'endpoint JSON (/auth/login).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


# =============================================================================
# Singleton repository (instancié à la première utilisation)
# =============================================================================

_user_repo: Optional[UserRepository] = None


def _get_user_repo() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = UserRepository()
    return _user_repo


# =============================================================================
# Dépendances FastAPI
# =============================================================================

async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """
    Extrait l'utilisateur courant depuis le token JWT du header Authorization.
    Rejette avec 401 si :
      - le token est absent
      - le token est invalide ou expiré
      - le user n'existe plus en BDD
      - le user est désactivé
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identifiants invalides ou token expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    # 1. Décoder le token
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré, veuillez vous reconnecter.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise credentials_exception

    # 2. Extraire le username
    username: Optional[str] = payload.get("sub")
    if not username:
        raise credentials_exception

    # 3. Vérifier que le user existe toujours et est actif
    user = _get_user_repo().get_by_username(username)
    if user is None:
        raise credentials_exception
    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé.",
        )

    # On ne renvoie JAMAIS le password_hash
    user.pop("password_hash", None)
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    Comme get_current_user, mais rejette avec 403 si le user n'est pas admin.
    """
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action réservée aux administrateurs.",
        )
    return user