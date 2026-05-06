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
# 🆕 TRANSCRIPTION VOCALE
# =============================================================================

class VoiceTranscriptionResponse(BaseModel):
    """
    Réponse de POST /api/v1/voice/transcribe.
    Le frontend doit afficher 'suggested_question' et demander confirmation
    à l'utilisateur AVANT d'appeler /api/v1/query.
    """
    ok: bool = True
    transcription: str = Field(
        ...,
        description="Texte brut transcrit depuis l'audio (peut contenir hésitations)",
    )
    suggested_question: str = Field(
        ...,
        description="Question nettoyée et reformulée, prête pour /query",
    )
    language: str = Field("fr", description="Langue détectée par Whisper")
    duration_audio_s: float = Field(0.0, description="Durée de l'audio en secondes")
    duration_processing_ms: float = Field(0.0, description="Temps de transcription")
    confidence: Optional[float] = Field(
        None,
        description="Confiance moyenne de la transcription (0-1)",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "transcription": "euh donne moi le top 10 des importateurs en 2024",
                "suggested_question": "Quels sont les 10 plus gros importateurs en 2024 ?",
                "language": "fr",
                "duration_audio_s": 4.2,
                "duration_processing_ms": 1850.3,
                "confidence": 0.94,
            }
        }


class VoiceErrorResponse(BaseModel):
    ok: bool = False
    error: str = Field(..., description="Message d'erreur")


# =============================================================================
# 🆕 EXTRACTION PDF
# =============================================================================

class ExtractedField(BaseModel):
    """Champ structuré extrait du PDF (NIF, période, etc.)"""
    name: str = Field(..., description="Nom du champ (ex: 'NIF', 'periode')")
    value: str = Field(..., description="Valeur extraite")
    confidence: Optional[str] = Field(
        None,
        description="haute / moyenne / faible",
    )


class DocumentExtractionResponse(BaseModel):
    """
    Réponse de POST /api/v1/document/extract.
    Le frontend affiche 'suggested_question' + 'extracted_fields' pour
    validation utilisateur avant d'appeler /api/v1/query.
    """
    ok: bool = True
    filename: str = Field(..., description="Nom du fichier uploadé")
    page_count: int = Field(..., description="Nombre de pages traitées")
    extracted_text: str = Field(
        ...,
        description="Texte brut extrait (tronqué pour l'affichage)",
    )
    suggested_question: str = Field(
        ...,
        description="Question naturelle reformulée par le LLM",
    )
    extracted_fields: List[ExtractedField] = Field(
        default_factory=list,
        description="Champs structurés détectés (NIF, période, marchandises…)",
    )
    has_tables: bool = Field(False, description="Le PDF contient-il des tables ?")
    used_ocr: bool = Field(False, description="OCR a-t-il été utilisé ?")
    duration_ms: float = Field(0.0, description="Temps total de traitement")

    class Config:
        json_schema_extra = {
            "example": {
                "ok": True,
                "filename": "demande_extraction_sococim.pdf",
                "page_count": 2,
                "extracted_text": "Demande d'extraction des déclarations\nNIF : 1234567...",
                "suggested_question": "Liste des déclarations de l'opérateur SOCOCIM (NIF 1234567) entre janvier et juin 2024",
                "extracted_fields": [
                    {"name": "NIF", "value": "1234567", "confidence": "haute"},
                    {"name": "operateur", "value": "SOCOCIM", "confidence": "haute"},
                    {"name": "periode_debut", "value": "2024-01-01", "confidence": "moyenne"},
                    {"name": "periode_fin", "value": "2024-06-30", "confidence": "moyenne"},
                ],
                "has_tables": False,
                "used_ocr": False,
                "duration_ms": 3245.8,
            }
        }


class DocumentErrorResponse(BaseModel):
    ok: bool = False
    filename: Optional[str] = None
    error: str = Field(..., description="Message d'erreur")
