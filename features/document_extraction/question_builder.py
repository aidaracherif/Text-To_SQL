"""
features/document_extraction/question_builder.py

À partir du texte brut extrait d'un PDF (demande d'extraction douanière),
utilise le LLM pour :
  1. Identifier les champs structurés (NIF, opérateur, période, type de marchandise…)
  2. Reformuler le tout en UNE question naturelle exploitable par /api/v1/query
"""

import json
import logging
import re
from typing import Dict, List, Tuple

from infrastructure.llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


# =============================================================================
# Limite de taille du texte envoyé au LLM (évite de saturer le contexte)
# =============================================================================

_MAX_TEXT_FOR_LLM_CHARS = 8000


# =============================================================================
# Prompt système pour l'extraction structurée
# =============================================================================

_EXTRACTION_PROMPT = """Tu es un assistant spécialisé dans l'analyse de documents douaniers \
de la Direction Générale des Douanes du Sénégal (DGD).

Tu reçois le texte d'une DEMANDE D'EXTRACTION DE DONNÉES (généralement un courrier officiel).
Ta mission : extraire les informations clés et formuler UNE question claire qui pourra être \
posée à un système d'analyse de données SQL.

CHAMPS À RECHERCHER (s'ils sont présents) :
  - NIF                : Numéro d'Identification Fiscale (séquence numérique)
  - operateur          : Nom de la société/opérateur économique
  - periode_debut      : Date de début (format YYYY-MM-DD si possible)
  - periode_fin        : Date de fin (format YYYY-MM-DD si possible)
  - type_operation     : import, export, transit, mise à la consommation…
  - bureau_douane      : Bureau de douane concerné
  - marchandise        : Type ou code de marchandise (SH, NDP…)
  - pays_origine       : Pays d'origine ou de provenance
  - regime_douanier    : Régime douanier
  - numero_declaration : Numéro de déclaration spécifique
  - autres_criteres    : Autres critères mentionnés

CONSIGNES IMPORTANTES :
- N'invente AUCUNE donnée. Si un champ n'est pas dans le texte, ne le mentionne pas.
- Pour la confidence : "haute" si explicite, "moyenne" si déductible, "faible" si incertain.
- La question reformulée doit être PRÉCISE et inclure tous les critères trouvés.
- La question doit commencer par un verbe d'action (Liste, Affiche, Donne, Quelles sont…).

FORMAT DE RÉPONSE OBLIGATOIRE — UNIQUEMENT du JSON valide, rien d'autre :

{
  "extracted_fields": [
    {"name": "NIF", "value": "1234567", "confidence": "haute"},
    {"name": "operateur", "value": "SOCOCIM", "confidence": "haute"}
  ],
  "suggested_question": "Liste les déclarations de l'opérateur SOCOCIM (NIF 1234567) entre le 01/01/2024 et le 30/06/2024"
}

Si le document N'EST PAS une demande d'extraction douanière (ex: facture, autre courrier), \
retourne :
{
  "extracted_fields": [],
  "suggested_question": "HORS_PERIMETRE"
}
"""


