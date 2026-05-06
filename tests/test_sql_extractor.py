"""
Tests unitaires pour core/sql_extractor.py

Couvre :
  - extract_sql() : extraction depuis ```sql, ``` ou texte brut
  - validate_sql() : refus des INSERT/UPDATE/DELETE/etc.
  - is_out_of_schema() : détection du marqueur LLM
  - fix_sql() : corrections automatiques (alias, valeurs métier, EXTRACT, LIMIT)
"""

import pytest

from core.sql_extractor import (
    extract_sql,
    validate_sql,
    is_out_of_schema,
    fix_sql,
)


# =============================================================================
# extract_sql() — extraction du SQL depuis la réponse LLM
# =============================================================================

class TestExtractSql:

    def test_extracts_from_sql_fenced_block(self):
        """Format standard ```sql ... ```"""
        response = "Voici le SQL :\n```sql\nSELECT * FROM declarations;\n```"
        assert extract_sql(response) == "SELECT * FROM declarations;"

    def test_extracts_from_generic_fenced_block(self):
        """Le LLM oublie parfois le tag 'sql' → ``` ... ```"""
        response = "```\nSELECT id FROM bureaux;\n```"
        assert extract_sql(response) == "SELECT id FROM bureaux;"

    def test_extracts_when_no_fences(self):
        """Le LLM peut renvoyer le SQL brut sans markdown"""
        response = "  SELECT * FROM declarations;  "
        assert extract_sql(response) == "SELECT * FROM declarations;"

    def test_handles_uppercase_sql_tag(self):
        """```SQL doit être reconnu (insensible à la casse)"""
        response = "```SQL\nSELECT 1;\n```"
        assert extract_sql(response) == "SELECT 1;"

    def test_handles_multiline_sql(self):
        response = """```sql
SELECT id, nom
FROM declarations
WHERE date_enregistrement >= '2024-01-01';
```"""
        result = extract_sql(response)
        assert "SELECT id, nom" in result
        assert "WHERE date_enregistrement" in result

    def test_first_block_wins_when_multiple(self):
        """Si plusieurs blocs, on prend le premier (cas du LLM bavard)"""
        response = "```sql\nSELECT 1;\n```\nblabla\n```sql\nSELECT 2;\n```"
        assert extract_sql(response) == "SELECT 1;"


# =============================================================================
# validate_sql() — refus des opérations dangereuses
# =============================================================================

