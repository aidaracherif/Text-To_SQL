"""
core/sql_extractor.py — Extraction et validation du SQL depuis la réponse LLM.
Logique pure, sans dépendances externes.
"""

import re


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_sql(llm_response: str) -> str:
    """
    Extrait le bloc SQL depuis la réponse du LLM.

    Gère les formats :
      - ```sql ... ```
      - ``` ... ```
      - SQL brut sans balises
    """
    # Chercher un bloc ```sql ... ```
    match = re.search(r"```sql\s*(.*?)```", llm_response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Chercher un bloc ``` ... ```
    match = re.search(r"```\s*(.*?)```", llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Pas de balises → nettoyer et retourner tel quel
    return llm_response.strip()


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION SÉCURITÉ
# ─────────────────────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE"
    r"|EXEC|EXECUTE|COPY|VACUUM|ANALYZE)\b",
    re.IGNORECASE,
)


def validate_sql(sql: str) -> None:
    """
    Lève une ValueError si le SQL contient des instructions interdites.
    Autorise uniquement les requêtes SELECT.
    """
    if not sql or not sql.strip():
        raise ValueError("SQL vide reçu du LLM.")

    if _FORBIDDEN.search(sql):
        raise ValueError(
            f"SQL refusé : instruction interdite détectée dans : {sql[:120]}"
        )

    # Doit commencer par SELECT ou WITH (CTE)
    first_token = sql.strip().split()[0].upper()
    if first_token not in ("SELECT", "WITH", "--"):
        raise ValueError(
            f"SQL refusé : la requête doit être un SELECT (reçu : '{first_token}')."
        )


# ─────────────────────────────────────────────────────────────────────────────
# DÉTECTION HORS PÉRIMÈTRE
# ─────────────────────────────────────────────────────────────────────────────

def is_out_of_schema(sql: str) -> bool:
    """
    Retourne True si le LLM a indiqué que la question est hors périmètre.
    Convention : le LLM retourne '-- QUESTION_HORS_SCHEMA' dans ce cas.
    """
    return "QUESTION_HORS_SCHEMA" in sql.upper()

# ─────────────────────────────────────────────────────────────────────────────
# CORRECTION AUTOMATIQUE
# ─────────────────────────────────────────────────────────────────────────────

def fix_sql(sql: str) -> str:
    sql = _fix_alias_conflict(sql)
    sql = _fix_absurd_percentage(sql)
    # _fix_group_by()         — retiré, trop agressif
    # _fix_having_vs_where()  — retiré, risque de mal découper les WHERE complexes
    sql = _fix_metier_values(sql)
    sql = _fix_join_keys(sql)
    sql = _fix_extract_syntax(sql)
    sql = _fix_missing_limit(sql)
    return sql 


def _fix_alias_conflict(sql: str) -> str:
    aliases = re.findall(r'\bFROM\s+(\w+)\s+(\w+)', sql, re.IGNORECASE)
    aliases += re.findall(r'\bJOIN\s+(\w+)\s+(\w+)', sql, re.IGNORECASE)

    for table, alias in aliases:
        if alias.upper() in ('ON', 'WHERE', 'GROUP', 'ORDER', 'LEFT', 'RIGHT', 'INNER'):
            continue
        sql = re.sub(
            rf'\b{re.escape(table)}\.(\w+)',
            rf'{alias}.\1',
            sql,
            flags=re.IGNORECASE,
        )
    return sql


def _fix_absurd_percentage(sql: str) -> str:
    pattern = r'(SUM\((\w+\.\w+)\))\s*/\s*(SUM\(\2\))(?!\s*OVER)'
    replacement = r'\1 / SUM(SUM(\2)) OVER ()'
    return re.sub(pattern, replacement, sql, flags=re.IGNORECASE)

def _fix_group_by(sql: str) -> str:
    """
    Détecte les colonnes dans SELECT qui ne sont pas dans GROUP BY
    et les ajoute automatiquement. Ignore toute expression contenant un agrégat.
    """
    if 'GROUP BY' not in sql.upper():
        return sql

    select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
    group_match  = re.search(r'GROUP BY\s+(.*?)(?:ORDER BY|HAVING|LIMIT|$)', sql, re.IGNORECASE | re.DOTALL)

    if not select_match or not group_match:
        return sql

    select_cols = select_match.group(1)
    group_cols  = group_match.group(1).strip()

    agg_pattern = re.compile(r'(COUNT|SUM|AVG|MIN|MAX)\s*\(', re.IGNORECASE)

    non_aggregated = []
    for col in select_cols.split(','):
        col = col.strip()

        # Ignorer toute expression qui CONTIENT un agrégat (même imbriqué)
        if agg_pattern.search(col):
            continue

        # Garder uniquement la partie avant AS
        col_clean = re.split(r'\s+AS\s+', col, flags=re.IGNORECASE)[0].strip()

        if col_clean and col_clean.upper() not in group_cols.upper():
            non_aggregated.append(col_clean)

    if not non_aggregated:
        return sql

    new_group = group_cols + ', ' + ', '.join(non_aggregated)
    sql = re.sub(
        r'(GROUP BY\s+)(.*?)(?=(ORDER BY|HAVING|LIMIT|$))',
        lambda m: m.group(1) + new_group + ' ',
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sql


def _fix_having_vs_where(sql: str) -> str:
    """
    Déplace les conditions avec agrégats du WHERE vers HAVING.
    Ex : WHERE COUNT(*) > 10  →  HAVING COUNT(*) > 10
    """
    agg_pattern = r'(COUNT|SUM|AVG|MIN|MAX)\s*\('

    def move_to_having(match):
        where_clause = match.group(1)
        conditions   = re.split(r'\bAND\b', where_clause, flags=re.IGNORECASE)

        where_conds  = []
        having_conds = []

        for cond in conditions:
            if re.search(agg_pattern, cond, re.IGNORECASE):
                having_conds.append(cond.strip())
            else:
                where_conds.append(cond.strip())

        result = ''
        if where_conds:
            result += 'WHERE ' + ' AND '.join(where_conds) + ' '
        if having_conds:
            result += 'HAVING ' + ' AND '.join(having_conds) + ' '
        return result

    sql = re.sub(
        r'WHERE\s+(.*?)(?=GROUP BY|ORDER BY|LIMIT|$)',
        move_to_having,
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return sql


def _fix_metier_values(sql: str) -> str:
    corrections = {
        # Statuts déclarations
        r'\bLIQUIDATED\b':      'LIQUIDEE',
        r'\bLIQUIDÉE\b':        'LIQUIDEE',
        r'\bIN_PROGRESS\b':     'EN_COURS',
        r'\bIN PROGRESS\b':     'EN_COURS',
        r'\bREGISTERED\b':      'ENREGISTREE',
        r'\bENREGISTRÉE\b':     'ENREGISTREE',
        r'\bVALIDATED\b':       'VALIDEE',
        r'\bVALIDÉE\b':         'VALIDEE',
        r'\bABANDONED\b':       'ABANDONNEE',
        r'\bABANDONNÉE\b':      'ABANDONNEE',
        r'\bDISPUTE\b':         'CONTENTIEUX',
        r'\bLITIGE\b':          'CONTENTIEUX',

        # Statuts paiement
        r'\bPAID\b':            'PAYE',
        r'\bPAYÉ\b':            'PAYE',
        r'\bPENDING\b':         'EN_ATTENTE',
        r'\bEN ATTENTE\b':      'EN_ATTENTE',
        r'\bEXEMPT\b':          'EXONERE',
        r'\bEXONÉRÉ\b':         'EXONERE',

        # Codes régimes
        r'\bIMPORT\b':          'IM',
        r'\bIMPORTATION\b':     'IM',
        r'\bEXPORT\b':          'EX',
        r'\bEXPORTATION\b':     'EX',
        r'\bTRANSIT\b':         'TF',
        r'\bADMISSION_TEMP\b':  'AT',
        r'\bADMISSION TEMP\b':  'AT',
        r'\bZONE_FRANCHE\b':    'ZF',
        r'\bZONE FRANCHE\b':    'ZF',

        # Types droits
        r'\bCUSTOMS\b':         'DD',
        r'\bDROIT_DOUANE\b':    'DD',
        r'\bVAT\b':             'TVA',
        r'\bPARAFISCAL\b':      'PCS',
        r'\bREDEVANCE\b':       'RS',
        r'\bPRELEVEMENT\b':     'PE',

        # Types opérateurs
        r'\bIMPORTER\b':        'IMPORTATEUR',
        r'\bEXPORTER\b':        'EXPORTATEUR',
        r'\bFREIGHT\b':         'TRANSITAIRE',
        r'\bMIXED\b':           'MIXTE',

        # Statuts opérateurs
        r'\bACTIVE\b':          'ACTIF',
        r'\bSUSPENDED\b':       'SUSPENDU',
        r'\bREVOKED\b':         'RADIE',
        r'\bRADIÉ\b':           'RADIE',
    }

    for pattern, replacement in corrections.items():
        sql = re.sub(
            rf"(['\"]){pattern}(['\"])",
            rf'\g<1>{replacement}\g<2>',
            sql,
            flags=re.IGNORECASE,
        )
    return sql

def _fix_join_keys(sql: str) -> str:
    """
    Corrige les clés de jointure incorrectes spécifiques au schéma douanier.
    Le LLM invente souvent des colonnes qui n'existent pas.
    """
    corrections = {
        # Jointure pays — la colonne s'appelle pays_origine, pas id_pays
        r'd\.id_pays\s*=\s*p\.code_pays':       'd.pays_origine = p.code_pays',
        r'd\.pays_id\s*=\s*p\.code_pays':        'd.pays_origine = p.code_pays',
        r'd\.pays\s*=\s*p\.code_pays':           'd.pays_origine = p.code_pays',

        # Jointure opérateurs
        r'd\.operateur_id\s*=\s*o\.id_operateur': 'd.id_operateur = o.id_operateur',
        r'd\.id_op\s*=\s*o\.id_operateur':        'd.id_operateur = o.id_operateur',

        # Jointure bureaux
        r'd\.bureau_id\s*=\s*b\.id_bureau':       'd.id_bureau = b.id_bureau',
        r'd\.id_bur\s*=\s*b\.id_bureau':          'd.id_bureau = b.id_bureau',

        # Jointure marchandises
        r'm\.declaration_id\s*=\s*d\.id_declaration': 'm.id_declaration = d.id_declaration',

        # Jointure droits_taxes
        r'dt\.declaration_id\s*=\s*d\.id_declaration': 'dt.id_declaration = d.id_declaration',
    }

    for wrong, correct in corrections.items():
        sql = re.sub(wrong, correct, sql, flags=re.IGNORECASE)

    return sql


def _fix_extract_syntax(sql: str) -> str:
    """
    Corrige la syntaxe d'extraction de date — PostgreSQL utilise EXTRACT(YEAR FROM col).
    Le LLM génère souvent la syntaxe MySQL (YEAR()) ou d'autres variantes invalides.
    """
    # YEAR(col) → EXTRACT(YEAR FROM col)
    sql = re.sub(
        r'\bYEAR\s*\((\w+\.\w+|\w+)\)',
        r'EXTRACT(YEAR FROM \1)',
        sql,
        flags=re.IGNORECASE,
    )
    # MONTH(col) → EXTRACT(MONTH FROM col)
    sql = re.sub(
        r'\bMONTH\s*\((\w+\.\w+|\w+)\)',
        r'EXTRACT(MONTH FROM \1)',
        sql,
        flags=re.IGNORECASE,
    )
    # col.year → EXTRACT(YEAR FROM col)
    sql = re.sub(
        r'(\w+\.\w+)\.year\b',
        r'EXTRACT(YEAR FROM \1)',
        sql,
        flags=re.IGNORECASE,
    )
    # DATE_FORMAT(col, '%Y') → EXTRACT(YEAR FROM col)
    sql = re.sub(
        r"DATE_FORMAT\s*\((\w+\.\w+|\w+)\s*,\s*'%Y'\)",
        r'EXTRACT(YEAR FROM \1)',
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _fix_missing_limit(sql: str) -> str:
    """
    Ajoute LIMIT 1000 si la requête n'en a pas et risque de retourner
    trop de lignes (SELECT sans filtre strict sur une grande table).
    Ne touche pas aux requêtes qui ont déjà un LIMIT ou un COUNT(*).
    """
    has_limit     = bool(re.search(r'\bLIMIT\b', sql, re.IGNORECASE))
    has_count     = bool(re.search(r'\bCOUNT\s*\(', sql, re.IGNORECASE))
    has_aggregate = bool(re.search(r'\b(SUM|AVG|MIN|MAX)\s*\(', sql, re.IGNORECASE))
    has_group_by  = bool(re.search(r'\bGROUP BY\b', sql, re.IGNORECASE))

    if has_limit or has_count:
        return sql

    # Si pas d'agrégat et pas de GROUP BY → requête qui peut retourner beaucoup de lignes
    if not has_aggregate and not has_group_by:
        sql = sql.rstrip().rstrip(';')
        sql += '\nLIMIT 1000;'

    return sql