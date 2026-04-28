"""
infrastructure/database/schema_loader.py — Lecture du schéma PostgreSQL.
Responsabilité unique : lire le catalogue PostgreSQL et produire une description textuelle.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from functools import lru_cache
from config.settings import DB_CONFIG


class SchemaLoader:
    """
    Lit le schéma de la base PostgreSQL et génère un texte descriptif
    utilisé comme contexte dans les prompts LLM.
    """

    def __init__(self, db_config: dict = None):
        self.db_config = db_config or DB_CONFIG
        self._schema_cache: dict = {}
        self._stats_cache: str   = ""

    def _connect(self):
        return psycopg2.connect(**self.db_config)

    # ──────────────────────────────────────────────────────────────────────────
    # Lecture du catalogue PostgreSQL
    # ──────────────────────────────────────────────────────────────────────────

    def load_schema(self) -> dict:
        """
        Lit les tables, colonnes, types et clés étrangères depuis PostgreSQL.
        Retourne un dict structuré { table_name: { columns, foreign_keys, comment } }.
        """
        conn = self._connect()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Tables
            cur.execute("""
                SELECT t.table_name,
                       obj_description(
                           (quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass,
                           'pg_class'
                       ) AS table_comment
                FROM information_schema.tables t
                WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
                ORDER BY t.table_name
            """)
            schema = {
                row["table_name"]: {
                    "comment": row["table_comment"] or "",
                    "columns": [],
                    "foreign_keys": [],
                }
                for row in cur.fetchall()
            }

            # Colonnes
            cur.execute("""
                SELECT c.table_name, c.column_name, c.data_type,
                       c.character_maximum_length, c.numeric_precision,
                       c.numeric_scale, c.is_nullable, c.column_default,
                       col_description(
                           (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                           c.ordinal_position
                       ) AS col_comment
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                ORDER BY c.table_name, c.ordinal_position
            """)
            for col in cur.fetchall():
                tname = col["table_name"]
                if tname not in schema:
                    continue
                dtype = col["data_type"]
                if dtype == "character varying" and col["character_maximum_length"]:
                    dtype = f"VARCHAR({col['character_maximum_length']})"
                elif dtype == "numeric" and col["numeric_precision"]:
                    dtype = f"NUMERIC({col['numeric_precision']},{col['numeric_scale'] or 0})"
                schema[tname]["columns"].append({
                    "name":     col["column_name"],
                    "type":     dtype.upper(),
                    "nullable": col["is_nullable"] == "YES",
                    "default":  col["column_default"],
                    "comment":  col["col_comment"] or "",
                })

            # Clés étrangères
            cur.execute("""
                SELECT tc.table_name, kcu.column_name,
                       ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
                ORDER BY tc.table_name
            """)
            for fk in cur.fetchall():
                tname = fk["table_name"]
                if tname in schema:
                    schema[tname]["foreign_keys"].append({
                        "column":     fk["column_name"],
                        "references": fk["foreign_table"],
                        "ref_column": fk["foreign_column"],
                    })

            self._schema_cache = schema
            return schema

        finally:
            conn.close()

    def load_stats(self) -> str:
        """Retourne un résumé des volumes par table (COUNT)."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            lines = ["## Volumes approximatifs"]
            for table in ["declarations", "operateurs", "bureaux", "marchandises", "droits_taxes"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cur.fetchone()[0]
                    lines.append(f"- {table} : {count:,} lignes")
                except Exception:
                    pass
            self._stats_cache = "\n".join(lines)
            return self._stats_cache
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Génération du texte de schéma pour le prompt LLM
    # ──────────────────────────────────────────────────────────────────────────

    def schema_to_text(self, schema: dict = None) -> str:
        """Convertit le schéma dict en texte lisible pour le LLM."""
        if schema is None:
            schema = self._schema_cache or self.load_schema()

        table_order = [
            "pays", "regimes", "bureaux", "operateurs",
            "declarations", "marchandises", "droits_taxes",
        ]
        ordered = table_order + [t for t in schema if t not in table_order]
        lines = []

        for tname in ordered:
            if tname not in schema:
                continue
            tinfo = schema[tname]
            header = f"### Table : {tname}"
            if tinfo["comment"]:
                header += f"  — {tinfo['comment']}"
            lines.append(header)
            for col in tinfo["columns"]:
                line = f"  - {col['name']} ({col['type']})"
                if col.get("comment"):
                    line += f" → {col['comment']}"
                if col.get("distinct_values"):
                    vals = ", ".join(f"'{v}'" for v in col["distinct_values"])
                    line += f" | valeurs : {vals}"
                lines.append(line)
            for fk in tinfo.get("foreign_keys", []):
                lines.append(f"  ↳ {fk['column']} référence {fk['references']}.{fk['ref_column']}")
            lines.append("")

        lines.extend([
            "## Jointures standard",
            "- declarations ↔ operateurs  : d.id_operateur = o.id_operateur",
            "- declarations ↔ bureaux      : d.id_bureau = b.id_bureau",
            "- declarations ↔ regimes      : d.code_regime = r.code_regime",
            "- declarations ↔ pays         : d.pays_origine = p.code_pays",
            "- marchandises ↔ declarations : m.id_declaration = d.id_declaration",
            "- droits_taxes ↔ declarations : dt.id_declaration = d.id_declaration",
        ])
        return "\n".join(lines)

    def get_schema_and_stats(self) -> tuple[str, str]:
        """
        Retourne (schema_text, stats_text).
        Utilise le cache si disponible.
        """
        schema_text = self.schema_to_text()
        stats_text  = self._stats_cache or self.load_stats()
        return schema_text, stats_text

    def get_summary(self) -> str:
        """Résumé court : table → colonnes (pour les logs)."""
        schema = self._schema_cache or self.load_schema()
        return "\n".join(
            f"{tname} ({', '.join(c['name'] for c in tinfo['columns'])})"
            for tname, tinfo in schema.items()
        )
