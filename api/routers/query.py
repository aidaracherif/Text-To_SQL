"""
api/routers/query.py — Endpoint principal de génération SQL.

Remplace entièrement pipeline_runner.py (qui était couplé à Streamlit).
La logique métier (_friendly_error, _hors_schema_message, _build_narrative)
est préservée ici, découplée de toute UI.
"""

import logging
import unicodedata
from typing import Union

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import QueryRequest, QuerySuccessResponse, QueryErrorResponse
from api.dependencies import get_service
from features.text_to_sql.service import TextToSQLService
from api.routers.history import record_query

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# ENDPOINT PRINCIPAL
# =============================================================================

@router.post(
    "/query",
    response_model=Union[QuerySuccessResponse, QueryErrorResponse],
    summary="Générer et exécuter une requête SQL",
    description=(
        "Prend une question en langage naturel, génère le SQL via le LLM, "
        "l'exécute sur PostgreSQL et retourne les résultats."
    ),
)
async def run_query(
    body: QueryRequest,
    service: TextToSQLService = Depends(get_service),
):
    """
    Pipeline complet : Question → SQL → Exécution → Résultat.

    Retourne QuerySuccessResponse si tout s'est bien passé,
    QueryErrorResponse sinon (pas de HTTP 500, l'erreur est dans le body).
    """
    logger.info(f"[QUERY] Question reçue : {body.question[:80]}...")

    result = service.ask(body.question)
    record_query(
    question=body.question,
    sql=result.sql or "",
    row_count=result.row_count,
    duration_ms=result.duration_ms,  # ← aussi absent du QuerySuccessResponse !
    success=not bool(result.error),
)


    # ── Erreur technique (Ollama down, PostgreSQL KO, etc.) ───────────────────
    if result.error:
        record_query(
            question=body.question,
            sql=result.sql or "",
            row_count=0,
            duration_ms=getattr(result, "duration_ms", 0.0),
            success=False,
        )
        return QueryErrorResponse(
            ok=False,
            sql=result.sql or "",
            error=_friendly_error(result.error),
        )

    # ── Question hors périmètre douanier ──────────────────────────────────────
    if result.warning:
        return QueryErrorResponse(
            ok=False,
            sql="",
            error=_hors_schema_message(body.question),
        )

    # ── Succès : nettoyer les NaN avant sérialisation JSON ───────────────────
    clean_rows = [
        [None if (isinstance(v, float) and v != v) else v for v in row]
        for row in result.rows
    ]

    record_query(
        question=body.question,
        sql=result.sql or "",
        row_count=result.row_count,
        duration_ms=getattr(result, "duration_ms", 0.0),
        success=True,
    )
    return QuerySuccessResponse(
        ok=True,
        sql=result.sql or "",
        columns=result.columns,
        rows=clean_rows,
        narrative=_build_narrative(body.question, result.row_count),
        row_count=result.row_count,
        duration_ms=getattr(result, "duration_ms", 0.0),
    )


# =============================================================================
# UTILITAIRES (déplacés de pipeline_runner.py → ici)
# =============================================================================

def _build_narrative(question: str, nb_rows: int) -> str:
    """Génère une courte phrase descriptive adaptée à la question posée."""
    if not nb_rows:
        return "Aucun résultat retourné pour ces critères."

    q = question.lower()
    if "bureau" in q:
        return f"Répartition par bureau de douane — {nb_rows} bureau(x)."
    if any(w in q for w in ["opérateur", "importateur", "top"]):
        return f"Classement des opérateurs — {nb_rows} résultat(s)."
    if any(w in q for w in ["droit", "taxe", "recette", "tva"]):
        return f"Analyse des droits et taxes — {nb_rows} ligne(s)."
    if any(w in q for w in ["pays", "origine"]):
        return f"Répartition par pays — {nb_rows} pays."
    if "déclaration" in q:
        return f"Extraction des déclarations — {nb_rows} enregistrement(s)."

    return (
        f"Requête exécutée — {nb_rows} ligne{'s' if nb_rows > 1 else ''} "
        f"retournée{'s' if nb_rows > 1 else ''}."
    )


def _friendly_error(raw: str) -> str:
    """Traduit les erreurs techniques en messages compréhensibles."""
    msg = raw.lower()
    if "ollama" in msg or ("connection" in msg and "11434" in msg):
        return "Ollama inaccessible. Lancez : ollama serve"
    if "timeout" in msg:
        return "Le modèle n'a pas répondu à temps. Réessayez."
    if "password" in msg or "role" in msg:
        return "Authentification PostgreSQL échouée — vérifiez votre .env"
    if "refused" in msg and "5432" in msg:
        return "PostgreSQL inaccessible — vérifiez que le serveur est lancé."
    if "select" in msg and "autorisées" in msg:
        return "Le modèle n'a pas produit de SELECT valide. Reformulez votre question."
    if "hors_schema" in msg or "hors périmètre" in msg:
        return "Cette question est hors du périmètre du schéma douanier."
    return raw[:200]


def _normalize(text: str) -> str:
    """Supprime les accents et met en minuscules."""
    return (
        unicodedata.normalize("NFD", text)
        .encode("ascii", "ignore")
        .decode("utf-8")
        .lower()
    )