class TestValidateSql:

    def test_accepts_simple_select(self):
        validate_sql("SELECT * FROM declarations;")  # Ne lève pas

    def test_accepts_with_cte(self):
        sql = "WITH t AS (SELECT * FROM declarations) SELECT * FROM t;"
        validate_sql(sql)  # Ne lève pas

    def test_rejects_empty_sql(self):
        with pytest.raises(ValueError, match="vide"):
            validate_sql("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="vide"):
            validate_sql("   \n  ")

    @pytest.mark.parametrize("dangerous_sql", [
        "INSERT INTO declarations VALUES (1);",
        "UPDATE declarations SET nom='X';",
        "DELETE FROM declarations;",
        "DROP TABLE declarations;",
        "TRUNCATE declarations;",
        "ALTER TABLE declarations ADD col TEXT;",
        "CREATE TABLE x (id INT);",
        "GRANT ALL ON declarations TO user;",
    ])
    def test_rejects_write_operations(self, dangerous_sql):
        """Toutes les opérations d'écriture doivent être refusées."""
        with pytest.raises(ValueError, match="interdite"):
            validate_sql(dangerous_sql)

    def test_rejects_non_select_first_token(self):
        """Si ça ne commence pas par SELECT/WITH, on refuse."""
        with pytest.raises(ValueError, match="SELECT"):
            validate_sql("EXPLAIN SELECT * FROM declarations;")

    def test_rejects_insert_even_in_subquery(self):
        """INSERT dans une sous-requête est aussi refusé (sécurité)."""
        sql = "SELECT * FROM (INSERT INTO x VALUES (1) RETURNING *) sub;"
        with pytest.raises(ValueError):
            validate_sql(sql)


# =============================================================================
# is_out_of_schema() — détection question hors périmètre
# =============================================================================

class TestIsOutOfSchema:

    def test_detects_marker(self):
        assert is_out_of_schema("-- QUESTION_HORS_SCHEMA") is True

    def test_detects_marker_lowercase(self):
        assert is_out_of_schema("-- question_hors_schema") is True

    def test_detects_marker_in_middle(self):
        sql = "-- contexte\n-- QUESTION_HORS_SCHEMA\n-- fin"
        assert is_out_of_schema(sql) is True

    def test_returns_false_for_normal_sql(self):
        assert is_out_of_schema("SELECT * FROM declarations;") is False

    def test_returns_false_for_empty(self):
        assert is_out_of_schema("") is False


# =============================================================================
# fix_sql() — corrections automatiques
# =============================================================================

class TestFixSql:

    def test_translates_metier_value_paid(self):
        """'PAID' (anglais) → 'PAYE' (français douanier)"""
        sql = "SELECT * FROM declarations WHERE statut = 'PAID';"
        fixed = fix_sql(sql)
        assert "'PAYE'" in fixed
        assert "'PAID'" not in fixed

    def test_translates_metier_value_liquidated(self):
        sql = "SELECT * FROM declarations WHERE statut = 'LIQUIDATED';"
        fixed = fix_sql(sql)
        assert "'LIQUIDEE'" in fixed

    def test_handles_accented_value(self):
        """Les variantes accentuées doivent aussi être normalisées"""
        sql = "SELECT * FROM declarations WHERE statut = 'LIQUIDÉE';"
        fixed = fix_sql(sql)
        assert "'LIQUIDEE'" in fixed

    def test_does_not_touch_correct_value(self):
        sql = "SELECT * FROM declarations WHERE statut = 'PAYE';"
        fixed = fix_sql(sql)
        assert "'PAYE'" in fixed

    def test_translates_mysql_year_to_postgres(self):
        """YEAR(col) MySQL → EXTRACT(YEAR FROM col) PostgreSQL"""
        sql = "SELECT YEAR(date_enregistrement) FROM declarations;"
        fixed = fix_sql(sql)
        assert "EXTRACT(YEAR FROM date_enregistrement)" in fixed
        assert "YEAR(date_enregistrement)" not in fixed

    def test_translates_month_function(self):
        sql = "SELECT MONTH(d.date_enregistrement) FROM declarations d;"
        fixed = fix_sql(sql)
        assert "EXTRACT(MONTH FROM d.date_enregistrement)" in fixed

    def test_fixes_join_keys_pays(self):
        """La colonne s'appelle pays_origine, pas id_pays."""
        sql = "SELECT * FROM declarations d JOIN pays p ON d.id_pays = p.code_pays;"
        fixed = fix_sql(sql)
        assert "d.pays_origine = p.code_pays" in fixed

    def test_adds_limit_when_missing(self):
        """SELECT sans LIMIT ni agrégat → ajoute LIMIT 1000"""
        sql = "SELECT * FROM declarations"
        fixed = fix_sql(sql)
        assert "LIMIT 1000" in fixed

    def test_does_not_add_limit_to_count(self):
        """COUNT(*) ne doit pas avoir de LIMIT (ça n'a pas de sens)"""
        sql = "SELECT COUNT(*) FROM declarations"
        fixed = fix_sql(sql)
        assert "LIMIT" not in fixed.upper()

    def test_does_not_add_limit_when_already_present(self):
        sql = "SELECT * FROM declarations LIMIT 50"
        fixed = fix_sql(sql)
        # Doit garder LIMIT 50, pas en ajouter un autre
        assert fixed.upper().count("LIMIT") == 1
        assert "LIMIT 50" in fixed

    def test_does_not_add_limit_with_group_by(self):
        """GROUP BY = on agrège, pas besoin de LIMIT"""
        sql = "SELECT statut, COUNT(*) FROM declarations GROUP BY statut"
        fixed = fix_sql(sql)
        # Ce SQL contient un COUNT donc pas de LIMIT ajouté
        assert "LIMIT" not in fixed.upper()
