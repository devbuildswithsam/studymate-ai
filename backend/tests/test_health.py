"""Tests for the app skeleton: health check, error shape, CORS. SMA-20."""

from app.config import APP_VERSION


def test_health_returns_status_version_env_and_auth_mode(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": APP_VERSION,
        "env": "test",  # from the overridden settings, not backend/.env
        "auth_mode": "local",
    }


def test_unknown_route_uses_the_error_shape(client):
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


def test_cors_allows_the_frontend_origin(client):
    response = client.get("/api/health", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_ignores_other_origins(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})

    # No header -> the browser refuses to hand the response to that page.
    assert "access-control-allow-origin" not in response.headers