_HORS_SCHEMA_MESSAGES = {
    # Salutations
    "bonjour":                  "Bonjour. Je suis le système d'analyse des données douanières de la DGD. Je suis uniquement habilité à répondre aux questions relatives aux déclarations, opérateurs, taxes et marchandises.",
    "bonsoir":                  "Bonsoir. Je suis le système d'analyse des données douanières de la DGD. Je suis uniquement habilité à répondre aux questions relatives aux déclarations, opérateurs, taxes et marchandises.",
    "bonne nuit":               "Bonne nuit. Je suis le système d'analyse des données douanières de la DGD. Je suis uniquement habilité à répondre aux questions relatives aux déclarations, opérateurs, taxes et marchandises.",
    "salut":                    "Bonjour. Je suis le système d'analyse des données douanières de la DGD. Je suis uniquement habilité à répondre aux questions relatives aux déclarations, opérateurs, taxes et marchandises.",

    # Identité du système
    "qui es-tu":                "Je suis le système d'aide à l'analyse des données de la Direction Générale des Douanes du Sénégal. Je ne suis pas habilité à répondre à des questions d'ordre général.",
    "qui etes-vous":            "Je suis le système d'aide à l'analyse des données de la Direction Générale des Douanes du Sénégal. Je ne suis pas habilité à répondre à des questions d'ordre général.",
    "tu es quoi":               "Je suis le système d'aide à l'analyse des données de la Direction Générale des Douanes du Sénégal. Je ne suis pas habilité à répondre à des questions d'ordre général.",
    "comment vas":              "Je ne suis pas habilité à répondre à cette question. Mon rôle est exclusivement l'analyse des données douanières.",
    "ca va":                    "Je ne suis pas habilité à répondre à cette question. Mon rôle est exclusivement l'analyse des données douanières.",

    # Météo
    "meteo":                    "Je ne suis pas habilité à fournir des informations météorologiques. Veuillez consulter un service météorologique approprié.",
    "temperature":              "Je ne suis pas habilité à fournir des informations météorologiques. Veuillez consulter un service météorologique approprié.",
    "climat":                   "Je ne suis pas habilité à fournir des informations climatiques. Veuillez consulter un service météorologique approprié.",

    # Politique et actualité
    "politique":                "Je ne suis pas habilité à répondre aux questions d'ordre politique. Mon périmètre est strictement limité aux données douanières.",
    "actualite":                "Je ne suis pas habilité à traiter des questions d'actualité. Je suis dédié exclusivement à l'analyse des données de la DGD.",
    "tu connais quoi":          "Je ne suis pas habilité à traiter des questions d'actualité. Je suis dédié exclusivement à l'analyse des données de la DGD.",
    "president de la republique": "Je ne suis pas habilité à répondre à cette question. Mon périmètre est strictement limité aux données douanières du Sénégal.",
    "premier ministre":         "Je ne suis pas habilité à répondre à cette question. Mon périmètre est strictement limité aux données douanières du Sénégal.",
    "gouvernement":             "Je ne suis pas habilité à répondre aux questions relatives au gouvernement. Je traite exclusivement les données douanières.",
    "election":                 "Je ne suis pas habilité à répondre aux questions politiques ou électorales. Mon périmètre est strictement limité aux données douanières.",

    # Personnel et RH
    "salaire":                  "Je ne suis pas habilité à répondre aux questions relatives aux ressources humaines ou aux rémunérations.",
    "remuneration":             "Je ne suis pas habilité à répondre aux questions relatives aux ressources humaines ou aux rémunérations.",
    "employe":                  "Je ne suis pas habilité à répondre aux questions relatives au personnel de l'administration.",
    "agent":                    "Je ne suis pas habilité à répondre aux questions relatives au personnel de l'administration.",
    "directeur de la douane":   "Je ne suis pas habilité à répondre aux questions relatives au personnel de l'administration douanière.",
    "qui est le directeur":     "Je ne suis pas habilité à répondre aux questions relatives au personnel de l'administration.",

    # Sécurité et authentification
    "mot de passe":             "Je ne suis pas habilité à traiter des informations d'authentification ou de sécurité système.",
    "identifiant":              "Je ne suis pas habilité à traiter des informations d'authentification ou de sécurité système.",
    "connexion":                "Je ne suis pas habilité à traiter des informations d'authentification ou de sécurité système.",
}

_VERBES_INTERDITS = [
    "supprime", "supprimer", "suppression",
    "efface", "effacer",
    "modifie", "modifier", "modification",
    "insere", "inserer", "insertion",
    "insert", "update", "delete", "drop", "truncate", "alter",
    "reinitialise", "reinitialiser", "vide", "vider",
]

_MESSAGE_GENERIQUE = (
    "Je ne suis pas habilité à répondre à cette question. "
    "Mon périmètre est strictement limité à l'analyse des données douanières "
    "de la Direction Générale des Douanes du Sénégal (déclarations, opérateurs, "
    "bureaux, taxes, marchandises). Veuillez reformuler votre demande "
    "en rapport avec ces données."
)

_MESSAGE_LECTURE_SEULE = (
    "Je ne suis pas habilité à effectuer des opérations de modification "
    "ou de suppression de données. Le système est strictement configuré en lecture seule."
)


def _hors_schema_message(question: str) -> str:
    """Retourne un message professionnel adapté à la question hors périmètre."""
    q = _normalize(question)
    if any(v in q for v in _VERBES_INTERDITS):
        return _MESSAGE_LECTURE_SEULE
    for mot_cle, message in _HORS_SCHEMA_MESSAGES.items():
        if _normalize(mot_cle) in q:
            return message
    return _MESSAGE_GENERIQUE
