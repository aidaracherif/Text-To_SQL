"""
Tests unitaires pour infrastructure/vectorstore/smart_retriever.py

Couvre :
  - Détection des signaux lexicaux (knowledge / schema / direct)
  - Route DIRECT quand score ≥ 0.88
  - Route DIRECT via pattern lexical
  - Route SQL_ONLY quand score moyen
  - Route KNOWLEDGE / SCHEMA / FULL selon les signaux
  - Filtrage des résultats sous le seuil minimum
"""

import pytest
from unittest.mock import MagicMock

from infrastructure.vectorstore.smart_retriever import (
    SmartRetriever,
    _needs_knowledge,
    _needs_schema,
    _is_direct_pattern,
    THRESHOLD_DIRECT,
    THRESHOLD_INCLUDE,
)


# =============================================================================
# Détecteurs lexicaux (fonctions pures)
# =============================================================================

class TestLexicalSignals:

    @pytest.mark.parametrize("question", [
        "Qu'est-ce qu'un régime douanier ?",
        "Différence entre transit et admission temporaire",
        "Comment fonctionne la TVA ?",
        "Définition de NINEA",
        "Pourquoi liquidée et non abandonnée ?",
    ])
    def test_detects_knowledge_signals(self, question):
        assert _needs_knowledge(question) is True

    @pytest.mark.parametrize("question", [
        "Quelle table contient les déclarations ?",
        "Structure du schéma de bureau",
        "Jointure entre opérateur et déclaration",
        "Les champs de la table marchandise",
    ])
    def test_detects_schema_signals(self, question):
        assert _needs_schema(question) is True

    @pytest.mark.parametrize("question", [
        "Quelle est la météo à Dakar",
        "Quelle heure est-il",
        "Comptez jusqu'à 10",
    ])
    def test_no_signal_for_unrelated(self, question):
        """
        Questions vraiment hors-sujet : aucun signal ne doit matcher.
        NOTE : la liste _KNOWLEDGE_SIGNALS contient des mots génériques comme
        "comment", "pourquoi", "expliqu" — donc des questions banales du type
        "Bonjour comment ça va" peuvent déclencher knowledge à tort.
        Voir test_known_false_positives ci-dessous.
        """
        assert _needs_knowledge(question) is False
        assert _needs_schema(question) is False

    @pytest.mark.parametrize("question", [
        "Bonjour comment ça va",      # "comment" est un signal knowledge
        "Pourquoi pas un café",        # "pourquoi" est un signal knowledge
    ])
    def test_known_false_positives(self, question):
        """
        Faux positifs connus du routage lexical actuel.
        Si la liste des signaux est nettoyée plus tard, ce test devra évoluer.
        Documente la limite plutôt que de la cacher.
        """
        # Au moins UN des deux détecteurs renvoie True (faux positif documenté)
        assert _needs_knowledge(question) or _needs_schema(question)

    @pytest.mark.parametrize("question", [
        "Combien de déclarations ?",
        "Liste des bureaux",
        "Top 10 des opérateurs",
        "Total des taxes",
        "Déclarations en 2024",
        "Opérateurs suspendus",
    ])
    def test_detects_direct_patterns(self, question):
        assert _is_direct_pattern(question) is True

    def test_unrelated_question_not_direct(self):
        assert _is_direct_pattern("Quelle est la météo ?") is False


# =============================================================================
# SmartRetriever.retrieve() — routage complet
# =============================================================================

