"""
core/prompt_builder.py — Construction des prompts système pour le LLM.
Logique pure : prend le schéma + contexte RAG → retourne une string.

v2 — améliorations :
  - Scores de similarité exposés au LLM avec instruction adaptée au niveau de confiance
  - Rappel de contrainte en tête du prompt RAG (évite l'oubli des règles sur contexte long)
  - Ordre optimisé : général → spécifique → question (recency bias des LLMs)
"""

from config.settings import MAX_ROWS_RESULT


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT SYSTÈME PRINCIPAL (sans RAG)
# ─────────────────────────────────────────────────────────────────────────────

def build_system_prompt(schema: str, stats: str = "") -> str:
    stats_section = f"\n{stats}\n" if stats else ""
    return f"""Tu es un expert SQL PostgreSQL travaillant pour la Direction Générale des Douanes du Sénégal (DGD).

Ton rôle est de traduire des questions en français en requêtes SQL PostgreSQL valides et optimisées.

## Schéma de la base de données

{schema}
{stats_section}
## Règles strictes

1. Réponds UNIQUEMENT avec un bloc SQL entre les balises ```sql et ```.
   Aucune explication avant ou après.

2. Utilise UNIQUEMENT les tables et colonnes présentes dans le schéma.
   N'invente jamais de noms de tables ou de colonnes.

3. Ajoute toujours LIMIT {MAX_ROWS_RESULT} sauf pour les agrégations
   (COUNT, SUM, AVG, etc.) où un LIMIT n'a pas de sens.

4. Requêtes en lecture seule uniquement (SELECT).
   N'écris jamais INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER.

5. Pour les jointures, utilise les clés étrangères du schéma.
   Préfère les JOIN explicites aux sous-requêtes quand possible.

6. Pour les montants : ROUND(montant, 2) pour l'affichage.

7. Pour les dates : format PostgreSQL YYYY-MM-DD.
   Pour filtrer par année : EXTRACT(YEAR FROM date_enregistrement) = 2024

8. Pour les recherches textuelles : ILIKE (insensible à la casse).

9. Donne des alias lisibles aux colonnes calculées.
   Ex : SUM(valeur_totale) AS total_valeur

10. Si la question ne concerne pas les données douanières ou est impossible
    avec ce schéma, retourne EXACTEMENT ce bloc sans rien d'autre :
```sql
    -- QUESTION_HORS_SCHEMA
```

    Exemples de questions hors périmètre :
    - Questions personnelles ou générales ("bonjour", "qui es-tu", "météo")
    - Questions politiques ou d'actualité
    - Questions sur d'autres administrations
    - Demandes de modification de données
    - Tout ce qui ne concerne pas les déclarations, opérateurs,
      bureaux, taxes ou marchandises douanières du Sénégal

      
11. Pour filtrer par régime, utilise TOUJOURS d.code_regime = 'IM' directement.
    Ne joins jamais la table regimes uniquement pour filtrer.
    Valeurs : 'IM'=importation, 'EX'=exportation, 'TF'=transit,
    'AT'=admission temporaire, 'ZF'=zone franche.

12. Valeurs exactes statut déclarations :
    'ENREGISTREE', 'EN_COURS', 'VALIDEE', 'LIQUIDEE', 'ABANDONNEE', 'CONTENTIEUX'.

13. Valeurs exactes statut_paiement dans droits_taxes :
    'PAYE', 'EN_ATTENTE', 'EXONERE', 'CONTENTIEUX'.

14. Valeurs exactes type_droit dans droits_taxes :
    'DD', 'TVA', 'PCS', 'PE', 'RS'.

15. Pour les pourcentages, utilise TOUJOURS une window function :
    ROUND(SUM(d.valeur_totale) * 100.0 / SUM(SUM(d.valeur_totale)) OVER (), 2)

## Exemples

Question : Combien de déclarations ont été enregistrées en 2024 ?
```sql
SELECT COUNT(*) AS nombre_declarations
FROM declarations
WHERE EXTRACT(YEAR FROM date_enregistrement) = 2024;
```

Question : Les 5 opérateurs avec le plus grand total de valeur déclarée
```sql
SELECT o.raison_sociale,
       ROUND(SUM(d.valeur_totale), 2) AS total_valeur
FROM declarations d
JOIN operateurs o ON d.id_operateur = o.id_operateur
GROUP BY o.raison_sociale
ORDER BY total_valeur DESC
LIMIT 5;
```

Question : Total des droits de douane perçus par année
```sql
SELECT EXTRACT(YEAR FROM d.date_enregistrement) AS annee,
       ROUND(SUM(dt.montant), 2)                AS total_droits
FROM droits_taxes dt
JOIN declarations d ON dt.id_declaration = d.id_declaration
WHERE dt.type_droit      = 'DD'
  AND dt.statut_paiement = 'PAYE'
GROUP BY annee
ORDER BY annee;
```
"""


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNES
# ─────────────────────────────────────────────────────────────────────────────

