"""
infrastructure/database/audit_repository.py — Accès BDD pour la table audit_log.

Sépare proprement les opérations d'audit (INSERT + SELECT sur audit_log)
du DBConnector métier (qui ne fait que des SELECT sur les tables douanières).

Pattern : Repository — encapsule toute la logique SQL de la table audit.
"""

import json
import logging
from typing import Any, Optional
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor, Json

from config.settings import DB_CONFIG

logger = logging.getLogger(__name__)


# Limite la taille du preview des lignes pour éviter d'exploser la BDD
ROWS_PREVIEW_LIMIT = 10


class AuditRepository:
    """
    Accès à la table audit_log.
    Crée une nouvelle connexion à chaque appel (cohérent avec DBConnector).
    """

    def __init__(self, db_config: dict | None = None):
        self.db_config = db_config or DB_CONFIG

    # ──────────────────────────────────────────────────────────────────────────
    # Connexion
    # ──────────────────────────────────────────────────────────────────────────

    def _connect(self):
        try:
            return psycopg2.connect(**self.db_config)
        except psycopg2.OperationalError as exc:
            raise ConnectionError(
                f"Impossible de se connecter à PostgreSQL pour l'audit : {exc}"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # INSERT — enregistrer une requête
    # ──────────────────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        # Niveau MINIMAL
        question: str,
        sql: str,
        success: bool,
        row_count: int = 0,
        duration_ms: float = 0.0,
        # Niveau COMPLET
        user_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        columns: Optional[list[str]] = None,
        rows: Optional[list[list[Any]]] = None,
        error_message: Optional[str] = None,
        error_raw: Optional[str] = None,
        warning: Optional[str] = None,
        # Niveau AUDIT LOURD
        rag_context: Optional[dict] = None,
        rag_route: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_raw_output: Optional[str] = None,
    ) -> Optional[int]:
        """
        Insère une entrée dans audit_log et retourne son id.
        En cas d'échec d'écriture, log un warning mais ne lève pas d'exception
        pour ne pas casser l'API métier.
        """
        # Tronquer le preview à ROWS_PREVIEW_LIMIT lignes max
        rows_preview = rows[:ROWS_PREVIEW_LIMIT] if rows else None

        sql_insert = """
            INSERT INTO audit_log (
                question, sql, success, row_count, duration_ms,
                user_name, ip_address, user_agent,
                columns_json, rows_preview, error_message, error_raw, warning,
                rag_context, rag_route, system_prompt, user_prompt,
                llm_model, llm_raw_output
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            RETURNING id;
        """

        params = (
            question, sql, success, row_count, duration_ms,
            user_name, ip_address, user_agent,
            Json(columns) if columns is not None else None,
            Json(rows_preview, dumps=_safe_json_dumps) if rows_preview else None,
            error_message, error_raw, warning,
            Json(rag_context) if rag_context else None,
            rag_route, system_prompt, user_prompt,
            llm_model, llm_raw_output,
        )

        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql_insert, params)
                    new_id = cur.fetchone()[0]
                conn.commit()
                return new_id
            finally:
                conn.close()
        except Exception as exc:
            # On ne veut JAMAIS faire crasher l'API à cause d'un problème d'audit
            logger.warning(f"[AuditRepository] Échec d'écriture audit : {exc}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # SELECT — récupérer l'historique
    # ──────────────────────────────────────────────────────────────────────────

    def list_recent(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        Retourne les `limit` dernières entrées (les plus récentes en premier).
        Format adapté au schema HistoryEntry de l'API.
        """
        sql = """
            SELECT
                id, question, sql, row_count, duration_ms, success,
                created_at
            FROM audit_log
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s;
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (limit, offset))
                    rows = cur.fetchall()
            finally:
                conn.close()

            # Convertir created_at en string ISO pour la sérialisation JSON
            result = []
            for row in rows:
                d = dict(row)
                ts: datetime = d.pop("created_at")
                d["timestamp"] = ts.strftime("%Y-%m-%d %H:%M:%S")
                result.append(d)
            return result
        except Exception as exc:
            logger.warning(f"[AuditRepository] Échec lecture historique : {exc}")
            return []

    def count(self) -> int:
        """Compte total des entrées d'audit."""
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM audit_log;")
                    return cur.fetchone()[0]
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[AuditRepository] Échec count : {exc}")
            return 0

    def get_by_id(self, audit_id: int) -> Optional[dict]:
        """Retourne une entrée d'audit complète (tous champs) par son id."""
        sql = "SELECT * FROM audit_log WHERE id = %s;"
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (audit_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[AuditRepository] Échec get_by_id : {exc}")
            return None

    def clear(self) -> int:
        """
        Vide la table d'audit. Retourne le nombre de lignes supprimées.
        À utiliser avec précaution (endpoint admin uniquement).
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit_log;")
                    deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[AuditRepository] Échec clear : {exc}")
            return 0


# =============================================================================
# Helpers
# =============================================================================

def _safe_json_dumps(obj):
    """
    Sérialise en JSON en gérant les types non-natifs (datetime, Decimal, bytes...).
    Évite les erreurs sur les données issues de PostgreSQL.
    """
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if hasattr(o, "isoformat"):     # date, time
            return o.isoformat()
        if isinstance(o, (bytes, bytearray)):
            return o.decode("utf-8", errors="replace")
        # Decimal et autres → str
        return str(o)

    return json.dumps(obj, default=default, ensure_ascii=False)