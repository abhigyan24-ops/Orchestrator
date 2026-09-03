# Multi-Agent Orchestrator MCP

A free, self-hosted MCP server that acts as a shared "brain" for coordinating multiple AI coding tools (Antigravity, Cursor, Kiro, Claude, Codex) on a single project.

It assigns tasks to the right tool based on capabilities, tracks progress, remembers context across sessions, and gracefully handles free-tier quota limits (including API key rotation and tool fallbacks) without losing work.

## Core Features

- **Context Memory:** Centralized project architecture and progress logs (`context_manager.py`).
- **Division of Labor:** Priority-based tool selection (`tool_skills` table) to assign frontend to Cursor, backend to Antigravity, etc.
- **Quota & Credential Management:** Tracks limits per `(tool, model)` and auto-rotates API keys using Fernet encryption (`quota_tracker.py`, `credential_manager.py`).
- **Task Pipeline:** Fully asynchronous task assignment with dependency blocking and automatic unblocking (`task_manager.py`).
- **Live Web Dashboard:** Read-only web dashboard at `/dashboard` displaying real-time task boards (grouped by project and status), tool quota tracking, and recent activity logs with auto-refresh every 5 seconds. Secured via HTTP Basic Auth (`DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`).


## Tech Stack

- **Server:** FastAPI + FastMCP (SSE Transport)
- **Database:** PostgreSQL (via `asyncpg`)
- **Security:** Bearer Token Auth + Fernet Encryption

## Local Development Setup

1. **Clone the repository.**
2. **Set up the virtual environment:**
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   pip install -r requirements.txt
   ```
3. **Configure the environment:**
   Copy `.env.example` to `.env` and fill in your values.
   ```bash
   cp .env.example .env
   ```
   *Make sure to generate a secure `ENCRYPTION_KEY` using the cryptography library.*

4. **Start PostgreSQL via Docker:**
   ```bash
   docker compose up -d
   ```

5. **Verify the database schema:**
   ```bash
   python verify_schema.py
   ```

6. **Run the server:**
   ```bash
   uvicorn app:app --reload
   ```
   The MCP SSE endpoint will be available at `http://localhost:8000/mcp`.

## Running Tests

Tests run against a real Postgres instance defined by `TEST_DATABASE_URL` in `.env`.

```bash
pytest tests/ -v
```

## Deployment (Render.com)

1. Create a **PostgreSQL** instance on Render.
2. Create a **Web Service** tied to your repository.
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables:**
   - `DATABASE_URL` (Internal DB URL provided by Render)
   - `ENCRYPTION_KEY`
   - `MCP_AUTH_TOKEN`
   - `DASHBOARD_USERNAME` (HTTP Basic Auth username for `/dashboard`)
   - `DASHBOARD_PASSWORD` (HTTP Basic Auth password for `/dashboard`)

Render handles routing and SSL termination.

## Connecting AI Agents to the Orchestrator

In your AI tool's MCP configuration (e.g., Cursor, Claude Desktop), configure an SSE connection pointing to your deployed URL.

**Example `mcp.json`:**
```json
{
  "mcpServers": {
    "Orchestrator": {
      "command": "node",
      "args": ["@modelcontextprotocol/client-sse", "https://your-app.onrender.com/mcp"],
      "env": {
        "Authorization": "Bearer YOUR_MCP_AUTH_TOKEN"
      }
    }
  }
}
```
*(Note: Client configuration varies by agent. FastMCP natively supports SSE transports.)*
