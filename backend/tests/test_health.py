from app.db import engine
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError


def test_unavailable_database_returns_503(monkeypatch):
    def unavailable():
        raise OperationalError("synthetic-secret", {}, Exception("synthetic-secret"))

    monkeypatch.setattr(engine, "connect", unavailable)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert "synthetic-secret" not in response.text


def test_openapi_and_health_shape():
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        response = client.get("/health")
        assert response.status_code in (200, 503)
        assert "database" in response.json()
