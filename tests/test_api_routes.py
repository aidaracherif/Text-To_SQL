"""
Tests d'API pour api/routers/{query,health,history}.py

Utilise FastAPI TestClient + override_dependencies pour injecter
des mocks à la place des vrais services.

Couvre :
  - POST /api/v1/query : succès, erreur, hors-périmètre, validation Pydantic
  - GET /api/v1/health : ok / degraded
  - GET /api/v1/history : liste paginée
  - GET /api/v1/history/{id} : détail
  - DELETE /api/v1/history : clear
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from api.dependencies import get_service
from auth.dependencies import get_current_user, require_admin
from core.models import QueryResult


# =============================================================================
# Fixtures spécifiques aux tests d'API
# =============================================================================

@pytest.fixture
def mock_service():
    """Service mocké injecté à la place du vrai TextToSQLService."""
    service = MagicMock()
    return service


@pytest.fixture
def client(mock_service, fake_user, fake_admin):
    """
    TestClient avec :
      - service mocké
      - get_current_user → fake_user (utilisateur authentifié)
      - require_admin    → fake_admin (admin authentifié)

    Pour tester l'absence d'auth, utiliser `client_no_auth` à la place.
    """
    app.dependency_overrides[get_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: fake_user
    app.dependency_overrides[require_admin] = lambda: fake_admin
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_auth(mock_service):
    """TestClient SANS bypass d'auth — pour tester que les routes rejettent bien."""
    app.dependency_overrides[get_service] = lambda: mock_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# =============================================================================
# POST /api/v1/query — succès
# =============================================================================

