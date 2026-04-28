"""
infrastructure/database/db_connector.py — Connexion et exécution SQL sur PostgreSQL.
Responsabilité unique : ouvrir une connexion, exécuter un SELECT, retourner les données.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import DB_CONFIG, MAX_ROWS_RESULT


class DBConnector:
    """
    Connecteur PostgreSQL.
    Crée une nouvelle connexion à chaque appel (connection pooling à ajouter si besoin).
    """

    def __init__(self, db_config: dict = None):
        self.db_config = db_config or DB_CONFIG

    # ──────────────────────────────────────────────────────────────────────────
    # Connexion
    # ──────────────────────────────────────────────────────────────────────────

    def _connect(self):
        try:
            return psycopg2.connect(**self.db_config)
        except psycopg2.OperationalError as exc:
            raise ConnectionError(
                f"Impossible de se connecter à PostgreSQL : {exc}\n"
                f"Config : {self.db_config['host']}:{self.db_config['port']} "
                f"db={self.db_config['dbname']}"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Exécution d'une requête SELECT
    # ──────────────────────────────────────────────────────────────────────────

    def execute(self, sql: str, limit: int = MAX_ROWS_RESULT) -> tuple[list, list]:
        """
        Exécute une requête SQL SELECT et retourne (columns, rows).

        Paramètres :
            sql   : requête SQL valide (SELECT uniquement)
            limit : limite maximale de lignes (sécurité)

        Retourne :
            columns : liste des noms de colonnes
            rows    : liste de listes (une par ligne)

        Lève :
            ValueError    si la requête n'est pas un SELECT
            RuntimeError  en cas d'erreur PostgreSQL
        """
        first_token = sql.strip().split()[0].upper() if sql.strip() else ""
        if first_token not in ("SELECT", "WITH"):
            raise ValueError(f"Seules les requêtes SELECT sont autorisées. Reçu : {first_token}")

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description] if cur.description else []
                rows = [list(row) for row in cur.fetchmany(limit)]
            return columns, rows
        except psycopg2.Error as exc:
            raise RuntimeError(f"Erreur PostgreSQL : {exc}")
        finally:
            conn.close()

    def test_connection(self) -> bool:
        """Vérifie que la connexion à la base est opérationnelle."""
        try:
            conn = self._connect()
            conn.close()
            return True
        except Exception:
            return False
