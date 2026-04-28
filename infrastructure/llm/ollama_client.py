"""
infrastructure/llm/ollama_client.py — Client HTTP pour Ollama.
Responsabilité unique : envoyer des messages au LLM et retourner la réponse.

CORRECTION v2 :
  - embed() utilise maintenant EMBED_MODEL (nomic-embed-text) et non OLLAMA_MODEL
  - Évite la confusion entre le modèle de génération et le modèle d'embedding
"""

import requests
from config.settings import OLLAMA_URL, OLLAMA_MODEL, EMBED_MODEL, LLM_OPTIONS, LLM_TIMEOUT_S


class OllamaClient:
    """
    Client Ollama minimaliste.
    Utilise l'API /api/chat (mode non-streaming) pour la génération,
    et /api/embeddings avec EMBED_MODEL pour les vecteurs RAG.
    """

    def __init__(
        self,
        url: str    = OLLAMA_URL,
        model: str  = OLLAMA_MODEL,
        timeout: int = LLM_TIMEOUT_S,
    ):
        #self.url     = url
        self.model   = model
        self.timeout = timeout
        self.options = dict(LLM_OPTIONS)
        # URL de base Ollama (sans /api/chat)
        self._base_url = url.replace("/api/chat", "").rstrip("/")

    # ──────────────────────────────────────────────────────────────────────────
    # Génération SQL
    # ──────────────────────────────────────────────────────────────────────────

    def chat(self, system_prompt: str, user_message: str) -> str:
        """
        Envoie un échange system + user au LLM et retourne la réponse texte.
        Lève une RuntimeError si Ollama est injoignable ou retourne une erreur.
        """
        payload = {
            "model":    self.model,
            "stream":   False,
            "options":  self.options,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
        }

        try:
            resp = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Impossible de joindre Ollama sur {self._base_url}. "
                "Vérifiez que le service est lancé : ollama serve"
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Ollama n'a pas répondu dans les {self.timeout}s impartis. "
                "Essayez avec un modèle plus léger ou augmentez LLM_TIMEOUT_S."
            )
        except requests.exceptions.HTTPError as exc:
            raise RuntimeError(f"Erreur HTTP Ollama : {exc}")

        data = resp.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError):
            return data.get("response", "")

    # ──────────────────────────────────────────────────────────────────────────
    # Embedding RAG  ← CORRECTION PRINCIPALE
    # ──────────────────────────────────────────────────────────────────────────

    def embed(self, text: str) -> list[float]:
        """
        Génère un embedding via Ollama.
        Utilise EMBED_MODEL (nomic-embed-text, dim=768) et NON le modèle LLM.

        BOGUE CORRIGÉ : l'ancienne version utilisait self.model (qwen2.5-coder)
        pour l'embedding, ce qui produisait des vecteurs incohérents avec
        ceux indexés dans Qdrant si EMBED_MODEL diffère de OLLAMA_MODEL.
        """
        payload = {
            "model":  EMBED_MODEL,   # ← nomic-embed-text, pas qwen2.5-coder
            "prompt": text,
        }
        try:
            resp = requests.post(
                f"{self._base_url}/api/embeddings",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("embedding", [])
        except Exception as exc:
            raise RuntimeError(f"Erreur embedding Ollama : {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # Health check
    # ──────────────────────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        """Vérifie que le service Ollama répond."""
        try:
            requests.get(self._base_url, timeout=3)
            return True
        except Exception:
            return False
