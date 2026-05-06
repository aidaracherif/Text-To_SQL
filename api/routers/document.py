"""
api/routers/document.py — Endpoint d'extraction PDF.

POST /api/v1/document/extract
  - Reçoit un PDF (multipart/form-data) — typiquement une demande d'extraction
  - Lit le texte (pdfplumber → PyMuPDF → OCR Tesseract en fallback)
  - Demande au LLM d'extraire les champs structurés + reformuler en question
  - Retourne { extracted_text, extracted_fields, suggested_question }

Workflow côté frontend :
  1. User upload PDF → POST /document/extract
  2. Frontend affiche suggested_question + extracted_fields pour validation
  3. User confirme / modifie la question
  4. Frontend appelle POST /query avec la question finale
"""

import logging
import time
from typing import Union

from fastapi import APIRouter, Depends, File, UploadFile

from api.schemas import (
    DocumentExtractionResponse,
    DocumentErrorResponse,
    ExtractedField,
)
from api.dependencies import get_pdf_reader, get_question_builder
from features.document_extraction.pdf_reader import PDFReader
from features.document_extraction.question_builder import QuestionBuilder
from config.settings import PDF_CONFIG, ALLOWED_PDF_TYPES

logger = logging.getLogger(__name__)

router = APIRouter()


# Limite d'affichage du texte extrait dans la réponse (UX)
_MAX_TEXT_PREVIEW_CHARS = 5000


# =============================================================================
# ENDPOINT — Extraction PDF
# =============================================================================

@router.post(
    "/document/extract",
    response_model=Union[DocumentExtractionResponse, DocumentErrorResponse],
    summary="Extraire les informations d'un PDF de demande d'extraction",
    description=(
        "Lit un PDF (typiquement une demande d'extraction de données douanières), "
        "extrait le texte (avec OCR si scanné) et les tables, puis utilise le LLM "
        "pour reformuler en une question naturelle. **L'utilisateur doit valider "
        "la question avant de l'envoyer à /api/v1/query.**"
    ),
)
async def extract_document(
    pdf: UploadFile = File(
        ...,
        description="Fichier PDF (max 20 Mo, 50 pages)",
    ),
    pdf_reader: PDFReader = Depends(get_pdf_reader),
    question_builder: QuestionBuilder = Depends(get_question_builder),
):
    """Extrait + reformule un PDF en question SQL-ready."""
    t0 = time.time()
    filename = pdf.filename or "document.pdf"

    # ── 1. Validation MIME type ──────────────────────────────────────────────
    content_type = (pdf.content_type or "").lower()
    if content_type and content_type not in ALLOWED_PDF_TYPES:
        return DocumentErrorResponse(
            ok=False,
            filename=filename,
            error=f"Type non supporté : '{content_type}'. Seul application/pdf est accepté.",
        )

    # ── 2. Lecture + validation taille ───────────────────────────────────────
    try:
        pdf_bytes = await pdf.read()
    except Exception as exc:
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=f"Lecture du fichier impossible : {exc}",
        )

    size_mb = len(pdf_bytes) / (1024 * 1024)
    if size_mb > PDF_CONFIG["max_size_mb"]:
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=f"PDF trop volumineux ({size_mb:.1f} Mo). Max : {PDF_CONFIG['max_size_mb']} Mo.",
        )

    if len(pdf_bytes) < 100:
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error="Fichier PDF vide ou corrompu.",
        )

    # Vérifier la signature PDF (%PDF-)
    if not pdf_bytes.startswith(b"%PDF-"):
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error="Le fichier ne semble pas être un PDF valide (signature manquante).",
        )

    logger.info(f"[DOC] PDF reçu : {filename} ({size_mb:.2f} Mo)")

    # ── 3. Extraction du contenu ─────────────────────────────────────────────
    try:
        extraction = pdf_reader.read(pdf_bytes)
    except Exception as exc:
        logger.error(f"[DOC] Échec extraction PDF : {exc}")
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=f"Échec de l'extraction du PDF : {exc}",
        )

    raw_text = extraction["text"]

    if not raw_text.strip():
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=(
                "Aucun texte détecté dans le PDF. "
                "S'il s'agit d'un scan, vérifiez que l'OCR (Tesseract) est installé."
            ),
        )

    logger.info(
        f"[DOC] Extraction OK : {extraction['page_count']} pages, "
        f"{len(raw_text)} chars, OCR={extraction['used_ocr']}, "
        f"tables={extraction['has_tables']}"
    )

    # ── 4. Reformulation LLM en question ─────────────────────────────────────
    try:
        builder_result = question_builder.build(
            pdf_text=raw_text,
            tables=extraction.get("tables"),
        )
    except Exception as exc:
        logger.error(f"[DOC] Échec reformulation : {exc}")
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=f"Échec de la reformulation : {exc}",
        )

    suggested = builder_result["suggested_question"]

    # Détection hors-périmètre signalée par le LLM
    if suggested == "HORS_PERIMETRE":
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=(
                "Ce document ne semble pas être une demande d'extraction douanière. "
                "Veuillez fournir un courrier ou formulaire de demande de données."
            ),
        )

    if not suggested:
        return DocumentErrorResponse(
            ok=False, filename=filename,
            error=(
                "Impossible de formuler une question à partir de ce document. "
                "Le contenu est peut-être trop ambigu ou hors périmètre."
            ),
        )

    # ── 5. Conversion des champs en modèles Pydantic ─────────────────────────
    extracted_fields = [
        ExtractedField(**f) for f in builder_result.get("extracted_fields", [])
    ]

    # ── 6. Tronquer le texte pour la réponse (UX) ────────────────────────────
    text_preview = raw_text
    if len(text_preview) > _MAX_TEXT_PREVIEW_CHARS:
        text_preview = text_preview[:_MAX_TEXT_PREVIEW_CHARS] + "\n\n[... texte tronqué pour l'affichage ...]"

    duration_ms = (time.time() - t0) * 1000

    return DocumentExtractionResponse(
        ok=True,
        filename=filename,
        page_count=extraction["page_count"],
        extracted_text=text_preview,
        suggested_question=suggested,
        extracted_fields=extracted_fields,
        has_tables=extraction["has_tables"],
        used_ocr=extraction["used_ocr"],
        duration_ms=duration_ms,
    )
