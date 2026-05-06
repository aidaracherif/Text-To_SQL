"""
main.py — Point d'entrée de l'application FastAPI.

Lancement :
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import query, health, history, voice, document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# LIFESPAN — initialisation / nettoyage au démarrage/arrêt
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise les ressources au démarrage, les libère à l'arrêt."""
    logger.info("🚀 Démarrage du serveur Text-to-SQL DGD Sénégal")
    logger.info("   Endpoints disponibles :")
    logger.info("   • POST /api/v1/query              — Question texte → SQL")
    logger.info("   • POST /api/v1/voice/transcribe   — Audio → question")
    logger.info("   • POST /api/v1/document/extract   — PDF → question")
    logger.info("   • GET  /api/v1/health             — État des services")
    logger.info("   • GET  /api/v1/history            — Historique session")
    logger.info("   • Doc interactive : http://localhost:8000/docs")
    yield
    logger.info("🛑 Arrêt du serveur")



# =============================================================================
# APPLICATION
# =============================================================================

app = FastAPI(
    title="Text-to-SQL DGD Sénégal",
    description=(
        "API REST pour la génération de requêtes SQL à partir de questions "
        "en langage naturel sur les données douanières de la DGD Sénégal.\n\n"
        "**Fonctionnalités :**\n"
        "- 📝 Question textuelle → SQL → Résultats\n"
        "- 🎤 Transcription vocale (faster-whisper) → question\n"
        "- 📄 Extraction PDF (pdfplumber + OCR Tesseract) → question\n"
    ),
    version="2.1.0",
    lifespan=lifespan,
)



# =============================================================================
# CORS — autoriser Angular (localhost:4200 en dev)
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",   # Angular dev
        "http://localhost:3000",
        # En production : ajoutez "https://votre-domaine.sn"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# =============================================================================
# ROUTERS
# =============================================================================

app.include_router(health.router,    prefix="/api/v1", tags=["Health"])
app.include_router(query.router,     prefix="/api/v1", tags=["Query"])
app.include_router(history.router,   prefix="/api/v1", tags=["History"])
app.include_router(voice.router,     prefix="/api/v1", tags=["Voice"])     # 🆕
app.include_router(document.router,  prefix="/api/v1", tags=["Document"])  # 🆕


# =============================================================================
# ROOT
# =============================================================================


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "API Text-to-SQL DGD Sénégal opérationnelle",
        "docs":    "/docs",
        "version": "2.1.0",
        "features": ["text-query", "voice-transcribe", "pdf-extract"],
    }
