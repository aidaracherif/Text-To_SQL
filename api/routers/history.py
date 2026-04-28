"""
api/routers/history.py — Historique des requêtes de la session.

Stocke les dernières requêtes en mémoire (pas de base de données requise).
Équivalent de l'onglet Audit de l'interface Streamlit.

Note : l'historique est perdu au redémarrage du serveur.
Pour la persistance, brancher une vraie BDD (table audit_log).
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends

from api.schemas import HistoryResponse, HistoryEntry, QueryRequest, QuerySuccessResponse, QueryErrorResponse
from api.dependencies import get_service
# from api.routers.query import run_query
from features.text_to_sql.service import TextToSQLService

logger = logging.getLogger(__name__)
router = APIRouter()

# Stockage en mémoire (liste globale, thread-safe pour FastAPI async)
_history: List[dict] = []
_counter: int = 0


def record_query(question: str, sql: str, row_count: int, duration_ms: float, success: bool):
    """Enregistre une requête dans l'historique en mémoire."""
    global _counter
    _counter += 1
    _history.append({
        "id": _counter,
        "question": question,
        "sql": sql,
        "row_count": row_count,
        "duration_ms": round(duration_ms, 1),
        "success": success,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    # Garder seulement les 100 dernières entrées
    if len(_history) > 100:
        _history.pop(0)


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Historique des requêtes",
    description="Retourne les dernières requêtes exécutées durant la session.",
)
async def get_history():
    """Retourne l'historique des requêtes (max 100 entrées, LIFO)."""
    entries = [HistoryEntry(**entry) for entry in reversed(_history)]
    return HistoryResponse(entries=entries, total=len(_history))


@router.delete(
    "/history",
    summary="Vider l'historique",
    description="Supprime toutes les entrées de l'historique en mémoire.",
)
async def clear_history():
    """Vide l'historique de la session."""
    global _history, _counter
    _history.clear()
    _counter = 0
    return {"message": "Historique vidé avec succès."}
