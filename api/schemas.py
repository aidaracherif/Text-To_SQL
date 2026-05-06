"""
api/schemas.py — Modèles Pydantic pour les requêtes et réponses de l'API.

Pydantic est intégré nativement dans FastAPI.
Il valide automatiquement les données entrantes et génère la doc OpenAPI.
"""

from typing import Any, List, Optional
from pydantic import BaseModel, Field


# =============================================================================
# REQUÊTES (Request body)
# =============================================================================

class QueryRequest(BaseModel):
    """Corps de la requête POST /api/v1/query"""
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Question en langage naturel sur les données douanières",
        examples=["Quels sont les 10 opérateurs ayant le plus importé en 2024 ?"],
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Donne-moi le total des droits et taxes par bureau de douane en 2024"
            }
        }


# =============================================================================
# RÉPONSES (Response body)
# =============================================================================

class QuerySuccessResponse(BaseModel):
    ok: bool = True
    sql: str = Field(..., description="Requête SQL générée et exécutée")
    columns: List[str] = Field(..., description="Noms des colonnes résultantes")
    rows: List[List[Any]] = Field(..., description="Données tabulaires (lignes × colonnes)")
    narrative: str = Field(..., description="Résumé textuel des résultats")
    row_count: int = Field(..., description="Nombre de lignes retournées")
    duration_ms: float = Field(0.0, description="Temps d'exécution en millisecondes")

class QueryErrorResponse(BaseModel):
    """Réponse en cas d'échec"""
    ok: bool = False
    sql: str = Field(default="", description="SQL tenté (peut être vide)")
    error: str = Field(..., description="Message d'erreur lisible")


class HealthResponse(BaseModel):
    """Réponse du health check"""
    status: str = Field(..., description="'ok' ou 'degraded'")
    llm: bool = Field(..., description="Ollama accessible ?")
    db: bool = Field(..., description="PostgreSQL accessible ?")
    rag: Optional[bool] = Field(None, description="Qdrant accessible ? (None si RAG désactivé)")


class HistoryEntry(BaseModel):
    """Entrée dans l'historique des requêtes"""
    id: int
    question: str
    sql: str
    row_count: int
    duration_ms: float
    success: bool
    timestamp: str


class HistoryResponse(BaseModel):
    """Liste des requêtes récentes"""
    entries: List[HistoryEntry]
    total: int


# =============================================================================
# AUTHENTIFICATION
# =============================================================================

class LoginRequest(BaseModel):
    """Corps de la requête POST /api/v1/auth/login"""
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Réponse du login : token JWT à utiliser dans Authorization: Bearer ..."""
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int = Field(..., description="Durée de validité du token")


class RegisterRequest(BaseModel):
    """Corps de la requête POST /api/v1/auth/register (admin uniquement)"""
    username: str = Field(..., min_length=3, max_length=64,
                          pattern=r"^[a-zA-Z0-9_.-]+$",
                          description="Lettres, chiffres, _ . - uniquement")
    password: str = Field(..., min_length=8, max_length=128,
                          description="Au moins 8 caractères")
    email: Optional[str] = Field(None, max_length=255)
    full_name: Optional[str] = Field(None, max_length=128)
    role: str = Field("user", pattern=r"^(user|admin)$")


class UserResponse(BaseModel):
    """Représentation publique d'un utilisateur (sans password_hash)."""
    id: int
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None