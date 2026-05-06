"""
Tests d'API pour api/routers/auth.py + protection des autres routes.

Couvre :
  - POST /api/v1/auth/login    : succès, mauvais mot de passe, user inactif
  - POST /api/v1/auth/register : admin uniquement, validation, conflit username
  - GET  /api/v1/auth/me       : retourne le user courant
  - GET  /api/v1/auth/users    : admin uniquement
  - Protection des routes /query et /history (401 sans token)
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from api.dependencies import get_service
from auth.dependencies import get_current_user, require_admin
from auth.security import hash_password


# =============================================================================
# Fixtures locales
# =============================================================================

@pytest.fixture
def mock_repo():
    """UserRepository mocké."""
    return MagicMock()


@pytest.fixture
def auth_client():
    """TestClient sans bypass d'auth — pour tester l'auth elle-même."""
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(fake_admin):
    """TestClient avec un admin authentifié (pour les routes admin-only)."""
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    app.dependency_overrides[require_admin] = lambda: fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def user_client(fake_user):
    """TestClient avec un user normal (PAS admin)."""
    app.dependency_overrides[get_current_user] = lambda: fake_user
    # require_admin ne doit PAS être bypass — les tests doivent vérifier le 403
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# =============================================================================
# POST /api/v1/auth/login
# =============================================================================

class TestLoginEndpoint:

    @patch("api.routers.auth._get_repo")
    def test_login_success_returns_token(self, mock_get_repo, auth_client):
        """Login avec bons identifiants → 200 + token JWT."""
        repo = MagicMock()
        repo.get_by_username.return_value = {
            "id": 1,
            "username": "alice",
            "password_hash": hash_password("correct_password"),
            "role": "user",
            "is_active": True,
        }
        mock_get_repo.return_value = repo

        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "correct_password"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]  # non vide
        assert body["expires_in_seconds"] > 0

    @patch("api.routers.auth._get_repo")
    def test_login_wrong_password_returns_401(self, mock_get_repo, auth_client):
        repo = MagicMock()
        repo.get_by_username.return_value = {
            "id": 1,
            "username": "alice",
            "password_hash": hash_password("correct_password"),
            "role": "user",
            "is_active": True,
        }
        mock_get_repo.return_value = repo

        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "WRONG"},
        )
        assert resp.status_code == 401

    @patch("api.routers.auth._get_repo")
    def test_login_unknown_user_returns_401(self, mock_get_repo, auth_client):
        """Si le user n'existe pas → 401 (pas 404, pour ne pas leaker)."""
        repo = MagicMock()
        repo.get_by_username.return_value = None
        mock_get_repo.return_value = repo

        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "ghost", "password": "anything"},
        )
        assert resp.status_code == 401

    @patch("api.routers.auth._get_repo")
    def test_login_inactive_user_returns_403(self, mock_get_repo, auth_client):
        repo = MagicMock()
        repo.get_by_username.return_value = {
            "id": 1,
            "username": "alice",
            "password_hash": hash_password("correct_password"),
            "role": "user",
            "is_active": False,
        }
        mock_get_repo.return_value = repo

        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "correct_password"},
        )
        assert resp.status_code == 403

    def test_login_validates_input(self, auth_client):
        """Username trop court → 422."""
        resp = auth_client.post(
            "/api/v1/auth/login",
            json={"username": "ab", "password": "x"},
        )
        assert resp.status_code == 422


# =============================================================================
# POST /api/v1/auth/register (admin uniquement)
# =============================================================================

