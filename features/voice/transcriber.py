"""
features/voice/transcriber.py — Service de transcription audio.

Wrapper autour de faster-whisper. Singleton (modèle chargé une seule fois).
Appelé par api/routers/voice.py.
"""

import io
import logging
import time
from typing import Optional, Tuple

from config.settings import WHISPER_CONFIG

logger = logging.getLogger(__name__)


class VoiceTranscriber:
    """
    Transcription audio via faster-whisper (CTranslate2).
    
    Le modèle est chargé une seule fois (lazy loading au premier appel)
    puis conservé en mémoire pour les requêtes suivantes.
    
    Usage :
        transcriber = VoiceTranscriber()
        result = transcriber.transcribe(audio_bytes)
        # result = {
        #     "text": "donne moi le top 10 des importateurs",
        #     "language": "fr",
        #     "duration": 4.2,
        #     "confidence": 0.94,
        # }
    """

    def __init__(
        self,
        model_size: str = None,
        language: str = None,
        device: str = None,
        compute_type: str = None,
        download_root: str = None,
    ):
        self.model_size    = model_size    or WHISPER_CONFIG["model_size"]
        self.language      = language      or WHISPER_CONFIG["language"]
        self.device        = device        or WHISPER_CONFIG["device"]
        self.compute_type  = compute_type  or WHISPER_CONFIG["compute_type"]
        self.download_root = download_root or WHISPER_CONFIG["download_root"]

        # Lazy loading : modèle chargé seulement au premier appel
        self._model = None

    # ──────────────────────────────────────────────────────────────────────────
    # Chargement du modèle (lazy)
    # ──────────────────────────────────────────────────────────────────────────

    def _load_model(self):
        """Charge le modèle Whisper en mémoire (une seule fois)."""
        if self._model is not None:
            return

        try:
            # Import paresseux : évite de payer le coût si voice non utilisé
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper n'est pas installé. "
                "Installez-le : pip install faster-whisper"
            ) from exc

        logger.info(
            f"Chargement modèle Whisper '{self.model_size}' "
            f"(device={self.device}, compute_type={self.compute_type})..."
        )
        t0 = time.time()

        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            download_root=self.download_root,
        )

        logger.info(f"Modèle Whisper chargé en {time.time() - t0:.1f}s")

    # ──────────────────────────────────────────────────────────────────────────
    # API publique
    # ──────────────────────────────────────────────────────────────────────────

    def transcribe(
        self,
        audio_bytes: bytes,
        language: Optional[str] = None,
    ) -> dict:
        """
        Transcrit un fichier audio (bytes) en texte.
        
        Args:
            audio_bytes : contenu binaire du fichier audio (webm, wav, mp3, etc.)
            language    : code langue ISO (fr, en…) ou None pour auto-détection
        
        Returns:
            dict avec : text, language, duration, confidence, processing_ms
        
        Raises:
            RuntimeError si la transcription échoue
        """
        self._load_model()

        lang = language or self.language
        t0 = time.time()

        try:
            # faster-whisper accepte un BytesIO directement
            audio_stream = io.BytesIO(audio_bytes)

            segments_iter, info = self._model.transcribe(
                audio_stream,
                language=lang,
                beam_size=5,
                vad_filter=True,        # Filtre les silences (améliore qualité)
                vad_parameters={"min_silence_duration_ms": 500},
            )

            # IMPORTANT : faster-whisper retourne un générateur paresseux.
            # Il faut le consommer pour obtenir le texte.
            segments = list(segments_iter)

        except Exception as exc:
            logger.error(f"Erreur transcription Whisper : {exc}")
            raise RuntimeError(f"Échec de la transcription audio : {exc}")

        # Concaténation du texte de tous les segments
        full_text = " ".join(seg.text.strip() for seg in segments).strip()

        # Confiance moyenne (avg_logprob est en log, on le convertit grossièrement)
        confidence = None
        if segments:
            import math
            avg_logprob = sum(seg.avg_logprob for seg in segments) / len(segments)
            # exp(logprob) donne la probabilité ; clamp [0, 1]
            confidence = max(0.0, min(1.0, math.exp(avg_logprob)))

        return {
            "text":           full_text,
            "language":       info.language,
            "duration":       info.duration,
            "confidence":     confidence,
            "processing_ms":  (time.time() - t0) * 1000,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Health check
    # ──────────────────────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """
        Vérifie que faster-whisper est installé et le modèle chargeable.
        N'effectue PAS le chargement réel (ce serait trop coûteux).
        """
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def is_loaded(self) -> bool:
        """Le modèle est-il déjà chargé en mémoire ?"""
        return self._model is not None
