import pytest
import os
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient
from mcp_server.auth import verify_token

@pytest.fixture
def auth_test_app(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "super-secret-token")
    app = FastAPI()

    @app.get("/protected")
    async def protected_route(token: str = Depends(verify_token)):
        return {"authenticated": True, "token": token}

    return app


def test_auth_valid_bearer_header(auth_test_app):
    client = TestClient(auth_test_app)
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer super-secret-token"}
    )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "token": "super-secret-token"}


def test_auth_invalid_bearer_header(auth_test_app):
    client = TestClient(auth_test_app)
    response = client.get(
        "/protected",
        headers={"Authorization": "Bearer wrong-token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid auth token"


def test_auth_valid_query_param(auth_test_app):
    client = TestClient(auth_test_app)
    response = client.get("/protected?token=super-secret-token")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "token": "super-secret-token"}


def test_auth_invalid_query_param(auth_test_app):
    client = TestClient(auth_test_app)
    response = client.get("/protected?token=invalid-query-token")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid auth token"


def test_auth_missing_token(auth_test_app):
    client = TestClient(auth_test_app)
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or invalid token"


def test_auth_missing_server_config(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    app = FastAPI()

    @app.get("/protected")
    async def protected_route(token: str = Depends(verify_token)):
        return {"authenticated": True}

    client = TestClient(app)
    response = client.get("/protected?token=some-token")
    assert response.status_code == 401
    assert response.json()["detail"] == "MCP_AUTH_TOKEN not configured on server"


def test_mcp_middleware_query_param(monkeypatch):
    from app import mcp_auth_middleware
    monkeypatch.setenv("MCP_AUTH_TOKEN", "super-secret-token")
    
    app = FastAPI()
    app.middleware("http")(mcp_auth_middleware)

    @app.get("/mcp/test")
    async def mcp_test_endpoint():
        return {"status": "ok"}

    client = TestClient(app)
    
    # Query param valid
    res_qp = client.get("/mcp/test?token=super-secret-token")
    assert res_qp.status_code == 200
    assert res_qp.json() == {"status": "ok"}

    # Bearer header valid
    res_hdr = client.get("/mcp/test", headers={"Authorization": "Bearer super-secret-token"})
    assert res_hdr.status_code == 200
    assert res_hdr.json() == {"status": "ok"}

    # Query param invalid
    res_bad_qp = client.get("/mcp/test?token=wrong-token")
    assert res_bad_qp.status_code == 401

    # Missing token
    res_missing = client.get("/mcp/test")
    assert res_missing.status_code == 401

