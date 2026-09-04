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


def test_streamable_mcp_mount_get_and_post(monkeypatch):
    from contextlib import asynccontextmanager
    from fastmcp import FastMCP
    from app import mcp_auth_middleware

    monkeypatch.setenv("MCP_AUTH_TOKEN", "super-secret-token")

    test_mcp = FastMCP("test_streamable")
    @test_mcp.tool()
    def ping() -> str:
        return "pong"

    sub = test_mcp.http_app(path="/", transport="streamable-http")

    @asynccontextmanager
    async def sub_lifespan(app: FastAPI):
        async with sub.lifespan(app):
            yield

    app = FastAPI(lifespan=sub_lifespan)
    app.middleware("http")(mcp_auth_middleware)
    app.mount("/mcp", sub)

    with TestClient(app) as client:
        # 1. GET /mcp with ?token= -> returns 400 (Bad Request: Missing session ID per MCP spec, NOT 401 and NOT 405)
        res_get_qp = client.get("/mcp?token=super-secret-token")
        assert res_get_qp.status_code == 400
        assert "Missing session ID" in res_get_qp.text

        # 2. GET /mcp without token -> returns 401
        res_get_no_auth = client.get("/mcp")
        assert res_get_no_auth.status_code == 401

        # 3. POST /mcp with ?token= -> returns 200 (NOT 405)
        init_payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"}
            }
        }
        res_post_qp = client.post("/mcp?token=super-secret-token", json=init_payload)
        assert res_post_qp.status_code == 200
        assert "2024-11-05" in res_post_qp.text

        # 4. POST /mcp with Authorization Bearer header -> returns 200 (NOT 405)
        res_post_hdr = client.post(
            "/mcp",
            headers={"Authorization": "Bearer super-secret-token"},
            json=init_payload
        )
        assert res_post_hdr.status_code == 200

        # 5. POST /mcp without token -> returns 401
        res_post_no_auth = client.post("/mcp", json=init_payload)
        assert res_post_no_auth.status_code == 401


