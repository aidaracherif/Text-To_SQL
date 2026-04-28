import logging
from core.pipeline import run_pipeline
from core.models import QueryResult
from infrastructure.llm.ollama_client import OllamaClient
from infrastructure.database.schema_loader import SchemaLoader
from infrastructure.database.db_connector import DBConnector

logger = logging.getLogger(__name__)


class TextToSQLService:

    def __init__( # Permet d'injecter des dépendances pour faciliter les tests unitaires.
        self,
        llm_client: OllamaClient = None,
        schema_loader: SchemaLoader = None, 
        db_connector: DBConnector = None, #
        rag_retriever=None,
    ):
        self.llm = llm_client or OllamaClient() #  
        self.schema = schema_loader or SchemaLoader()
        self.db = db_connector or DBConnector()
        self.rag = rag_retriever # RAG est optionnel, on peut fonctionner sans.

    def ask(self, question: str, verbose: bool = False) -> QueryResult:
        try:
            logger.info(f"Question: {question}")

            result = run_pipeline(
                question=question,
                schema_loader=self.schema,
                llm_client=self.llm,
                db_connector=self.db,
                rag_retriever=self.rag,
                verbose=verbose,
            )

            if not isinstance(result, QueryResult):
                raise TypeError("Le pipeline doit retourner un QueryResult")

            return result

        except Exception as e:
            logger.error(f"Erreur pipeline: {e}")

            return QueryResult(
                question=question,
                sql="",
                columns=[],
                rows=[],
                error=str(e)
            )

    def health_check(self) -> dict:
        return {
            "llm": self.llm.is_alive(),
            "db": self.db.test_connection(),
            "rag": (
                hasattr(self.rag, "store") and self.rag.store.is_alive()
            ) if self.rag else None,
        }