"""
api/routers/auth.py — Endpoints d'authentification.

Endpoints :
  - POST /api/v1/auth/login    : se connecter, recevoir un token JWT
  - POST /api/v1/auth/register : créer un compte (admin uniquement)
  - GET  /api/v1/auth/me       : qui suis-je ? (connexion requise)
  - GET  /api/v1/auth/users    : liste des users (admin uniquement)
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from api.schemas import (
    LoginRequest,
    TokenResponse,
    RegisterRequest,
    UserResponse,
)
from auth.security import (
    hash_password,
    verify_password,
    create_access_token,
)
from auth.dependencies import get_current_user, require_admin
from infrastructure.database.user_repository import UserRepository
from config.settings import JWT_EXPIRATION_HOURS

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# Singleton repository
# =============================================================================

_user_repo: Optional[UserRepository] = None


def _get_repo() -> UserRepository:
    global _user_repo
    if _user_repo is None:
        _user_repo = UserRepository()
    return _user_repo


# =============================================================================
# Helpers
# =============================================================================

def _to_response(user: dict) -> UserResponse:
    """Convertit un dict user (depuis le repo) en UserResponse Pydantic."""
    # Convertir les datetime en string pour la sérialisation JSON
    def _dt(d):
        if d is None:
            return None
        if isinstance(d, datetime):
            return d.isoformat()
        return str(d)

    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        full_name=user.get("full_name"),
        role=user["role"],
        is_active=user["is_active"],
        created_at=_dt(user["created_at"]),
        last_login_at=_dt(user.get("last_login_at")),
    )


# =============================================================================
# POST /auth/login — connexion
# =============================================================================

@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Se connecter et obtenir un token JWT",
)
async def login(body: LoginRequest):
    """
    Vérifie username/password et retourne un token JWT.
    Le token doit ensuite être envoyé dans le header :
        Authorization: Bearer <token>
    """
    repo = _get_repo()
    user = repo.get_by_username(body.username)

    # Vérifications combinées (mêmes erreurs pour ne pas leaker
    # l'existence du compte)
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nom d'utilisateur ou mot de passe incorrect.",
    )
    if user is None:
        raise invalid
    if not verify_password(body.password, user["password_hash"]):
        raise invalid
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé.",
        )

    # Maj last_login_at (échec silencieux)
    repo.update_last_login(user["id"])

    # Générer le token
    token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
    )
    logger.info(f"[AUTH] Login réussi : {user['username']} (role={user['role']})")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_seconds=JWT_EXPIRATION_HOURS * 3600,
    )


# =============================================================================
# POST /auth/token — alias OAuth2 standard pour Swagger UI ("Authorize 🔓")
# =============================================================================
# Cet endpoint existe UNIQUEMENT pour permettre l'utilisation du bouton
# "Authorize" de Swagger UI, qui envoie les credentials en form-data
# (application/x-www-form-urlencoded) selon le standard OAuth2.
#
# Le frontend Angular doit utiliser /auth/login (JSON) plutôt que /auth/token.
# =============================================================================

@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="Login OAuth2 (form-data) — pour Swagger UI",
    description=(
        "Endpoint OAuth2 standard utilisé par le bouton **Authorize** de Swagger. "
        "Pour les clients programmatiques (Angular, scripts), préférer `/auth/login` "
        "qui accepte du JSON."
    ),
    include_in_schema=True,
)
async def login_oauth2_form(form_data: OAuth2PasswordRequestForm = Depends()):
    """Identique à /auth/login mais lit username/password depuis le form-data."""
    repo = _get_repo()
    user = repo.get_by_username(form_data.username)

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nom d'utilisateur ou mot de passe incorrect.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if user is None:
        raise invalid
    if not verify_password(form_data.password, user["password_hash"]):
        raise invalid
    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé.",
        )

    repo.update_last_login(user["id"])

    token = create_access_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
    )
    logger.info(f"[AUTH] Login OAuth2 réussi : {user['username']}")
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_seconds=JWT_EXPIRATION_HOURS * 3600,
    )


# =============================================================================
# POST /auth/register — création d'un compte (admin uniquement)
# =============================================================================

@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un nouvel utilisateur (admin uniquement)",
)
async def register(
    body: RegisterRequest,
    _admin: dict = Depends(require_admin),
):
    """
    Crée un nouvel utilisateur. Réservé aux admins.
    Le mot de passe est hashé avec bcrypt avant stockage.
    """
    pwd_hash = hash_password(body.password)
    try:
        new_user = _get_repo().create(
            username=body.username,
            password_hash=pwd_hash,
            email=body.email,
            full_name=body.full_name,
            role=body.role,
        )
    except ValueError as ve:
        # Username déjà pris
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ve))

    if new_user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Échec de la création de l'utilisateur.",
        )
    logger.info(f"[AUTH] User créé : {new_user['username']} par {_admin['username']}")
    # is_active n'est pas retourné par RETURNING → on le complète
    new_user.setdefault("is_active", True)
    new_user.setdefault("last_login_at", None)
    return _to_response(new_user)


# =============================================================================
# GET /auth/me — qui suis-je ?
# =============================================================================

@router.get(
    "/auth/me",
    response_model=UserResponse,
    summary="Récupérer les infos de l'utilisateur courant",
)
async def me(user: dict = Depends(get_current_user)):
    """Retourne les infos du user identifié par le token JWT."""
    return _to_response(user)


# =============================================================================
# GET /auth/users — liste des users (admin)
# =============================================================================

@router.get(
    "/auth/users",
    response_model=list[UserResponse],
    summary="Liste tous les utilisateurs (admin uniquement)",
)
async def list_users(_admin: dict = Depends(require_admin)):
    """Retourne tous les utilisateurs. Réservé aux admins."""
    users = _get_repo().list_all()
    return [_to_response(u) for u in users]