class TestRegisterEndpoint:

    @patch("api.routers.auth._get_repo")
    def test_admin_can_register_new_user(self, mock_get_repo, admin_client):
        repo = MagicMock()
        repo.create.return_value = {
            "id": 2,
            "username": "newuser",
            "email": "new@dgd.sn",
            "full_name": "New User",
            "role": "user",
            "is_active": True,
            "created_at": "2024-05-01T00:00:00",
        }
        mock_get_repo.return_value = repo

        resp = admin_client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "password": "VeryStrongPwd123",
                "email": "new@dgd.sn",
                "full_name": "New User",
                "role": "user",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "newuser"
        assert "password" not in body  # JAMAIS dans la réponse
        assert "password_hash" not in body

    @patch("api.routers.auth._get_repo")
    def test_register_conflict_returns_409(self, mock_get_repo, admin_client):
        """Username déjà pris → 409."""
        repo = MagicMock()
        repo.create.side_effect = ValueError("Le nom d'utilisateur 'alice' existe déjà.")
        mock_get_repo.return_value = repo

        resp = admin_client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "password": "StrongPwd123",
                "role": "user",
            },
        )
        assert resp.status_code == 409

    def test_user_cannot_register(self, user_client):
        """Un simple user ne peut PAS créer de comptes → 403."""
        resp = user_client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "password": "StrongPwd123",
                "role": "user",
            },
        )
        assert resp.status_code == 403

    def test_anonymous_cannot_register(self, auth_client):
        """Sans token → 401."""
        resp = auth_client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "password": "StrongPwd123",
                "role": "user",
            },
        )
        assert resp.status_code == 401

    def test_register_password_too_short(self, admin_client):
        """min_length=8."""
        resp = admin_client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "password": "1234567"},
        )
        assert resp.status_code == 422

    def test_register_username_with_special_chars(self, admin_client):
        """Pattern : ^[a-zA-Z0-9_.-]+$ — refuse les espaces, @, etc."""
        resp = admin_client.post(
            "/api/v1/auth/register",
            json={"username": "alice@bob", "password": "StrongPwd123"},
        )
        assert resp.status_code == 422


# =============================================================================
# GET /api/v1/auth/me
# =============================================================================

class TestMeEndpoint:

    def test_me_returns_current_user(self, user_client, fake_user):
        resp = user_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == fake_user["username"]
        assert body["role"] == fake_user["role"]
        # password_hash absent
        assert "password_hash" not in body

    def test_me_requires_auth(self, auth_client):
        """Sans token → 401."""
        resp = auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 401


# =============================================================================
# GET /api/v1/auth/users (admin uniquement)
# =============================================================================

class TestListUsersEndpoint:

    @patch("api.routers.auth._get_repo")
    def test_admin_can_list_users(self, mock_get_repo, admin_client):
        repo = MagicMock()
        repo.list_all.return_value = [
            {
                "id": 1, "username": "alice", "email": None, "full_name": None,
                "role": "user", "is_active": True,
                "created_at": "2024-01-01T00:00:00", "last_login_at": None,
            },
        ]
        mock_get_repo.return_value = repo

        resp = admin_client.get("/api/v1/auth/users")
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) == 1
        assert users[0]["username"] == "alice"

    def test_user_cannot_list_users(self, user_client):
        resp = user_client.get("/api/v1/auth/users")
        assert resp.status_code == 403

    def test_anonymous_cannot_list_users(self, auth_client):
        resp = auth_client.get("/api/v1/auth/users")
        assert resp.status_code == 401


# =============================================================================
# PROTECTION DES ROUTES MÉTIER (sans token → 401)
# =============================================================================

class TestRouteProtection:
    """
    Vérifie que les routes /query et /history sont bien protégées.
    Critique côté sécurité.
    """

    def test_query_requires_auth(self, auth_client):
        resp = auth_client.post(
            "/api/v1/query",
            json={"question": "test test test"},
        )
        assert resp.status_code == 401

    def test_history_requires_auth(self, auth_client):
        resp = auth_client.get("/api/v1/history")
        assert resp.status_code == 401

    def test_history_detail_requires_admin(self, user_client):
        """Un user normal ne peut PAS voir les détails (champs sensibles)."""
        resp = user_client.get("/api/v1/history/1")
        assert resp.status_code == 403

    def test_clear_history_requires_admin(self, user_client):
        """Un user normal ne peut PAS vider l'historique."""
        resp = user_client.delete("/api/v1/history")
        assert resp.status_code == 403

    def test_health_does_not_require_auth(self, auth_client):
        """L'endpoint /health doit rester PUBLIC pour le monitoring."""
        # On override get_service inline pour ne pas dépendre d'Ollama
        from unittest.mock import MagicMock
        svc = MagicMock()
        svc.health_check.return_value = {"llm": True, "db": True, "rag": True}
        app.dependency_overrides[get_service] = lambda: svc

        resp = auth_client.get("/api/v1/health")
        assert resp.status_code == 200