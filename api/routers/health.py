"""
api/routers/health.py — Endpoint de santé de l'API.

Permet à Angular (ou un monitoring) de vérifier que tous les services
sont opérationnels avant d'afficher l'interface.
"""

from fastapi import APIRouter, Depends

from api.schemas import HealthResponse
from api.dependencies import get_service
from features.text_to_sql.service import TextToSQLService

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="État de santé de l'API",
    description="Vérifie la connectivité avec Ollama, PostgreSQL et Qdrant (RAG).",
)
async def health_check(service: TextToSQLService = Depends(get_service)):
    """
    Retourne l'état de chaque composant :
    - llm  : Ollama est-il accessible ?
    - db   : PostgreSQL est-il accessible ?
    - rag  : Qdrant est-il accessible ? (null si RAG désactivé)
    """
    checks = service.health_check()

    # Le statut global est "ok" seulement si LLM + DB sont up
    # RAG est optionnel (peut être None)
    all_critical_ok = checks["llm"] and checks["db"]

    return HealthResponse(
        status="ok" if all_critical_ok else "degraded",
        llm=checks["llm"],
        db=checks["db"],
        rag=checks.get("rag"),
    )
