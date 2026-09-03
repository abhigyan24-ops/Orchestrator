from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from db.connection import get_connection
from core.models import Task, TaskStatus
from core.encryption import encrypt_key
from mcp_server.auth import verify_token
from core.task_manager import add_task

# Secure all endpoints in this router
router = APIRouter(
    prefix="/api",
    tags=["dashboard"],
    dependencies=[Depends(verify_token)]
)


class CredentialCreate(BaseModel):
    tool_name: str
    account_label: str
    api_key: str
    sequence_order: int = 1
    tool_type: str = "api_based"


class TaskCreate(BaseModel):
    project_id: str
    title: str
    category: str
    description: Optional[str] = None
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    target_folder: Optional[str] = None


@router.get("/credentials")
async def get_credentials():
    """Get all configured credentials (without exposing the raw encrypted api_key)."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT id, tool_name, account_label, sequence_order, status, tool_type FROM api_credentials ORDER BY tool_name, sequence_order"
        )
        return [dict(r) for r in rows]


@router.post("/credentials")
async def add_credential(cred: CredentialCreate):
    """Add a new API credential."""
    encrypted_key = encrypt_key(cred.api_key)
    async with get_connection() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO api_credentials (tool_name, account_label, api_key, sequence_order, status, tool_type)
                VALUES ($1, $2, $3, $4, 'available', $5)
                """,
                cred.tool_name, cred.account_label, encrypted_key, cred.sequence_order, cred.tool_type
            )
            return {"status": "success", "message": f"Credential for {cred.tool_name} added successfully."}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/credentials/{cred_id}")
async def delete_credential(cred_id: int):
    """Delete a credential by ID."""
    async with get_connection() as conn:
        await conn.execute("DELETE FROM api_credentials WHERE id = $1", cred_id)
        return {"status": "success"}


@router.get("/tasks")
async def get_tasks():
    """Get all tasks for the dashboard."""
    async with get_connection() as conn:
        rows = await conn.fetch("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")
        return [dict(r) for r in rows]


@router.post("/tasks")
async def create_new_task(task: TaskCreate):
    """Manually create a new task (e.g., from the dashboard)."""
    try:
        new_task = await add_task(
            project_id=task.project_id,
            title=task.title,
            category=task.category,
            description=task.description,
            repo_url=task.repo_url,
            branch=task.branch,
            target_folder=task.target_folder
        )
        return {"status": "success", "task": new_task.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
