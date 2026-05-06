"""
api/routers/voice.py — Endpoint de transcription vocale.

POST /api/v1/voice/transcribe
  - Reçoit un fichier audio (multipart/form-data)
  - Transcrit via faster-whisper
  - Reformule la transcription en question SQL-friendly via LLM
  - Retourne { transcription, suggested_question } pour validation utilisateur

Workflow côté frontend :
  1. User enregistre audio → POST /voice/transcribe
  2. Frontend affiche suggested_question
  3. User confirme / modifie
  4. Frontend appelle POST /query avec la question finale
"""

import logging
from typing import Union

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query

from api.schemas import VoiceTranscriptionResponse, VoiceErrorResponse
from api.dependencies import get_voice_transcriber, get_question_cleaner
from features.voice.transcriber import VoiceTranscriber
from features.voice.question_cleaner import QuestionCleaner
from config.settings import MAX_AUDIO_SIZE_MB, ALLOWED_AUDIO_TYPES

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# ENDPOINT — Transcription audio
# =============================================================================

@router.post(
    "/voice/transcribe",
    response_model=Union[VoiceTranscriptionResponse, VoiceErrorResponse],
    summary="Transcrire un audio en question",
    description=(
        "Transcrit un fichier audio (webm/wav/mp3/ogg/m4a) en texte via "
        "faster-whisper, puis reformule la transcription en question naturelle "
        "exploitable par /api/v1/query. **L'utilisateur doit confirmer la "
        "question avant de l'envoyer à /query.**"
    ),
)
async def transcribe_audio(
    audio: UploadFile = File(
        ...,
        description="Fichier audio (webm/wav/mp3/ogg/m4a/flac), max 25 Mo",
    ),
    use_llm_cleanup: bool = Query(
        True,
        description="Utiliser le LLM pour reformuler (sinon nettoyage regex seul)",
    ),
    language: str = Query(
        "fr",
        description="Code langue ISO (fr, en…) — auto-détection si vide",
    ),
    transcriber: VoiceTranscriber = Depends(get_voice_transcriber),
    cleaner: QuestionCleaner = Depends(get_question_cleaner),
):
    """Transcrit un audio puis reformule en question SQL-ready."""

    # ── 1. Validation MIME type ──────────────────────────────────────────────
    content_type = (audio.content_type or "").lower()
    if content_type and content_type not in ALLOWED_AUDIO_TYPES:
        logger.warning(f"Type audio refusé : {content_type}")
        return VoiceErrorResponse(
            ok=False,
            error=(
                f"Format audio non supporté : '{content_type}'. "
                f"Formats acceptés : {', '.join(sorted(ALLOWED_AUDIO_TYPES))}"
            ),
        )

    # ── 2. Lecture + validation taille ───────────────────────────────────────
    try:
        audio_bytes = await audio.read()
    except Exception as exc:
        return VoiceErrorResponse(ok=False, error=f"Lecture du fichier audio impossible : {exc}")

    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_AUDIO_SIZE_MB:
        return VoiceErrorResponse(
            ok=False,
            error=f"Fichier audio trop volumineux ({size_mb:.1f} Mo). Max : {MAX_AUDIO_SIZE_MB} Mo.",
        )

    if len(audio_bytes) < 100:  # sanity check : moins de 100 octets = vide/corrompu
        return VoiceErrorResponse(
            ok=False,
            error="Fichier audio vide ou corrompu.",
        )

    logger.info(
        f"[VOICE] Audio reçu : {audio.filename} ({size_mb:.2f} Mo, type={content_type})"
    )

    # ── 3. Transcription Whisper ─────────────────────────────────────────────
    try:
        whisper_result = transcriber.transcribe(audio_bytes, language=language or None)
    except Exception as exc:
        logger.error(f"[VOICE] Échec transcription : {exc}")
        return VoiceErrorResponse(
            ok=False,
            error=f"Échec de la transcription : {exc}",
        )

    raw_text = whisper_result["text"]

    if not raw_text.strip():
        return VoiceErrorResponse(
            ok=False,
            error="Aucune parole détectée dans l'audio. Réessayez en parlant plus clairement.",
        )

    logger.info(f"[VOICE] Transcription brute : {raw_text[:120]}")

    # ── 4. Reformulation via LLM (ou regex en fallback) ──────────────────────
    suggested = cleaner.clean(raw_text, use_llm=use_llm_cleanup)

    logger.info(f"[VOICE] Question suggérée : {suggested[:120]}")

    # ── 5. Réponse structurée ────────────────────────────────────────────────
    return VoiceTranscriptionResponse(
        ok=True,
        transcription=raw_text,
        suggested_question=suggested,
        language=whisper_result.get("language", language),
        duration_audio_s=whisper_result.get("duration", 0.0),
        duration_processing_ms=whisper_result.get("processing_ms", 0.0),
        confidence=whisper_result.get("confidence"),
    )
