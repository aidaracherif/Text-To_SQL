"""
infrastructure/database/user_repository.py — Accès BDD pour la table users.

Pattern Repository : encapsule toute la logique SQL liée aux utilisateurs.
Ne contient AUCUNE logique métier (pas de hashage ici, pas de JWT) — juste
des CRUDs. La logique de sécurité est dans auth/security.py.
"""

import logging
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from config.settings import DB_CONFIG

logger = logging.getLogger(__name__)


class UserRepository:
    """
    Accès à la table users.
    Ouvre une nouvelle connexion à chaque appel (cohérent avec AuditRepository).
    """

    def __init__(self, db_config: dict | None = None):
        self.db_config = db_config or DB_CONFIG

    # ──────────────────────────────────────────────────────────────────────────
    # Connexion
    # ──────────────────────────────────────────────────────────────────────────

    def _connect(self):
        return psycopg2.connect(**self.db_config)

    # ──────────────────────────────────────────────────────────────────────────
    # CRÉATION
    # ──────────────────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        username: str,
        password_hash: str,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        role: str = "user",
    ) -> Optional[dict]:
        """
        Insère un nouvel utilisateur.
        Retourne le dict du user créé (sans le password_hash).
        Lève ValueError si le username existe déjà.
        """
        sql = """
            INSERT INTO users (username, password_hash, email, full_name, role)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, username, email, full_name, role, is_active, created_at;
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (username, password_hash, email, full_name, role))
                    row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
            finally:
                conn.close()
        except psycopg2.errors.UniqueViolation:
            raise ValueError(f"Le nom d'utilisateur '{username}' existe déjà.")
        except Exception as exc:
            logger.error(f"[UserRepository] Échec création user : {exc}")
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # LECTURE
    # ──────────────────────────────────────────────────────────────────────────

    def get_by_username(self, username: str) -> Optional[dict]:
        """
        Retourne le user complet (avec password_hash) pour la phase de login.
        Retourne None si introuvable ou si la BDD est down.
        """
        sql = """
            SELECT id, username, email, full_name, role, is_active,
                   password_hash, created_at, last_login_at
            FROM users
            WHERE username = %s;
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (username,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[UserRepository] Échec get_by_username : {exc}")
            return None

    def get_by_id(self, user_id: int) -> Optional[dict]:
        """Retourne un user par son id (sans password_hash, pour usage public)."""
        sql = """
            SELECT id, username, email, full_name, role, is_active,
                   created_at, last_login_at
            FROM users
            WHERE id = %s;
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql, (user_id,))
                    row = cur.fetchone()
                    return dict(row) if row else None
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[UserRepository] Échec get_by_id : {exc}")
            return None

    def list_all(self) -> list[dict]:
        """Liste tous les utilisateurs (pour la gestion admin)."""
        sql = """
            SELECT id, username, email, full_name, role, is_active,
                   created_at, last_login_at
            FROM users
            ORDER BY created_at DESC;
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(sql)
                    return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[UserRepository] Échec list_all : {exc}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # MISE À JOUR
    # ──────────────────────────────────────────────────────────────────────────

    def update_last_login(self, user_id: int) -> None:
        """Met à jour last_login_at = NOW(). Échec silencieux."""
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET last_login_at = NOW() WHERE id = %s;",
                        (user_id,),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[UserRepository] Échec update_last_login : {exc}")

    def set_active(self, user_id: int, is_active: bool) -> bool:
        """Active/désactive un compte. Retourne True si la maj a réussi."""
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET is_active = %s WHERE id = %s;",
                        (is_active, user_id),
                    )
                    affected = cur.rowcount
                conn.commit()
                return affected > 0
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(f"[UserRepository] Échec set_active : {exc}")
            return False