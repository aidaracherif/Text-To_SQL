"""
infrastructure/vectorstore/smart_retriever.py — Retriever intelligent à 2 passes.

STRATÉGIE :
  Passe 1 — Embed la question + cherche UNIQUEMENT dans sql_examples.
             Si le meilleur score ≥ THRESHOLD_DIRECT → on s'arrête.
             Une seule recherche vectorielle, ~50ms gagnés sur M2.

  Passe 2 — Score insuffisant → analyse lexicale de la question pour décider
             quelles collections complémentaires interroger :
               - Signaux métier  → knowledge
               - Signaux schéma  → db_schema
               - Question vague  → les deux (mode FULL)

  Résultat : contexte identique à Retriever, mais avec 1, 2 ou 3 recherches
             selon la nature de la question.
"""

import re
import logging
from config.settings import QDRANT_COLLECTIONS, RAG_TOP_K
from infrastructure.vectorstore.qdrant_client import QdrantStore

logger = logging.getLogger(__name__)

# =============================================================================
# SEUILS
# =============================================================================

# Score cosinus ≥ THRESHOLD_DIRECT → l'exemple SQL est quasi-identique,
# pas besoin d'enrichir davantage.
THRESHOLD_DIRECT  = 0.88

# Score minimum pour inclure un résultat dans le contexte (filtre le bruit).
THRESHOLD_INCLUDE = 0.45

# =============================================================================
# SIGNAUX LEXICAUX
# =============================================================================

_KNOWLEDGE_SIGNALS = {
    "régime", "regime", "transit", "admission", "temporaire",
    "importation", "exportation", "zone franche",
    "tva", "taxe", "droit", "dd", "pcs", "pe", "rs",
    "contentieux", "liquidée", "liquidee", "abandonnée", "abandonnee",
    "statut", "cycle", "ninea", "transitaire", "caution", "garantie",
    "cif", "taux", "exonér", "exoner",
    "qu'est-ce", "c'est quoi", "expliqu", "définition",
    "comment", "différence", "difference", "pourquoi",
}

_SCHEMA_SIGNALS = {
    "table", "colonne", "jointure", "join", "clé", "cle",
    "structure", "schéma", "schema", "champ",
    "bureau", "bureaux", "pays", "marchandise",
    "déclaration", "declaration", "opérateur", "operateur",
    "droits_taxes", "regimes",
}

# Patterns quasi-identiques à une question du catalogue → passe directe
_DIRECT_PATTERNS = [
    r"combien de d[ée]clarations",
    r"liste des? bureaux",
    r"liste des? op[ée]rateurs",
    r"^top\s+\d+",
    r"r[ée]partition des? d[ée]clarations",
    r"nombre de d[ée]clarations",
    r"total des? taxes",
    r"total des? droits",
    r"d[ée]clarations en \d{4}",
    r"d[ée]clarations (en|par) statut",
    r"montant.*tva",
    r"tva.*\d{4}",
    r"op[ée]rateurs suspendus",
    r"r[ée]gimes douaniers",
]

# =============================================================================
# ROUTEUR INTERNE
# =============================================================================

def _needs_knowledge(question: str) -> bool:
    q = question.lower()
    return any(sig in q for sig in _KNOWLEDGE_SIGNALS)

def _needs_schema(question: str) -> bool:
    q = question.lower()
    return any(sig in q for sig in _SCHEMA_SIGNALS)

def _is_direct_pattern(question: str) -> bool:
    q = question.lower().strip()
    return any(re.search(p, q) for p in _DIRECT_PATTERNS)

# =============================================================================
# SMART RETRIEVER
# =============================================================================

class SmartRetriever:
    """
    Retriever à 2 passes avec routage intelligent.
    Interface identique à Retriever pour une compatibilité totale.
    """

    def __init__(self, qdrant_store: QdrantStore, llm_client):
        self.store       = qdrant_store
        self.llm_client  = llm_client
        self.collections = QDRANT_COLLECTIONS

    def _embed(self, text: str) -> list[float]:
        return self.llm_client.embed(text)

    def _search(self, collection_key: str, vector: list[float], top_k: int) -> list[dict]:
        """Cherche et filtre les résultats sous le seuil minimum."""
        raw = self.store.search(self.collections[collection_key], vector, top_k=top_k)
        return [r for r in raw if r.get("score", 0) >= THRESHOLD_INCLUDE]

    def retrieve(self, question: str, top_k: int = RAG_TOP_K) -> dict:
        """
        Retourne le contexte RAG en 1, 2 ou 3 recherches Qdrant.

        Format retourné (compatible Retriever) :
            {
                "sql_examples":  [...],
                "knowledge":     [...],
                "schema_chunks": [...],
                "_route":        "direct" | "sql_only" | "knowledge" | "schema" | "full",
            }
        Le champ "_route" est purement informatif (audit/debug) et préfixé
        d'un underscore pour signaler qu'il n'est pas une collection.
        """
        context = {"sql_examples": [], "knowledge": [], "schema_chunks": []}

        # ── Embed unique pour toutes les collections ──────────────────────────
        vector = self._embed(question)

        # ── PASSE 1 : sql_examples seulement ─────────────────────────────────
        sql_hits  = self._search("sql_examples", vector, top_k=top_k)
        best      = sql_hits[0]["score"] if sql_hits else 0.0
        context["sql_examples"] = sql_hits

        route = "sql_only"

        # ── ROUTE DIRECTE : exemple quasi-identique ───────────────────────────
        if best >= THRESHOLD_DIRECT or _is_direct_pattern(question):
            route = "direct"
            logger.info(f"[SmartRetriever] DIRECT — score={best:.3f} | question={question[:60]}")
            context["_route"] = route
            return context

        # ── PASSE 2 : collections complémentaires ─────────────────────────────
        need_k = _needs_knowledge(question)
        need_s = _needs_schema(question)

        # Aucun signal clair → on prend les deux (sécurité)
        if not need_k and not need_s:
            need_k = need_s = True 

        if need_k:
            context["knowledge"]     = self._search("knowledge", vector, top_k=2)
            route = "knowledge" if not need_s else "full"
        if need_s:
            context["schema_chunks"] = self._search("schema",    vector, top_k=2)
            route = "schema" if not need_k else "full"

        logger.info(
            f"[SmartRetriever] {route.upper()} — score={best:.3f} "
            f"| k={len(context['knowledge'])} s={len(context['schema_chunks'])} "
            f"| question={question[:60]}"
        )
        context["_route"] = route
        return context

    def explain(self, question: str) -> None:
        """Affiche les décisions de routing dans le terminal (debug)."""
        best_pattern = _is_direct_pattern(question)
        need_k = _needs_knowledge(question)
        need_s = _needs_schema(question)

        print(f"\nQuestion : {question}")
        if best_pattern:
            print("  Route   : DIRECT (pattern catalogue détecté)")
            print("  Collections : sql_examples uniquement")
        elif not need_k and not need_s:
            print("  Route   : FULL (aucun signal spécifique)")
            print("  Collections : sql_examples + knowledge + schema")
        else:
            cols = ["sql_examples"]
            if need_k: cols.append("knowledge")
            if need_s: cols.append("schema")
            print(f"  Route   : {' + '.join(cols)}")
            print(f"  Collections : {', '.join(cols)}")