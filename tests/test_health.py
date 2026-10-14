import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from nexusai.core.config import Settings
from nexusai.core.logging import SafeJSONFormatter
from nexusai.database.health import check_database
from nexusai.main import create_app


def settings():
    return Settings(_env_file=None, database_url=None, analytics_database_url=None)


def test_liveness_and_unconfigured_readiness():
    with TestClient(create_app(settings())) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["database"] == "not_configured"
        UUID(response.headers["x-request-id"])


def test_readiness_success(monkeypatch):
    monkeypatch.setattr("nexusai.main.check_database", lambda engine: "ready")
    with TestClient(create_app(settings())) as client:
        assert client.get("/health/ready").status_code == 200


def test_database_error_is_sanitized():
    class BrokenEngine:
        def connect(self):
            raise OperationalError("SELECT secret", {}, Exception("password=private"))

    assert check_database(BrokenEngine()) == "unavailable"


@pytest.mark.parametrize(
    "revision,expected",
    [
        ([], "migration_required"),
        (["future"], "migration_required"),
        (["0002_documents"], "ready"),
    ],
)
def test_schema_revision_gate(revision, expected):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, statement):
            return self

        def scalars(self):
            return revision

    class Engine:
        def connect(self):
            return Connection()

    assert check_database(Engine()) == expected


def test_request_ids_and_not_found():
    with TestClient(create_app(settings())) as client:
        identifier = "6348dadc-2380-4ec6-9f96-ff6e836231b1"
        response = client.get("/missing", headers={"X-Request-ID": identifier})
        assert response.status_code == 404
        assert response.json() == {"error": "not_found", "request_id": identifier}
        invalid = client.get("/health/live", headers={"X-Request-ID": "unsafe-value"})
        UUID(invalid.headers["x-request-id"])


def test_internal_errors_do_not_leak():
    app = create_app(settings())

    @app.get("/test-error")
    def fail():
        raise RuntimeError("password=private")

    with TestClient(app) as client:
        response = client.get("/test-error")
        assert response.status_code == 500
        assert "private" not in response.text
        assert response.json()["error"] == "internal_error"


def test_validation_does_not_echo_input():
    app = create_app(settings())

    @app.get("/test-input")
    def typed_input(count: int):
        return count

    with TestClient(app) as client:
        response = client.get("/test-input?count=password-private")
        assert response.status_code == 422
        assert "password-private" not in response.text


def test_settings_reject_non_postgres_and_mask_password():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="sqlite:///test.db")
    configuration = Settings(
        _env_file=None, database_url="postgresql+psycopg://u:private@localhost/nexusai"
    )
    assert "private" not in repr(configuration)


def test_log_formatter_allowlists_fields():
    record = logging.LogRecord("test", logging.ERROR, "", 1, "password=private", (), None)
    record.event = "request_completed"
    record.request_id = "safe-id"
    result = SafeJSONFormatter().format(record)
    assert "private" not in result
    assert json.loads(result)["event"] == "request_completed"


def test_openapi_only_exposes_implemented_routes():
    with TestClient(create_app(settings())) as client:
        assert set(client.get("/openapi.json").json()["paths"]) == {
            "/health",
            "/health/live",
            "/health/ready",
            "/documents/upload",
            "/documents",
            "/documents/search",
            "/documents/{document_id}/chunks",
            "/jobs/{job_id}",
            "/jobs/{job_id}/retry",
            "/index/status",
            "/rag/query",
            "/rag/citations/{chunk_id}",
        }
