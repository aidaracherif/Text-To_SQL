"""
features/voice/question_cleaner.py — Reformule une transcription brute
en question naturelle exploitable par le pipeline Text-to-SQL.

Exemple :
    Entrée  : "euh donne moi euh le top dix des importateurs en 2024 voilà"
    Sortie  : "Quels sont les 10 plus gros importateurs en 2024 ?"
"""

import logging
import re
from infrastructure.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


# =============================================================================
# Mots de remplissage à supprimer (pré-traitement rapide avant LLM)
# =============================================================================

_FILLER_WORDS = [
    r"\beuh\b", r"\bheu\b", r"\bhum\b", r"\bhmm\b",
    r"\bben\b", r"\bbah\b", r"\bvoilà\b", r"\bdonc\b",
    r"\bdu coup\b", r"\ben fait\b", r"\bquoi\b",
    r"\bje veux dire\b", r"\bcomment dire\b",
]

_FILLER_REGEX = re.compile("|".join(_FILLER_WORDS), re.IGNORECASE)


def _quick_clean(text: str) -> str:
    """Nettoyage rapide regex sans appel LLM (premier passage)."""
    cleaned = _FILLER_REGEX.sub("", text)
    # Compresser espaces multiples
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Capitaliser première lettre
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


# =============================================================================
# Reformulation via LLM
# =============================================================================

_REFORMULATION_PROMPT = """Tu es un assistant chargé de reformuler des questions vocales \
en questions claires et concises pour un système d'analyse de données douanières.

RÈGLES :
1. Garde EXACTEMENT le sens et l'intention de la question originale.
2. Supprime les hésitations, répétitions et mots de remplissage.
3. Corrige la grammaire et l'orthographe.
4. Convertis les nombres en chiffres ("dix" → "10", "deux mille vingt-quatre" → "2024").
5. Termine par un point d'interrogation si c'est une question.
6. Ne réponds PAS à la question, reformule-la SEULEMENT.
7. Ne change pas le vocabulaire métier (NIF, bureau, déclaration, opérateur, droits, taxes…).
8. Reste concis : maximum une ou deux phrases.

Réponds UNIQUEMENT avec la question reformulée, sans préambule, sans guillemets, \
sans explications.

EXEMPLES :

Question vocale : "euh donne moi le top dix des importateurs en deux mille vingt-quatre voilà"
Question reformulée : Quels sont les 10 plus gros importateurs en 2024 ?

Question vocale : "je voudrais voir les recettes par bureau de douane sur le premier semestre"
Question reformulée : Quelles sont les recettes par bureau de douane sur le premier semestre ?

Question vocale : "combien de déclarations ont été faites par SOCOCIM cette année hum"
Question reformulée : Combien de déclarations ont été faites par SOCOCIM cette année ?
"""


class QuestionCleaner:
    """
    Nettoie et reformule une transcription vocale en question SQL-friendly.
    """

    def __init__(self, llm_client: OllamaClient = None):
        self.llm = llm_client or OllamaClient()

    def clean(self, raw_transcription: str, use_llm: bool = True) -> str:
        """
        Args:
            raw_transcription : texte brut de Whisper
            use_llm           : True = appel LLM (qualité max), 
                                False = regex seul (rapide mais basique)
        
        Returns:
            Question reformulée prête pour /api/v1/query
        """
        if not raw_transcription or not raw_transcription.strip():
            return ""

        # Étape 1 : nettoyage rapide (toujours)
        quick = _quick_clean(raw_transcription)

        if not use_llm or len(quick) < 5:
            return quick

        # Étape 2 : reformulation LLM
        try:
            reformulated = self.llm.chat(
                system_prompt=_REFORMULATION_PROMPT,
                user_message=f'Question vocale : "{raw_transcription}"\nQuestion reformulée :',
            ).strip()

            # Nettoyage des artefacts éventuels
            reformulated = reformulated.strip('"\'`')
            # Si le LLM a re-préfixé "Question reformulée :"
            reformulated = re.sub(
                r"^(question reformulée|reformulation)\s*:\s*",
                "",
                reformulated,
                flags=re.IGNORECASE,
            ).strip()

            # Sécurité : si le LLM produit une réponse vide ou aberrante,
            # on retombe sur le nettoyage rapide.
            if not reformulated or len(reformulated) < 3:
                logger.warning(
                    "LLM a produit une reformulation vide, fallback sur quick_clean"
                )
                return quick

            return reformulated

        except Exception as exc:
            logger.warning(
                f"Reformulation LLM échouée ({exc}), fallback sur quick_clean"
            )
            return quick
