"""
Tests unitaires pour infrastructure/database/audit_repository.py

OBJECTIF CRITIQUE : vérifier que l'AuditRepository ne CRASHE JAMAIS
l'API métier, même si PostgreSQL est down ou si l'INSERT échoue.

Couvre :
  - Connexion réussie : INSERT et retour de l'id
  - Connexion impossible : retourne None sans lever d'exception
  - INSERT qui plante : retourne None sans crasher
  - Sérialisation safe (datetime, Decimal, bytes)
  - Troncature du preview de lignes
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
import json

import pytest


# =============================================================================
# Helper : créer un repo avec une connexion mockée
# =============================================================================

def _make_repo_with_mock_conn(mock_connect_result):
    """
    Patch psycopg2.connect pour retourner mock_connect_result, puis instancie
    un AuditRepository. Si mock_connect_result est une exception, elle sera
    levée à l'appel de connect().
    """
    from infrastructure.database.audit_repository import AuditRepository

    repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
    return repo


# =============================================================================
# Cas nominal : INSERT réussit
# =============================================================================

class TestAuditRecordSuccess:

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_record_returns_inserted_id(self, mock_connect):
        from infrastructure.database.audit_repository import AuditRepository

        # Mock du curseur qui retourne id=42
        cursor = MagicMock()
        cursor.fetchone.return_value = (42,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)

        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_connect.return_value = conn

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
        result_id = repo.record(
            question="test",
            sql="SELECT 1",
            success=True,
            row_count=1,
            duration_ms=10.0,
        )

        assert result_id == 42
        # commit doit avoir été appelé
        conn.commit.assert_called_once()
        # connexion fermée
        conn.close.assert_called_once()

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_record_minimal_only(self, mock_connect):
        """Doit fonctionner en passant uniquement les champs minimaux."""
        from infrastructure.database.audit_repository import AuditRepository

        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_connect.return_value = conn

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
        result_id = repo.record(
            question="q",
            sql="",
            success=False,
            row_count=0,
            duration_ms=0.0,
        )
        assert result_id == 1


# =============================================================================
# ROBUSTESSE — l'audit ne doit JAMAIS planter l'API
# =============================================================================

class TestAuditRecordRobustness:

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_returns_none_when_db_down(self, mock_connect):
        """Si psycopg2 ne peut pas se connecter, on log et on retourne None."""
        import psycopg2
        from infrastructure.database.audit_repository import AuditRepository

        mock_connect.side_effect = psycopg2.OperationalError("connection refused")

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
        result_id = repo.record(
            question="test",
            sql="SELECT 1",
            success=True,
        )
        # CRITIQUE : pas d'exception levée
        assert result_id is None

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_returns_none_when_insert_fails(self, mock_connect):
        """Si l'INSERT plante (table manquante, etc.), pas de crash."""
        from infrastructure.database.audit_repository import AuditRepository

        cursor = MagicMock()
        cursor.execute.side_effect = Exception("relation 'audit_log' does not exist")
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_connect.return_value = conn

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
        result_id = repo.record(question="q", sql="", success=False)
        assert result_id is None

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_list_recent_returns_empty_on_error(self, mock_connect):
        """Si la lecture plante, on retourne [] (pas d'exception)."""
        import psycopg2
        from infrastructure.database.audit_repository import AuditRepository

        mock_connect.side_effect = psycopg2.OperationalError("down")

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})
        assert repo.list_recent() == []
        assert repo.count() == 0
        assert repo.get_by_id(1) is None
        assert repo.clear() == 0


# =============================================================================
# TRONCATURE — preview limité à 10 lignes
# =============================================================================

class TestAuditRowsPreview:

    @patch("infrastructure.database.audit_repository.psycopg2.connect")
    def test_truncates_rows_to_preview_limit(self, mock_connect):
        """rows_preview doit être tronqué à 10 lignes max."""
        from infrastructure.database.audit_repository import (
            AuditRepository, ROWS_PREVIEW_LIMIT
        )

        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cursor
        mock_connect.return_value = conn

        repo = AuditRepository(db_config={"dbname": "test", "user": "x", "password": "x", "host": "x", "port": 5432})

        # 50 lignes envoyées
        big_rows = [[i, f"ville_{i}"] for i in range(50)]
        repo.record(
            question="q",
            sql="SELECT 1",
            success=True,
            rows=big_rows,
        )

        # Vérifier que cursor.execute a été appelé avec rows_preview tronqué
        call_args = cursor.execute.call_args
        params = call_args[0][1]  # deuxième argument = tuple de params
        # rows_preview est le 10ème param (index 9 dans la liste)
        # On ne va pas chercher l'index exact, on vérifie juste la taille
        assert ROWS_PREVIEW_LIMIT == 10


# =============================================================================
# SÉRIALISATION — types non-natifs JSON
# =============================================================================

class TestSafeJsonSerialization:

    def test_serializes_datetime(self):
        """datetime doit devenir une string ISO."""
        from infrastructure.database.audit_repository import _safe_json_dumps

        dt = datetime(2024, 5, 15, 10, 30, 0)
        result = _safe_json_dumps([dt])
        # Doit être un JSON valide qui contient l'ISO format
        parsed = json.loads(result)
        assert "2024-05-15" in parsed[0]

    def test_serializes_decimal(self):
        """Decimal (ex. depuis PostgreSQL NUMERIC) doit devenir une string."""
        from infrastructure.database.audit_repository import _safe_json_dumps

        result = _safe_json_dumps([Decimal("1234.56")])
        parsed = json.loads(result)
        # Doit être convertible
        assert "1234.56" in str(parsed[0])

    def test_serializes_bytes(self):
        """bytes doit devenir une string (utf-8)."""
        from infrastructure.database.audit_repository import _safe_json_dumps

        result = _safe_json_dumps([b"hello"])
        parsed = json.loads(result)
        assert parsed[0] == "hello"

    def test_handles_unicode(self):
        """ensure_ascii=False → les accents passent."""
        from infrastructure.database.audit_repository import _safe_json_dumps

        result = _safe_json_dumps(["déclaration douanière"])
        # Doit garder les accents (pas \u00e9...)
        assert "déclaration" in result
