import os
import secrets
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

from db.connection import get_connection

router = APIRouter(tags=["dashboard"])
security = HTTPBasic()

# Jinja2 template directory
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def verify_dashboard_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Constant-time HTTP Basic Auth verification for dashboard endpoints."""
    expected_username = os.environ.get("DASHBOARD_USERNAME", "admin")
    expected_password = os.environ.get("DASHBOARD_PASSWORD", "orchestrator_secret")

    is_username_correct = secrets.compare_digest(
        credentials.username.encode("utf8"), expected_username.encode("utf8")
    )
    is_password_correct = secrets.compare_digest(
        credentials.password.encode("utf8"), expected_password.encode("utf8")
    )

    if not (is_username_correct and is_password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def format_relative_time(dt: Optional[datetime]) -> str:
    """Format a future or past datetime into human-readable relative time (e.g. 'in 22h 14m')."""
    if not dt:
        return "None"
    
    # Ensure timezone awareness
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    diff = (dt - now).total_seconds()
    
    if diff <= 0:
        return "Expired"
    
    hours = int(diff // 3600)
    minutes = int((diff % 3600) // 60)
    
    if hours > 0:
        return f"in {hours}h {minutes}m"
    elif minutes > 0:
        return f"in {minutes}m"
    else:
        return "in <1m"


async def fetch_dashboard_payload() -> Dict[str, Any]:
    """Fetch read-only snapshot of tasks, quota status, and recent activity log."""
    async with get_connection() as conn:
        # 1. Fetch all tasks
        task_rows = await conn.fetch("""
            SELECT id, project_id, title, category, status, depends_on, 
                   assigned_tool, assigned_model, updated_at
            FROM tasks
            ORDER BY id ASC
        """)
        
        tasks = []
        for r in task_rows:
            d = dict(r)
            updated_at = d.get("updated_at")
            d["updated_at"] = updated_at.isoformat() if updated_at else None
            d["updated_at_str"] = updated_at.strftime("%Y-%m-%d %H:%M:%S UTC") if updated_at else ""
            tasks.append(d)

        # 2. Fetch quota status table
        quota_rows = await conn.fetch("""
            SELECT tool_name, model_name, status, last_checked, reset_at, notes
            FROM quota_status
            ORDER BY tool_name ASC, model_name ASC
        """)
        
        quotas = []
        for r in quota_rows:
            d = dict(r)
            reset_at = d.get("reset_at")
            d["reset_at_human"] = format_relative_time(reset_at)
            d["reset_at_str"] = reset_at.strftime("%Y-%m-%d %H:%M:%S UTC") if reset_at else "—"
            d["reset_at"] = reset_at.isoformat() if reset_at else None
            last_checked = d.get("last_checked")
            d["last_checked_str"] = last_checked.strftime("%Y-%m-%d %H:%M:%S UTC") if last_checked else "—"
            d["last_checked"] = last_checked.isoformat() if last_checked else None
            quotas.append(d)

        # 3. Fetch recent 20 activity logs
        log_rows = await conn.fetch("""
            SELECT id, tool_name, model_name, task_id, event, timestamp
            FROM quota_log
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        
        logs = []
        for r in log_rows:
            d = dict(r)
            ts = d.get("timestamp")
            d["timestamp_str"] = ts.strftime("%Y-%m-%d %H:%M:%S UTC") if ts else ""
            d["timestamp"] = ts.isoformat() if ts else None
            logs.append(d)

        return {
            "tasks": tasks,
            "quotas": quotas,
            "logs": logs,
            "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        }


@router.get("/dashboard", dependencies=[Depends(verify_dashboard_auth)])
async def get_dashboard_html(request: Request, user: str = Depends(verify_dashboard_auth)):
    """Main read-only dashboard web page."""
    data = await fetch_dashboard_payload()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "data": data
        }
    )


@router.get("/dashboard/data", dependencies=[Depends(verify_dashboard_auth)])
async def get_dashboard_json(user: str = Depends(verify_dashboard_auth)):
    """JSON endpoint polled every 5 seconds by the dashboard UI."""
    data = await fetch_dashboard_payload()
    return JSONResponse(content=data)