class TestQueryEndpointSuccess:

    @patch("api.routers.query.record_query")
    def test_returns_200_on_success(self, mock_record, client, mock_service):
        mock_service.ask.return_value = QueryResult(
            question="Combien ?",
            sql="SELECT COUNT(*) FROM declarations;",
            columns=["count"],
            rows=[[42]],
            row_count=1,
            duration_ms=50.0,
        )

        resp = client.post("/api/v1/query", json={"question": "Combien de déclarations ?"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["sql"] == "SELECT COUNT(*) FROM declarations;"
        assert body["row_count"] == 1
        assert body["columns"] == ["count"]

    @patch("api.routers.query.record_query")
    def test_records_audit_on_success(self, mock_record, client, mock_service):
        """Le record_query doit être appelé exactement UNE fois en cas de succès."""
        mock_service.ask.return_value = QueryResult(
            question="test",
            sql="SELECT 1",
            columns=["x"],
            rows=[[1]],
            row_count=1,
        )
        client.post("/api/v1/query", json={"question": "test test test"})
        # Doit être appelé EXACTEMENT 1 fois (le bug corrigé en étape 1)
        assert mock_record.call_count == 1
        # success=True
        assert mock_record.call_args.kwargs["success"] is True

    @patch("api.routers.query.record_query")
    def test_includes_ip_and_user_agent_in_audit(self, mock_record, client, mock_service):
        """L'audit doit récupérer l'IP et le user-agent de la requête HTTP."""
        mock_service.ask.return_value = QueryResult(
            question="test", sql="SELECT 1", columns=["x"], rows=[[1]], row_count=1,
        )
        client.post(
            "/api/v1/query",
            json={"question": "test test test"},
            headers={"User-Agent": "test-agent/1.0"},
        )
        kwargs = mock_record.call_args.kwargs
        assert kwargs["user_agent"] == "test-agent/1.0"
        assert kwargs["ip_address"] is not None  # TestClient envoie une IP


# =============================================================================
# POST /api/v1/query — erreurs (toujours 200, erreur dans le body)
# =============================================================================

class TestQueryEndpointErrors:

    @patch("api.routers.query.record_query")
    def test_returns_error_in_body_when_pipeline_fails(self, mock_record, client, mock_service):
        """En cas d'erreur métier, on retourne 200 avec ok=false (pas 500)."""
        mock_service.ask.return_value = QueryResult(
            question="test",
            error="Ollama injoignable",
        )
        resp = client.post("/api/v1/query", json={"question": "test test test"})

        # 200 — l'API ne crashe pas
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "error" in body

    @patch("api.routers.query.record_query")
    def test_records_audit_on_error(self, mock_record, client, mock_service):
        """L'erreur doit aussi être tracée dans l'audit."""
        mock_service.ask.return_value = QueryResult(
            question="test",
            error="boom",
        )
        client.post("/api/v1/query", json={"question": "test test test"})

        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["success"] is False
        # L'erreur brute doit être conservée
        assert kwargs.get("error_raw") == "boom"

    @patch("api.routers.query.record_query")
    def test_handles_out_of_schema_question(self, mock_record, client, mock_service):
        """Question hors périmètre → ok=false avec un message friendly."""
        mock_service.ask.return_value = QueryResult(
            question="météo",
            warning="Question hors périmètre du schéma douanier.",
        )
        resp = client.post("/api/v1/query", json={"question": "Quelle est la météo ?"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "error" in body

    @patch("api.routers.query.record_query")
    def test_records_audit_for_out_of_schema(self, mock_record, client, mock_service):
        """Le hors-périmètre est aussi tracé (success=False, warning rempli)."""
        mock_service.ask.return_value = QueryResult(
            question="météo",
            warning="Question hors périmètre du schéma douanier.",
        )
        client.post("/api/v1/query", json={"question": "Quelle est la météo ?"})

        assert mock_record.call_count == 1
        kwargs = mock_record.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs.get("warning") is not None


# =============================================================================
# Validation Pydantic
# =============================================================================

class TestQueryValidation:

    def test_rejects_too_short_question(self, client):
        """min_length=3 dans le schéma → 422."""
        resp = client.post("/api/v1/query", json={"question": "ab"})
        assert resp.status_code == 422

    def test_rejects_missing_question(self, client):
        resp = client.post("/api/v1/query", json={})
        assert resp.status_code == 422

    def test_rejects_question_too_long(self, client):
        """max_length=1000."""
        resp = client.post("/api/v1/query", json={"question": "a" * 1001})
        assert resp.status_code == 422


# =============================================================================
# GET /api/v1/health
# =============================================================================

class TestHealthEndpoint:

    def test_returns_ok_when_all_up(self, client, mock_service):
        mock_service.health_check.return_value = {
            "llm": True, "db": True, "rag": True
        }
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["llm"] is True
        assert body["db"] is True

    def test_returns_degraded_when_db_down(self, client, mock_service):
        mock_service.health_check.return_value = {
            "llm": True, "db": False, "rag": True
        }
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] is False

    def test_returns_degraded_when_llm_down(self, client, mock_service):
        mock_service.health_check.return_value = {
            "llm": False, "db": True, "rag": None
        }
        resp = client.get("/api/v1/health")
        body = resp.json()
        assert body["status"] == "degraded"

    def test_rag_optional(self, client, mock_service):
        """Si RAG = None (désactivé), pas de status degraded à cause de ça."""
        mock_service.health_check.return_value = {
            "llm": True, "db": True, "rag": None
        }
        resp = client.get("/api/v1/health")
        body = resp.json()
        assert body["status"] == "ok"  # RAG None ≠ degraded
        assert body["rag"] is None


# =============================================================================
# GET /api/v1/history
# =============================================================================

class TestHistoryEndpoint:

    @patch("api.routers.history._get_repo")
    def test_returns_empty_history(self, mock_get_repo, client):
        repo = MagicMock()
        repo.list_recent.return_value = []
        repo.count.return_value = 0
        mock_get_repo.return_value = repo

        resp = client.get("/api/v1/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["entries"] == []
        assert body["total"] == 0

    @patch("api.routers.history._get_repo")
    def test_returns_history_entries(self, mock_get_repo, client):
        repo = MagicMock()
        repo.list_recent.return_value = [
            {
                "id": 1,
                "question": "Combien ?",
                "sql": "SELECT 1",
                "row_count": 1,
                "duration_ms": 100.0,
                "success": True,
                "timestamp": "2024-05-15 10:00:00",
            }
        ]
        repo.count.return_value = 1
        mock_get_repo.return_value = repo

        resp = client.get("/api/v1/history")
        body = resp.json()
        assert body["total"] == 1
        assert len(body["entries"]) == 1
        assert body["entries"][0]["question"] == "Combien ?"

    @patch("api.routers.history._get_repo")
    def test_pagination_params(self, mock_get_repo, client):
        repo = MagicMock()
        repo.list_recent.return_value = []
        repo.count.return_value = 0
        mock_get_repo.return_value = repo

        client.get("/api/v1/history?limit=5&offset=10")
        # Vérifier que les params sont propagés
        repo.list_recent.assert_called_with(limit=5, offset=10)

    @patch("api.routers.history._get_repo")
    def test_rejects_negative_limit(self, mock_get_repo, client):
        """ge=1 dans le schéma → 422 si limit ≤ 0."""
        resp = client.get("/api/v1/history?limit=0")
        assert resp.status_code == 422

    @patch("api.routers.history._get_repo")
    def test_history_detail_returns_404_when_not_found(self, mock_get_repo, client):
        repo = MagicMock()
        repo.get_by_id.return_value = None
        mock_get_repo.return_value = repo

        resp = client.get("/api/v1/history/9999")
        assert resp.status_code == 404

    @patch("api.routers.history._get_repo")
    def test_history_detail_returns_full_entry(self, mock_get_repo, client):
        repo = MagicMock()
        repo.get_by_id.return_value = {
            "id": 1,
            "question": "test",
            "sql": "SELECT 1",
            "success": True,
            "rag_context": {"sql_examples": [], "knowledge": []},
        }
        mock_get_repo.return_value = repo

        resp = client.get("/api/v1/history/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["rag_context"] is not None

    @patch("api.routers.history._get_repo")
    def test_clear_history(self, mock_get_repo, client):
        repo = MagicMock()
        repo.clear.return_value = 42
        mock_get_repo.return_value = repo

        resp = client.delete("/api/v1/history")
        assert resp.status_code == 200
        body = resp.json()
        assert "42" in body["message"]