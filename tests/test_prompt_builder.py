"""
Tests unitaires pour core/prompt_builder.py

Couvre :
  - build_system_prompt() : prompt système avec/sans stats
  - build_rag_prompt() : intégration du contexte RAG dans le prompt
"""

import pytest

from core.prompt_builder import build_system_prompt, build_rag_prompt


# =============================================================================
# build_system_prompt()
# =============================================================================

class TestBuildSystemPrompt:

    def test_includes_schema(self):
        prompt = build_system_prompt("TABLE foo (id INT)")
        assert "TABLE foo (id INT)" in prompt

    def test_includes_stats_when_provided(self):
        prompt = build_system_prompt("schema...", "STATS: 100 lignes")
        assert "STATS: 100 lignes" in prompt

    def test_works_without_stats(self):
        """stats est optionnel, ne doit pas crasher."""
        prompt = build_system_prompt("schema...")
        assert prompt  # non-vide
        assert "schema..." in prompt

    def test_mentions_postgres(self):
        """Le prompt doit cadrer le LLM sur PostgreSQL."""
        prompt = build_system_prompt("schema...")
        assert "PostgreSQL" in prompt

    def test_mentions_select_only_rule(self):
        """Le prompt doit interdire les écritures."""
        prompt = build_system_prompt("schema...")
        # On vérifie qu'au moins une mention de la restriction est présente
        assert "SELECT" in prompt
        # Doit interdire les opérations dangereuses
        forbidden_mentioned = any(
            kw in prompt for kw in ["INSERT", "UPDATE", "DELETE", "DROP"]
        )
        assert forbidden_mentioned

    def test_mentions_hors_schema_convention(self):
        """Le LLM doit savoir comment indiquer une question hors périmètre."""
        prompt = build_system_prompt("schema...")
        assert "QUESTION_HORS_SCHEMA" in prompt


# =============================================================================
# build_rag_prompt()
# =============================================================================

class TestBuildRagPrompt:

    def test_includes_question_at_end(self):
        """La question doit être en fin (recency bias)."""
        prompt = build_rag_prompt("ma question", {})
        assert prompt.rstrip().endswith("ma question")

    def test_works_with_empty_context(self):
        """Si le contexte est vide, le prompt doit quand même être valide."""
        prompt = build_rag_prompt("test", {})
        assert "test" in prompt
        # Ne doit pas crasher

    def test_includes_sql_examples(self, sample_rag_context):
        prompt = build_rag_prompt("test", sample_rag_context)
        assert "SELECT COUNT(*) FROM declarations" in prompt

    def test_includes_knowledge(self, sample_rag_context):
        prompt = build_rag_prompt("test", sample_rag_context)
        assert "déclaration douanière" in prompt.lower()

    def test_includes_schema_chunks(self, sample_rag_context):
        prompt = build_rag_prompt("test", sample_rag_context)
        assert "declarations" in prompt

    def test_high_score_uses_direct_instruction(self):
        """Score >= 0.88 → instruction 'adapte directement'."""
        context = {
            "sql_examples": [
                {"question": "Q", "sql": "SELECT 1;", "score": 0.95}
            ],
            "knowledge": [],
            "schema_chunks": [],
        }
        prompt = build_rag_prompt("test", context)
        assert "directement" in prompt.lower()

    def test_low_score_uses_inspiration_instruction(self):
        """Score moyen → instruction 'inspire-toi'."""
        context = {
            "sql_examples": [
                {"question": "Q", "sql": "SELECT 1;", "score": 0.50}
            ],
            "knowledge": [],
            "schema_chunks": [],
        }
        prompt = build_rag_prompt("test", context)
        # "référence" ou similaire pour les scores bas
        assert "référence" in prompt.lower() or "exemples" in prompt.lower()

    def test_includes_reminder_at_top(self):
        """Le rappel des règles doit être présent (ancre de contrainte)."""
        prompt = build_rag_prompt("test", {})
        assert "RAPPEL" in prompt
        assert "QUESTION_HORS_SCHEMA" in prompt

    def test_handles_missing_rag_keys(self):
        """Si certaines clés du contexte manquent, ne doit pas crasher."""
        # Contexte partiel — pas de schema_chunks
        context = {"sql_examples": [], "knowledge": []}
        prompt = build_rag_prompt("test", context)
        assert prompt  # non-vide
        assert "test" in prompt