def _score_label(score: float) -> str:
    if score >= 0.88: return "quasi-identique"
    if score >= 0.75: return "très similaire"
    if score >= 0.60: return "partiellement similaire"
    return "indicatif"


def _format_sql_examples(items: list[dict]) -> str | None:
    if not items:
        return None
    lines = []
    for i, ex in enumerate(items, 1):
        score = ex.get("score", 0)
        lines.append(
            f"Exemple {i} — similarité : {_score_label(score)} ({score:.2f})\n"
            f"Question : {ex.get('question', '')}\n"
            f"```sql\n{ex.get('sql', '').strip()}\n```"
        )
    return "\n\n".join(lines)


def _format_knowledge(items: list[dict]) -> str | None:
    if not items:
        return None
    lines = []
    for item in items:
        titre   = item.get("titre", "").strip()
        contenu = item.get("contenu", "").strip()
        lines.append(f"• {titre} : {contenu}" if titre else f"• {contenu}")
    return "\n".join(lines) if lines else None


def _format_schema_chunks(items: list[dict]) -> str | None:
    if not items:
        return None
    lines = []
    for item in items:
        table = item.get("table", "").strip()
        desc  = item.get("description", "").strip()
        lines.append(f"• {table} : {desc}" if desc else f"• {table}")
    return "\n".join(lines) if lines else None


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT ENRICHI PAR LE RAG
# ─────────────────────────────────────────────────────────────────────────────

def build_rag_prompt(question: str, context: dict) -> str:
    """
    Construit le prompt utilisateur enrichi par le contexte RAG.

    Ordre intentionnel (recency bias — le LLM lit mieux ce qui est en fin) :
      1. Rappel de contrainte  → ancre les règles même sur contexte long
      2. Règles métier         → contexte sémantique général
      3. Tables suggérées      → jointures recommandées
      4. Exemples SQL          → avec instruction selon niveau de confiance
      5. Question              → en dernier (position d'attention maximale)
    """
    sections = []

    # 1. Ancre de contrainte
    sections.append(
        "[RAPPEL]\n"
        "Réponds uniquement avec un bloc SQL valide entre ```sql et ```.\n"
        f"Si la question est hors du schéma douanier : -- QUESTION_HORS_SCHEMA\n"
        f"LIMIT {MAX_ROWS_RESULT} obligatoire sauf agrégations."
    )

    # 2. Règles métier
    knowledge_text = _format_knowledge(context.get("knowledge", []))
    if knowledge_text:
        sections.append(
            "[RÈGLES MÉTIER DOUANIÈRES — à respecter dans la requête]\n"
            + knowledge_text
        )

    # 3. Tables recommandées
    schema_text = _format_schema_chunks(context.get("schema_chunks", []))
    if schema_text:
        sections.append(
            "[TABLES SUGGÉRÉES — priorité pour les jointures]\n"
            + schema_text
        )

    # 4. Exemples SQL avec instruction adaptée au score
    examples_text = _format_sql_examples(context.get("sql_examples", []))
    if examples_text:
        best = context["sql_examples"][0].get("score", 0) if context.get("sql_examples") else 0
        if best >= 0.88:
            instr = "L'exemple ci-dessous est quasi-identique. Adapte-le directement."
        elif best >= 0.75:
            instr = "Ces exemples sont très proches. Inspire-toi de leur structure."
        else:
            instr = "Ces exemples illustrent le style SQL attendu. Utilise-les comme référence."
        sections.append(f"[EXEMPLES SQL SIMILAIRES — {instr}]\n" + examples_text)

    # 5. Question
    sections.append(f"[QUESTION]\n{question}")

    return "\n\n".join(sections)
