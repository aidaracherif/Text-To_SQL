"""
infrastructure/vectorstore/qdrant_client.py — Wrapper Qdrant.
Responsabilité unique : créer des collections, insérer et chercher des vecteurs.
"""

from qdrant_client import QdrantClient as _QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter
)
from config.settings import QDRANT_HOST, QDRANT_PORT, EMBED_DIM


class QdrantStore:
    """
    Abstraction autour du client Qdrant officiel.
    """

    def __init__(self, host: str = QDRANT_HOST, port: int = QDRANT_PORT):
        self.client = _QdrantClient(host=host, port=port)

    # ──────────────────────────────────────────────────────────────────────────
    # Collections
    # ──────────────────────────────────────────────────────────────────────────

    def ensure_collection(self, name: str, dim: int = EMBED_DIM) -> None:
        """Crée la collection si elle n'existe pas."""
        existing = {c.name for c in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def delete_collection(self, name: str) -> None:
        self.client.delete_collection(name)

    # ──────────────────────────────────────────────────────────────────────────
    # Insertion
    # ──────────────────────────────────────────────────────────────────────────

    def upsert(self, collection: str, points: list[dict]) -> None:
        """
        Insère ou met à jour des points.

        points : liste de { "id": int, "vector": list[float], "payload": dict }
        """
        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
                for p in points
            ],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Recherche
    # ──────────────────────────────────────────────────────────────────────────

    # def search(self, collection: str, vector: list[float], top_k: int = 3) -> list[dict]:
    #     """
    #     Cherche les top_k vecteurs les plus proches.
    #     Retourne une liste de payloads avec leur score.
    #     """
    #     results = self.client.query_points(
    #         collection_name=collection,
    #         query_vector=vector,
    #         limit=top_k,
    #         with_payload=True,
    #     )
    #     return [
    #         {"score": r.score, **r.payload}
    #         for r in results
    #     ]
    def search(self, collection: str, vector: list[float], top_k: int = 3) -> list[dict]:
        results = self.client.query_points(
        collection_name=collection,
        query=vector,  
        limit=top_k,
        with_payload=True,
    )

        return [
        {"score": r.score, **r.payload}
        for r in results.points  
    ]

    def is_alive(self) -> bool:
        """Vérifie que Qdrant répond."""
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False
