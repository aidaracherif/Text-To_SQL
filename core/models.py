"""
core/models.py — Structures de données partagées dans tout le projet.
Aucune dépendance externe hormis dataclasses / typing.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Any
import pandas as pd


@dataclass
class QueryResult: # Résultat d'une question posée à TextToSQLService.ask()
    """
    Résultat complet d'un pipeline Text-to-SQL.
    Produit par features/text_to_sql/service.py et consommé par l'UI.
    """
    question:   str
    sql:        Optional[str]     = None
    columns:    List[str]         = field(default_factory=list)
    rows:       List[List[Any]]   = field(default_factory=list)
    narrative:  Optional[str]     = None
    row_count:  int               = 0
    warning:    Optional[str]     = None
    error:      Optional[str]     = None
    duration_ms: float            = 0.0

    # ── Champs d'audit (optionnels, remplis par le pipeline pour la traçabilité) ──
    rag_context:    Optional[dict] = None     # {sql_examples, knowledge, schema_chunks}
    rag_route:      Optional[str]  = None     # "direct" | "sql_only" | "knowledge" | "schema" | "full"
    system_prompt:  Optional[str]  = None     # prompt système envoyé au LLM
    user_prompt:    Optional[str]  = None     # prompt user envoyé au LLM
    llm_raw_output: Optional[str]  = None     # réponse brute du LLM avant extraction SQL

    @property # Convertit les résultats en DataFrame pour l'affichage dans l'UI.
    def dataframe(self) -> pd.DataFrame:
        if self.columns and self.rows:
            return pd.DataFrame(self.rows, columns=self.columns)
        return pd.DataFrame()

    @property # Indique si la requête a réussi (pas d'erreur et SQL généré).
    def success(self) -> bool: 
        return self.error is None and self.sql is not None
    
    @property
    def to_dict(self): # Convertit le résultat en dict pour l'UI (exclut les champs non nécessaires).
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "error": self.error,
            "narrative": self.narrative,
    }


@dataclass
class SchemaTable: # Représentation d'une table du schéma de BDD.
    """Représentation d'une table du schéma de BDD."""
    name:         str
    comment:      str                   = ""
    columns:      List[dict]            = field(default_factory=list)
    foreign_keys: List[dict]            = field(default_factory=list)


@dataclass
class RAGContext: # Contexte récupéré par le RAG avant la génération SQL.
    """Contexte récupéré par le RAG avant la génération SQL."""
    sql_examples:  List[dict] = field(default_factory=list)
    knowledge:     List[dict] = field(default_factory=list)
    schema_chunks: List[dict] = field(default_factory=list)


@dataclass
class AuditEntry: # Entrée dans le journal d'audit de session.
    """Entrée dans le journal d'audit de session."""
    date:        str
    heure:       str
    utilisateur: str
    question:    str
    sql:         str
    statut:      str
    lignes:      int
    dur_ms:      float