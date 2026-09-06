import os
import secrets
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import asyncio
from fastmcp.utilities.lifespan import combine_lifespans
import uvicorn

from mcp_server.server import mcp
from api.routes import router as api_router
from api.dashboard import router as dashboard_router
from db.connection import init_pool, close_pool
from core.pm_llm import check_openrouter_health

load_dotenv()

# Create FastMCP Streamable HTTP subapp.
# path="/mcp" means the MCP handler is registered at /mcp inside the subapp.
# The subapp is mounted at "/" so the full path /mcp is preserved end-to-end,
# avoiding the double-prefix stripping bug with path="/" mounted at "/mcp".
mcp_app = mcp.http_app(path="/mcp", transport="streamable-http")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Lifecycle hook for FastAPI to manage the DB connection pool and startup checks."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable must be set")

    print(f"Connecting to database at {db_url.split('@')[-1]}...")
    await init_pool(db_url)
    print("Database connected.")

    # Startup health check: Verify configured OpenRouter free models in background
    asyncio.create_task(check_openrouter_health())

    yield

    print("Closing database connection...")
    await close_pool()


# Create FastAPI application, combining our app lifespan with the MCP subapp lifespan.
# combine_lifespans ensures the MCP session manager task group is properly initialised.
app = FastAPI(
    title="Multi-Agent Orchestrator MCP",
    description="Shared context and quota management for AI coding tools",
    lifespan=combine_lifespans(app_lifespan, mcp_app.lifespan),
)


@app.middleware("http")
async def mcp_auth_middleware(request: Request, call_next):
    """Protect /mcp endpoints — accepts Bearer token header OR ?token= query param."""
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


# Include REST API and dashboard routers
app.include_router(api_router)
app.include_router(dashboard_router)


@app.get("/health", dependencies=[])
async def health_check():
    """Unprotected health check endpoint."""
    return {"status": "ok", "service": "multi-agent-orchestrator"}


# Serve static assets under /static/ (JS, CSS)
app.mount("/static", StaticFiles(directory="static"), name="static_assets")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the dashboard index page at root."""
    return FileResponse("static/index.html")


# Mount FastMCP Streamable HTTP transport at the root of the app.
# The MCP route is /mcp inside the subapp, so GET /mcp and POST /mcp both work.
# This must come LAST so explicit routes above take precedence.
app.mount("/", mcp_app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Multi-Agent Orchestrator on port {port}...")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
