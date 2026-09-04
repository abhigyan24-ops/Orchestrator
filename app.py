import os
import secrets
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from mcp_server.server import mcp
from api.routes import router as api_router
from api.dashboard import router as dashboard_router
from db.connection import init_pool, close_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle hook for FastAPI to manage the DB connection pool."""
    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable must be set")
    
    print(f"Connecting to database at {db_url.split('@')[-1]}...")
    await init_pool(db_url)
    print("Database connected.")
    
    yield
    
    print("Closing database connection...")
    await close_pool()


# Create FastAPI application
app = FastAPI(
    title="Multi-Agent Orchestrator MCP",
    description="Shared context and quota management for AI coding tools",
    lifespan=lifespan
)

@app.middleware("http")
async def mcp_auth_middleware(request: Request, call_next):
    """Simple middleware to protect /mcp endpoints."""
    if request.url.path.startswith("/mcp"):
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif "token" in request.query_params:
            token = request.query_params.get("token")

        if not token:
            return JSONResponse({"detail": "Missing or invalid token"}, status_code=401)
        
        expected_token = os.environ.get("MCP_AUTH_TOKEN")
        if not expected_token or not secrets.compare_digest(token, expected_token):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            
    return await call_next(request)

# Include the dashboard API and read-only web dashboard
app.include_router(api_router)
app.include_router(dashboard_router)


@app.get("/health", dependencies=[])
async def health_check():
    """Unprotected health check endpoint."""
    return {"status": "ok", "service": "multi-agent-orchestrator"}


@app.get("/mcp")
@app.get("/mcp/")
async def mcp_redirect():
    """Redirect /mcp to /mcp/sse for SSE clients."""
    return RedirectResponse(url="/mcp/sse", status_code=307)


# Mount FastMCP SSE transport
if hasattr(mcp, "http_app"):
    mcp_subapp = mcp.http_app(transport="sse")
    app.mount("/mcp", mcp_subapp)
elif hasattr(mcp, "add_to_fastapi"):
    mcp.add_to_fastapi(app, prefix="/mcp")
else:
    starlette_app = getattr(mcp, "app", None) or getattr(mcp, "_app", None)
    if starlette_app:
        app.mount("/mcp", starlette_app)


# Mount the static dashboard at the root
app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Multi-Agent Orchestrator on port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
