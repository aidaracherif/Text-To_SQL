"""
api/dependencies.py — Injection de dépendances FastAPI.

FastAPI n'a pas de session_state comme Streamlit.
On utilise un singleton module-level pour conserver le service en mémoire
entre les requêtes (même comportement que st.session_state côté Streamlit).

Usage dans un router :
    from api.dependencies import get_service
    
    @router.post("/query")
    async def query(service: TextToSQLService = Depends(get_service)):
        ...
"""

import logging
from functools import lru_cache

from features.text_to_sql.service import TextToSQLService
from features.voice.transcriber import VoiceTranscriber
from features.voice.question_cleaner import QuestionCleaner
from features.document_extraction.pdf_reader import PDFReader
from features.document_extraction.question_builder import QuestionBuilder
from infrastructure.vectorstore.qdrant_client import QdrantStore
from infrastructure.vectorstore.smart_retriever import SmartRetriever
from infrastructure.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

def _build_rag_retriever() -> SmartRetriever | None:
    """
    Tente d'initialiser le Retriever RAG.
    Retourne None si Qdrant est indisponible (fallback silencieux).
    Identique à la logique de pipeline_runner.py de l'ancienne version.
    """
    try:
        store = QdrantStore()
        if not store.is_alive():
            logger.warning("Qdrant indisponible — mode sans RAG activé.")
            return None
        llm = OllamaClient()
        retriever = SmartRetriever(qdrant_store=store, llm_client=llm)
        logger.info("RAG initialisé avec succès.")
        return retriever
    except Exception as e:
        logger.warning(f"Impossible d'initialiser le RAG : {e} — mode sans RAG activé.")
        return None


@lru_cache(maxsize=1)
def get_service() -> TextToSQLService:
    """
    Retourne l'unique instance de TextToSQLService (singleton).

    @lru_cache(maxsize=1) garantit qu'on ne crée le service qu'une seule fois,
    même si get_service() est appelé depuis plusieurs requêtes simultanées.
    Équivalent exact de st.session_state["service"] en Streamlit.
    """
    logger.info("Initialisation de TextToSQLService...")
    rag_retriever = _build_rag_retriever()
    service = TextToSQLService(rag_retriever=rag_retriever)
    logger.info("TextToSQLService prêt.")
    return service

# =============================================================================
# 🆕 Service Vocal
# =============================================================================

@lru_cache(maxsize=1)
def get_voice_transcriber() -> VoiceTranscriber:
    """
    Singleton VoiceTranscriber.
    NB : le modèle Whisper n'est PAS chargé ici (lazy loading au 1er appel).
    """
    logger.info("Initialisation de VoiceTranscriber (modèle chargé à la demande)...")
    return VoiceTranscriber()


@lru_cache(maxsize=1)
def get_question_cleaner() -> QuestionCleaner:
    """Singleton QuestionCleaner (réutilise le client Ollama global)."""
    return QuestionCleaner(llm_client=OllamaClient())



# =============================================================================
# 🆕 Service Document/PDF
# =============================================================================

@lru_cache(maxsize=1)
def get_pdf_reader() -> PDFReader:
    """Singleton PDFReader."""
    return PDFReader()


@lru_cache(maxsize=1)
def get_question_builder() -> QuestionBuilder:
    """Singleton QuestionBuilder pour les PDF."""
    return QuestionBuilder(llm_client=OllamaClient())
