"""
Tests unitaires pour core/pipeline.py

Couvre :
  - Pipeline complet en cas de succès
  - Pipeline sans RAG (mode dégradé)
  - Pipeline avec RAG (mode complet)
  - Gestion des erreurs LLM (Ollama down)
  - Gestion des erreurs PostgreSQL (auto-repair)
  - Détection hors-périmètre
  - Refus des SQL dangereux
  - Remplissage des champs d'audit
"""

import pytest

from core.pipeline import run_pipeline
from core.models import QueryResult


# =============================================================================
# CAS NOMINAL — succès simple
# =============================================================================

class TestPipelineSuccess:

    def test_returns_query_result(self, fake_llm, fake_db, fake_schema_loader):
        result = run_pipeline(
            question="Combien de déclarations ?",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert isinstance(result, QueryResult)
        assert result.error is None
        assert result.warning is None

    def test_fills_columns_and_rows_on_success(self, fake_llm, fake_db, fake_schema_loader):
        fake_db.execute.return_value = (["count"], [[42]])
        result = run_pipeline(
            question="Combien ?",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.columns == ["count"]
        assert result.rows == [[42]]
        assert result.row_count == 1

    def test_measures_duration(self, fake_llm, fake_db, fake_schema_loader):
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        # duration_ms doit être positif (même très petit)
        assert result.duration_ms >= 0

    def test_calls_llm_with_built_prompt(self, fake_llm, fake_db, fake_schema_loader):
        run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        # Le LLM doit avoir été appelé avec system + user prompt
        assert fake_llm.chat.called
        args = fake_llm.chat.call_args[0]
        assert len(args) == 2  # system_prompt, user_prompt


# =============================================================================
# RAG : avec et sans
# =============================================================================

class TestPipelineRag:

    def test_works_without_rag(self, fake_llm, fake_db, fake_schema_loader):
        """Le RAG est optionnel — pipeline doit fonctionner sans."""
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
            rag_retriever=None,
        )
        assert result.error is None
        assert result.rag_context is None
        assert result.rag_route is None

    def test_uses_rag_when_provided(
        self, fake_llm, fake_db, fake_schema_loader, fake_rag_retriever
    ):
        run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
            rag_retriever=fake_rag_retriever,
        )
        assert fake_rag_retriever.retrieve.called

    def test_audit_route_filled_from_rag(
        self, fake_llm, fake_db, fake_schema_loader, fake_rag_retriever
    ):
        """Le champ rag_route doit être rempli depuis le contexte RAG."""
        fake_rag_retriever.retrieve.return_value = {
            "sql_examples": [],
            "knowledge": [],
            "schema_chunks": [],
            "_route": "direct",
        }
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
            rag_retriever=fake_rag_retriever,
        )
        assert result.rag_route == "direct"
        assert result.rag_context is not None


# =============================================================================
# CHAMPS D'AUDIT
# =============================================================================

class TestPipelineAudit:

    def test_fills_system_and_user_prompt(self, fake_llm, fake_db, fake_schema_loader):
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.system_prompt is not None
        assert result.user_prompt is not None

    def test_fills_llm_raw_output(self, fake_llm, fake_db, fake_schema_loader):
        fake_llm.chat.return_value = "```sql\nSELECT 1;\n```"
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.llm_raw_output == "```sql\nSELECT 1;\n```"


# =============================================================================
# ERREURS — LLM down
# =============================================================================

class TestPipelineErrors:

    def test_catches_llm_failure(self, fake_llm, fake_db, fake_schema_loader):
        """Si Ollama plante, on doit retourner result.error sans crasher."""
        fake_llm.chat.side_effect = RuntimeError("Ollama injoignable")
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.error is not None
        assert "Ollama" in result.error

    def test_catches_schema_loader_failure(self, fake_llm, fake_db, fake_schema_loader):
        """Si le SchemaLoader plante, idem."""
        fake_schema_loader.get_schema_and_stats.side_effect = RuntimeError("DB down")
        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.error is not None

    def test_rejects_dangerous_sql(self, fake_llm, fake_db, fake_schema_loader):
        """Si le LLM renvoie un DROP TABLE, on doit refuser proprement."""
        fake_llm.chat.return_value = "```sql\nDROP TABLE declarations;\n```"
        result = run_pipeline(
            question="supprime tout",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.error is not None
        assert "interdite" in result.error.lower()
        # Le DB ne doit JAMAIS avoir été appelé
        fake_db.execute.assert_not_called()


# =============================================================================
# AUTO-REPAIR — retry après erreur PostgreSQL
# =============================================================================

class TestPipelineAutoRepair:

    def test_retries_on_pg_error(self, fake_llm, fake_db, fake_schema_loader):
        """
        1ère exec PG plante → le pipeline rappelle le LLM avec l'erreur,
        2e exec réussit → succès.
        """
        # 1er .execute() plante, 2e réussit
        fake_db.execute.side_effect = [
            RuntimeError("column 'foo' does not exist"),
            (["count"], [[42]]),
        ]
        # Le LLM renvoie 2 SQL différents (initial + corrigé)
        fake_llm.chat.side_effect = [
            "```sql\nSELECT foo FROM declarations;\n```",
            "```sql\nSELECT COUNT(*) FROM declarations;\n```",
        ]

        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )

        # Le retry doit avoir réussi
        assert result.error is None
        assert result.row_count == 1
        # LLM appelé 2 fois (initial + repair)
        assert fake_llm.chat.call_count == 2
        # DB appelé 2 fois
        assert fake_db.execute.call_count == 2

    def test_gives_up_after_repair_fails(self, fake_llm, fake_db, fake_schema_loader):
        """Si même après repair ça plante, on retourne error."""
        fake_db.execute.side_effect = RuntimeError("syntax error")
        fake_llm.chat.return_value = "```sql\nSELECT broken FROM nowhere;\n```"

        result = run_pipeline(
            question="test",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )

        assert result.error is not None
        assert "syntax error" in result.error


# =============================================================================
# HORS-PÉRIMÈTRE
# =============================================================================

class TestPipelineOutOfSchema:

    def test_detects_hors_schema_marker(self, fake_llm, fake_db, fake_schema_loader):
        """Si le LLM renvoie le marqueur, on remplit warning sans exécuter."""
        fake_llm.chat.return_value = "-- QUESTION_HORS_SCHEMA"
        result = run_pipeline(
            question="quelle est la météo ?",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.warning is not None
        assert "hors périmètre" in result.warning.lower()
        # Pas d'exécution DB
        fake_db.execute.assert_not_called()

    def test_no_error_when_hors_schema(self, fake_llm, fake_db, fake_schema_loader):
        """warning ≠ error : ce n'est pas une erreur technique."""
        fake_llm.chat.return_value = "-- QUESTION_HORS_SCHEMA"
        result = run_pipeline(
            question="bonjour",
            schema_loader=fake_schema_loader,
            llm_client=fake_llm,
            db_connector=fake_db,
        )
        assert result.error is None
        assert result.warning is not None
