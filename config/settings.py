"""
=============================================================================
SETTINGS — Text-to-SQL DGD Sénégal
=============================================================================
Centralise toute la configuration du projet.
Les valeurs sensibles sont lues depuis le fichier .env à la racine.
=============================================================================
"""

import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# BASE DE DONNÉES PostgreSQL
# =============================================================================

DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     os.getenv("DB_PORT"),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# =============================================================================
# OLLAMA / LLM
# =============================================================================

OLLAMA_URL   = os.getenv("OLLAMA_URL") 
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") 

LLM_OPTIONS = {
    "temperature": 0.0,   # 0 = déterministe (critique pour SQL)
    "top_p":       1.0,
    "num_predict": 512,
}

LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S"))

# =============================================================================
# QDRANT (vectorstore)
# =============================================================================

QDRANT_URL  = os.getenv("QDRANT_URL",)
QDRANT_HOST = os.getenv("QDRANT_HOST")
QDRANT_PORT = int(os.getenv("QDRANT_PORT"))

QDRANT_COLLECTIONS = {
    "sql_examples": "sql_examples",
    "knowledge":    "douane_knowledge",
    "schema":       "db_schema",
}

EMBED_MODEL = os.getenv("EMBED_MODEL")
EMBED_DIM   = int(os.getenv("EMBED_DIM"))

# =============================================================================
# PIPELINE
# =============================================================================

MAX_ROWS_RESULT = int(os.getenv("MAX_ROWS_RESULT"))
RAG_TOP_K       = int(os.getenv("RAG_TOP_K"))
