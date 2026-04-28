# """
# features/rag/indexer.py — Indexation des catalogues dans Qdrant.
# À lancer une seule fois (ou après mise à jour des catalogues).
# """

# from infrastructure.vectorstore.qdrant_client import QdrantStore
# from infrastructure.llm.ollama_client import OllamaClient
# from config.settings import QDRANT_COLLECTIONS, EMBED_DIM

# from features.rag.catalog import SQL_EXAMPLES, KNOWLEDGE, SCHEMA


# class RAGIndexer:
#     """
#     Transforme les 3 catalogues en vecteurs et les insère dans Qdrant.
#     """

#     def __init__(self, store: QdrantStore = None, llm: OllamaClient = None):
#         self.store = store or QdrantStore()
#         self.llm   = llm   or OllamaClient()

#     def _embed(self, text: str) -> list[float]:
#         return self.llm.embed(text)

#     def create_collections(self) -> None:
#         """Crée les 3 collections si elles n'existent pas."""
#         for name in QDRANT_COLLECTIONS.values():
#             self.store.ensure_collection(name, dim=EMBED_DIM)
#         print("✅ Collections Qdrant prêtes.")

#     def index_sql_examples(self) -> None:
#         """Indexe les paires question/SQL."""
#         points = []
#         for i, ex in enumerate(SQL_EXAMPLES):
#             vector = self._embed(ex["question"])
#             points.append({
#                 "id": i,
#                 "vector": vector,
#                 "payload": {"question": ex["question"], "sql": ex["sql"]},
#             })
#         self.store.upsert(QDRANT_COLLECTIONS["sql_examples"], points)
#         print(f"✅ {len(points)} exemples SQL indexés.")

#     def index_knowledge(self) -> None:
#         """Indexe les règles métier douanières."""
#         points = []
#         for i, item in enumerate(KNOWLEDGE):
#             vector = self._embed(item["contenu"])
#             points.append({
#                 "id": i,
#                 "vector": vector,
#                 "payload": {"titre": item["titre"], "contenu": item["contenu"]},
#             })
#         self.store.upsert(QDRANT_COLLECTIONS["knowledge"], points)
#         print(f"✅ {len(points)} entrées de connaissance indexées.")

#     def index_schema(self) -> None:
#         """Indexe les descriptions de tables."""
#         points = []
#         for i, item in enumerate(SCHEMA):
#             vector = self._embed(item["description"])
#             points.append({
#                 "id": i,
#                 "vector": vector,
#                 "payload": {"table": item["table"], "description": item["description"]},
#             })
#         self.store.upsert(QDRANT_COLLECTIONS["schema"], points)
#         print(f"✅ {len(points)} descriptions de tables indexées.")

#     def run_all(self) -> None:
#         """Lance l'indexation complète."""
#         print("🔄 Création des collections...")
#         self.create_collections()
#         print("🔄 Indexation des exemples SQL...")
#         self.index_sql_examples()
#         print("🔄 Indexation des connaissances métier...")
#         self.index_knowledge()
#         print("🔄 Indexation du schéma...")
#         self.index_schema()
#         print("\n✅ Indexation RAG terminée !")

"""
features/rag/indexer.py — Indexation des catalogues dans Qdrant.
À lancer une seule fois (ou après mise à jour des catalogues).
"""

from infrastructure.vectorstore.qdrant_client import QdrantStore
from infrastructure.llm.ollama_client import OllamaClient
from config.settings import QDRANT_COLLECTIONS, EMBED_DIM

from features.rag.catalog import SQL_EXAMPLES, KNOWLEDGE, SCHEMA


class RAGIndexer:
    """
    Transforme les 3 catalogues en vecteurs et les insère dans Qdrant.
    """

    def __init__(self, store: QdrantStore = None, llm: OllamaClient = None):
        self.store = store or QdrantStore()
        self.llm   = llm   or OllamaClient()

    def _embed(self, text: str) -> list[float]:
        return self.llm.embed(text)

    def create_collections(self) -> None:
        """Crée les 3 collections si elles n'existent pas."""
        for name in QDRANT_COLLECTIONS.values():
            self.store.ensure_collection(name, dim=EMBED_DIM)
        print("✅ Collections Qdrant prêtes.")

    def index_sql_examples(self) -> None:
        """Indexe les paires question/SQL."""
        points = []
        for i, ex in enumerate(SQL_EXAMPLES):
            vector = self._embed(ex["question"])
            points.append({
                "id": i,
                "vector": vector,
                "payload": {"question": ex["question"], "sql": ex["sql"]},
            })
        self.store.upsert(QDRANT_COLLECTIONS["sql_examples"], points)
        print(f"✅ {len(points)} exemples SQL indexés.")

    def index_knowledge(self) -> None:
        """Indexe les règles métier douanières."""
        points = []
        for i, item in enumerate(KNOWLEDGE):
            vector = self._embed(item["contenu"])
            points.append({
                "id": i,
                "vector": vector,
                "payload": {"titre": item["titre"], "contenu": item["contenu"]},
            })
        self.store.upsert(QDRANT_COLLECTIONS["knowledge"], points)
        print(f"✅ {len(points)} entrées de connaissance indexées.")

    def index_schema(self) -> None:
        """Indexe les descriptions de tables."""
        points = []
        for i, item in enumerate(SCHEMA):
            vector = self._embed(item["description"])
            points.append({
                "id": i,
                "vector": vector,
                "payload": {"table": item["table"], "description": item["description"]},
            })
        self.store.upsert(QDRANT_COLLECTIONS["schema"], points)
        print(f"✅ {len(points)} descriptions de tables indexées.")

    def run_all(self) -> None:
        """Lance l'indexation complète."""
        print("🔄 Création des collections...")
        self.create_collections()
        print("🔄 Indexation des exemples SQL...")
        self.index_sql_examples()
        print("🔄 Indexation des connaissances métier...")
        self.index_knowledge()
        print("🔄 Indexation du schéma...")
        self.index_schema()
        print("\n✅ Indexation RAG terminée !")