class QuestionBuilder:
    """
    Construit une question SQL-friendly à partir du texte d'un PDF.
    """

    def __init__(self, llm_client: OllamaClient = None):
        self.llm = llm_client or OllamaClient()

    def build(
        self,
        pdf_text: str,
        tables: List[List[List[str]]] = None,
    ) -> Dict:
        """
        Args:
            pdf_text : texte concaténé du PDF
            tables   : tables extraites (optionnel, ajouté au contexte)
        
        Returns:
            {
                "suggested_question": "Liste les déclarations...",
                "extracted_fields":   [{"name", "value", "confidence"}, ...],
            }
        """
        if not pdf_text or not pdf_text.strip():
            return {
                "suggested_question": "",
                "extracted_fields": [],
            }

        # Préparer le texte (tronqué + tables formatées)
        text_for_llm = self._prepare_text(pdf_text, tables)

        # Appel LLM
        try:
            llm_response = self.llm.chat(
                system_prompt=_EXTRACTION_PROMPT,
                user_message=f"Voici le contenu du document à analyser :\n\n{text_for_llm}",
            )
        except Exception as exc:
            logger.error(f"Appel LLM échoué : {exc}")
            return self._fallback(pdf_text)

        # Parser la réponse JSON
        parsed = self._parse_llm_response(llm_response)

        if parsed is None:
            logger.warning("Réponse LLM non parsable, fallback sur regex")
            return self._fallback(pdf_text)

        return parsed

    # ──────────────────────────────────────────────────────────────────────────
    # Préparation du texte pour le LLM
    # ──────────────────────────────────────────────────────────────────────────

    def _prepare_text(
        self,
        pdf_text: str,
        tables: List[List[List[str]]] = None,
    ) -> str:
        """Tronque + ajoute les tables formatées si présentes."""
        text = pdf_text.strip()

        # Ajouter les tables formatées (max 3 tables pour limiter la taille)
        if tables:
            tables_str_parts = []
            for i, tbl in enumerate(tables[:3], start=1):
                rows_str = []
                for row in tbl[:20]:  # max 20 lignes par table
                    cells = [str(c).strip() if c else "" for c in row]
                    rows_str.append(" | ".join(cells))
                tables_str_parts.append(
                    f"\n[TABLE {i}]\n" + "\n".join(rows_str)
                )
            text += "\n" + "".join(tables_str_parts)

        # Troncature finale
        if len(text) > _MAX_TEXT_FOR_LLM_CHARS:
            text = text[:_MAX_TEXT_FOR_LLM_CHARS] + "\n[... document tronqué ...]"

        return text

    # ──────────────────────────────────────────────────────────────────────────
    # Parsing de la réponse LLM
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_llm_response(self, response: str) -> Dict | None:
        """Extrait le JSON de la réponse du LLM (gère les bordels markdown)."""
        if not response:
            return None

        # Tentative directe
        try:
            return self._validate_parsed(json.loads(response.strip()))
        except json.JSONDecodeError:
            pass

        # Extraire entre ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
        if match:
            try:
                return self._validate_parsed(json.loads(match.group(1)))
            except json.JSONDecodeError:
                pass

        # Extraire le premier bloc { ... }
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if match:
            try:
                return self._validate_parsed(json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        return None

    def _validate_parsed(self, data: dict) -> Dict:
        """Valide la structure attendue."""
        suggested = str(data.get("suggested_question", "")).strip()
        fields_raw = data.get("extracted_fields", []) or []

        # Filtrer les champs valides
        fields = []
        for f in fields_raw:
            if isinstance(f, dict) and f.get("name") and f.get("value"):
                fields.append({
                    "name":       str(f["name"]),
                    "value":      str(f["value"]),
                    "confidence": str(f.get("confidence", "moyenne")),
                })

        return {
            "suggested_question": suggested,
            "extracted_fields":   fields,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Fallback regex (si LLM indisponible)
    # ──────────────────────────────────────────────────────────────────────────

    def _fallback(self, pdf_text: str) -> Dict:
        """
        Extraction minimale par regex si le LLM est down.
        Couvre les cas les plus fréquents : NIF, dates, opérateur en majuscules.
        """
        fields = []

        # NIF (7 à 12 chiffres précédés de "NIF")
        nif_match = re.search(
            r"\bNIF\s*[:\-]?\s*(\d{7,12})\b", pdf_text, re.IGNORECASE
        )
        if nif_match:
            fields.append({
                "name": "NIF",
                "value": nif_match.group(1),
                "confidence": "haute",
            })

        # Dates au format JJ/MM/AAAA
        date_matches = re.findall(
            r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b", pdf_text
        )
        if len(date_matches) >= 2:
            fields.append({
                "name": "periode_debut", "value": date_matches[0],
                "confidence": "moyenne",
            })
            fields.append({
                "name": "periode_fin", "value": date_matches[1],
                "confidence": "moyenne",
            })
        elif date_matches:
            fields.append({
                "name": "date", "value": date_matches[0],
                "confidence": "moyenne",
            })

        # Construction d'une question minimale
        question_parts = ["Liste les déclarations"]
        if any(f["name"] == "NIF" for f in fields):
            nif = next(f["value"] for f in fields if f["name"] == "NIF")
            question_parts.append(f"de l'opérateur ayant le NIF {nif}")
        if any(f["name"] in ("periode_debut", "date") for f in fields):
            dates = [f["value"] for f in fields if "periode" in f["name"] or f["name"] == "date"]
            if len(dates) >= 2:
                question_parts.append(f"entre le {dates[0]} et le {dates[1]}")
            elif dates:
                question_parts.append(f"du {dates[0]}")

        suggested = " ".join(question_parts)
        if len(question_parts) == 1:
            # Aucun champ trouvé → on ne peut rien proposer
            suggested = ""

        return {
            "suggested_question": suggested,
            "extracted_fields":   fields,
        }