class TestSmartRetrieverRouting:

    def _make_retriever(self, llm_client):
        """Crée un SmartRetriever avec un store mocké."""
        store = MagicMock()
        retriever = SmartRetriever(qdrant_store=store, llm_client=llm_client)
        # On override les noms de collections pour matcher le code interne
        retriever.collections = {
            "sql_examples": "sql_examples",
            "knowledge": "knowledge",
            "schema": "schema",
        }
        return retriever, store

    def test_direct_route_when_score_above_threshold(self, fake_llm):
        """Score ≥ 0.88 → route DIRECT, pas de 2e passe."""
        retriever, store = self._make_retriever(fake_llm)
        store.search.return_value = [{"score": 0.95, "sql": "SELECT 1"}]

        ctx = retriever.retrieve("question random sans signal lexical")

        assert ctx["_route"] == "direct"
        # Une seule recherche : sql_examples uniquement
        assert store.search.call_count == 1
        # Knowledge et schema_chunks doivent être vides
        assert ctx["knowledge"] == []
        assert ctx["schema_chunks"] == []

    def test_direct_route_via_pattern_match(self, fake_llm):
        """Pattern lexical matché → DIRECT même avec score moyen."""
        retriever, store = self._make_retriever(fake_llm)
        store.search.return_value = [{"score": 0.60, "sql": "SELECT COUNT(*)"}]

        ctx = retriever.retrieve("Combien de déclarations en 2024")
        assert ctx["_route"] == "direct"
        # Pas de 2e passe
        assert store.search.call_count == 1

    def test_knowledge_route_for_definition_question(self, fake_llm):
        """Question de définition → route KNOWLEDGE uniquement."""
        retriever, store = self._make_retriever(fake_llm)

        # Premier appel = sql_examples (score moyen), 2ème = knowledge
        store.search.side_effect = [
            [{"score": 0.50}],   # sql_examples
            [{"score": 0.70}],   # knowledge
        ]

        ctx = retriever.retrieve("Qu'est-ce qu'un régime douanier ?")
        assert ctx["_route"] == "knowledge"
        # 2 recherches : sql + knowledge (pas schema car pas de signal schéma)
        assert store.search.call_count == 2

    def test_schema_route_for_structure_question(self, fake_llm):
        """Question de structure → route SCHEMA uniquement."""
        retriever, store = self._make_retriever(fake_llm)
        store.search.side_effect = [
            [{"score": 0.50}],   # sql_examples
            [{"score": 0.70}],   # schema
        ]
        ctx = retriever.retrieve("Quelle est la jointure entre les tables ?")
        assert ctx["_route"] == "schema"

    def test_full_route_when_no_signal(self, fake_llm):
        """Aucun signal lexical clair → mode FULL (les 3 collections)."""
        retriever, store = self._make_retriever(fake_llm)
        store.search.return_value = [{"score": 0.50}]

        ctx = retriever.retrieve("question vague et générique")
        assert ctx["_route"] == "full"
        # 3 recherches : sql + knowledge + schema
        assert store.search.call_count == 3

    def test_filters_low_score_results(self, fake_llm):
        """Les résultats sous THRESHOLD_INCLUDE (0.45) doivent être filtrés."""
        retriever, store = self._make_retriever(fake_llm)
        store.search.return_value = [
            {"score": 0.30},  # Sous le seuil → filtré
            {"score": 0.55},  # Au-dessus → gardé
        ]

        ctx = retriever.retrieve("Combien de déclarations en 2024")
        # Pattern direct → on s'arrête après sql_examples
        assert len(ctx["sql_examples"]) == 1
        assert ctx["sql_examples"][0]["score"] == 0.55


# =============================================================================
# Cohérence des seuils (sanity check)
# =============================================================================

class TestThresholds:

    def test_threshold_direct_higher_than_include(self):
        """THRESHOLD_DIRECT (route directe) > THRESHOLD_INCLUDE (filtre bruit)."""
        assert THRESHOLD_DIRECT > THRESHOLD_INCLUDE

    def test_threshold_direct_reasonable(self):
        """THRESHOLD_DIRECT entre 0.7 et 1.0 (sinon trop restrictif/permissif)."""
        assert 0.7 <= THRESHOLD_DIRECT <= 1.0

    def test_threshold_include_reasonable(self):
        assert 0.0 < THRESHOLD_INCLUDE <= 0.7
