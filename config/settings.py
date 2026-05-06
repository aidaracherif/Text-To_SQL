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


# =============================================================================
# 🆕 TRANSCRIPTION VOCALE (faster-whisper)
# =============================================================================

WHISPER_CONFIG = {
    "model_size":     os.getenv("WHISPER_MODEL", "small"),
    "language":       os.getenv("WHISPER_LANGUAGE", "fr"),
    "device":         os.getenv("WHISPER_DEVICE", "cpu"),
    "compute_type":   os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
    "download_root":  os.getenv("WHISPER_DOWNLOAD_DIR", "./models/whisper"),
}

MAX_AUDIO_SIZE_MB = int(os.getenv("MAX_AUDIO_SIZE_MB", "25"))

# Formats audio acceptés (MIME types)
ALLOWED_AUDIO_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",      # mp3
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/flac",
}

# =============================================================================
# 🆕 EXTRACTION PDF
# =============================================================================

PDF_CONFIG = {
    "max_size_mb":  int(os.getenv("MAX_PDF_SIZE_MB", "20")),
    "ocr_enabled":  os.getenv("PDF_OCR_ENABLED", "true").lower() == "true",
    "ocr_language": os.getenv("PDF_OCR_LANGUAGE", "fra"),
    "max_pages":    int(os.getenv("PDF_MAX_PAGES", "50")),
}

ALLOWED_PDF_TYPES = {"application/pdf"}
