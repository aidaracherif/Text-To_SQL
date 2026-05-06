"""
tests/conftest.py — Fixtures pytest partagées par tous les tests.

Centralise la création des objets de test (faux LLM, fausse DB, faux RAG)
pour éviter de dupliquer les mocks dans chaque fichier de test.
"""

import sys
import os
from unittest.mock import MagicMock

import pytest

# Ajouter la racine du projet au PYTHONPATH pour que `from core.x import y` marche
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# =============================================================================
# FIXTURES — Faux clients (mocks)
# =============================================================================

@pytest.fixture
def fake_llm():
    """
    Faux client Ollama. Par défaut, renvoie un SQL valide.
    Chaque test peut override .chat.return_value selon son besoin.
    """
    llm = MagicMock()
    llm.chat.return_value = "```sql\nSELECT * FROM declarations LIMIT 10;\n```"
    llm.embed.return_value = [0.1] * 768
    llm.is_alive.return_value = True
    return llm


@pytest.fixture
def fake_db():
    """
    Faux DBConnector. Par défaut, retourne 2 colonnes et 1 ligne.
    """
    db = MagicMock()
    db.execute.return_value = (["id", "nom"], [[1, "Dakar"]])
    db.test_connection.return_value = True
    return db


@pytest.fixture
def fake_schema_loader():
    """Faux SchemaLoader. Retourne un schéma minimal en string."""
    sl = MagicMock()
    sl.get_schema_and_stats.return_value = (
        "TABLE declarations (id INT, date_enregistrement DATE)",
        "STATS: 100 declarations",
    )
    return sl


@pytest.fixture
def fake_rag_retriever():
    """Faux SmartRetriever. Retourne un contexte vide par défaut."""
    rag = MagicMock()
    rag.retrieve.return_value = {
        "sql_examples": [],
        "knowledge": [],
        "schema_chunks": [],
        "_route": "sql_only",
    }
    rag.store = MagicMock()
    rag.store.is_alive.return_value = True
    return rag


@pytest.fixture
def fake_audit_repo():
    """Faux AuditRepository. .record() retourne un id factice."""
    repo = MagicMock()
    repo.record.return_value = 1
    repo.list_recent.return_value = []
    repo.count.return_value = 0
    repo.get_by_id.return_value = None
    repo.clear.return_value = 0
    return repo


# =============================================================================
# FIXTURES — Données d'exemple
# =============================================================================

@pytest.fixture
def sample_query_result():
    """Un QueryResult de succès, prêt à l'emploi."""
    from core.models import QueryResult
    return QueryResult(
        question="Combien de déclarations ?",
        sql="SELECT COUNT(*) FROM declarations;",
        columns=["count"],
        rows=[[42]],
        row_count=1,
        duration_ms=123.4,
    )


@pytest.fixture
def sample_rag_context():
    """Un contexte RAG complet pour tester les prompts."""
    return {
        "sql_examples": [
            {
                "question": "Combien de déclarations ?",
                "sql": "SELECT COUNT(*) FROM declarations;",
                "score": 0.92,
            }
        ],
        "knowledge": [
            {
                "titre": "Définition déclaration",
                "contenu": "Une déclaration douanière est un document obligatoire.",
                "score": 0.78,
            }
        ],
        "schema_chunks": [
            {
                "table": "declarations",
                "description": "Table principale des déclarations",
                "score": 0.65,
            }
        ],
        "_route": "direct",
    }
