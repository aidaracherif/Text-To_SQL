from infrastructure.vectorstore.qdrant_client import QdrantStore
from infrastructure.llm.ollama_client import OllamaClient
from features.rag.indexer import RAGIndexer


def main():
    print("🚀 Lancement de l'indexation RAG...")

    store = QdrantStore()
    llm = OllamaClient()

    indexer = RAGIndexer(store=store, llm=llm)
    indexer.run_all()

    print("✅ Indexation terminée.")


if __name__ == "__main__":
    main()

