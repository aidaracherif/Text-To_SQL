"""
api/routers/history.py — Historique des requêtes (persisté en PostgreSQL).

L'historique est désormais stocké dans la table `audit_log` via AuditRepository.
La fonction `record_query()` reste l'API publique appelée par les autres routers
mais accepte maintenant tous les champs d'audit (contexte RAG, prompts, etc.).
"""

import logging
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Query

from api.schemas import HistoryResponse, HistoryEntry
from infrastructure.database.audit_repository import AuditRepository

logger = logging.getLogger(__name__)
router = APIRouter()


# =============================================================================
# Singleton repository — instancié à la première utilisation
# =============================================================================

_repo: Optional[AuditRepository] = None


def _get_repo() -> AuditRepository:
    global _repo
    if _repo is None:
        _repo = AuditRepository()
    return _repo


# =============================================================================
# API publique appelée depuis query.py (et ailleurs si besoin)
# =============================================================================

def record_query(
    *,
    # Niveau MINIMAL (obligatoire)
    question: str,
    sql: str,
    row_count: int,
    duration_ms: float,
    success: bool,
    # Niveau COMPLET (optionnels)
    user_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    columns: Optional[list[str]] = None,
    rows: Optional[list[list[Any]]] = None,
    error_message: Optional[str] = None,
    error_raw: Optional[str] = None,
    warning: Optional[str] = None,
    # Niveau AUDIT LOURD (optionnels)
    rag_context: Optional[dict] = None,
    rag_route: Optional[str] = None,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    llm_model: Optional[str] = None,
    llm_raw_output: Optional[str] = None,
) -> Optional[int]:
    """
    Enregistre une requête dans audit_log.

    Si la BDD est temporairement indisponible, log un warning mais ne lève
    pas d'exception — on ne veut pas casser l'API métier pour un problème
    de logging.

    Retourne l'id audit créé ou None en cas d'échec.
    """
    return _get_repo().record(
        question=question,
        sql=sql,
        success=success,
        row_count=row_count,
        duration_ms=duration_ms,
        user_name=user_name,
        ip_address=ip_address,
        user_agent=user_agent,
        columns=columns,
        rows=rows,
        error_message=error_message,
        error_raw=error_raw,
        warning=warning,
        rag_context=rag_context,
        rag_route=rag_route,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        llm_model=llm_model,
        llm_raw_output=llm_raw_output,
    )


# =============================================================================
# Endpoints REST
# =============================================================================

@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Historique des requêtes",
    description="Retourne les dernières requêtes exécutées (persistées en BDD).",
)
async def get_history(
    limit: int = Query(100, ge=1, le=1000, description="Nombre max d'entrées"),
    offset: int = Query(0, ge=0, description="Décalage pour pagination"),
):
    """Retourne l'historique paginé des requêtes (les plus récentes en premier)."""
    repo = _get_repo()
    rows = repo.list_recent(limit=limit, offset=offset)
    total = repo.count()

    entries = [HistoryEntry(**row) for row in rows]
    return HistoryResponse(entries=entries, total=total)


@router.get(
    "/history/{audit_id}",
    summary="Détail complet d'une entrée d'audit",
    description="Retourne tous les champs (contexte RAG, prompts, etc.) d'une entrée.",
)
async def get_history_detail(audit_id: int):
    """Détail complet d'une entrée — utile pour debug et dashboard."""
    entry = _get_repo().get_by_id(audit_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Audit id={audit_id} non trouvé.")
    # Convertir created_at en string pour JSON
    if "created_at" in entry and entry["created_at"] is not None:
        entry["created_at"] = entry["created_at"].isoformat()
    return entry


@router.delete(
    "/history",
    summary="Vider l'historique",
    description="Supprime toutes les entrées de la table audit_log. À utiliser avec précaution.",
)
async def clear_history():
    """Vide l'historique. Endpoint à protéger en prod (admin uniquement)."""
    deleted = _get_repo().clear()
    return {"message": f"Historique vidé. {deleted} entrée(s) supprimée(s)."}