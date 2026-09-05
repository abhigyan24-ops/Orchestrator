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


class PlanFeatureRequest(BaseModel):
    project_id: str
    feature_description: str
    repo_url: str

DEFAULT_USER_ID = "owner"

@router.get("/credentials")
async def get_credentials():
    """Get all configured credentials for current user (without exposing the raw encrypted api_key)."""
    async with get_connection() as conn:
        rows = await conn.fetch(
            "SELECT id, tool_name, account_label, sequence_order, status, tool_type, user_id FROM api_credentials WHERE user_id = $1 ORDER BY tool_name, sequence_order",
            DEFAULT_USER_ID
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
                INSERT INTO api_credentials (tool_name, account_label, api_key, sequence_order, status, tool_type, user_id)
                VALUES ($1, $2, $3, $4, 'available', $5, $6)
                """,
                cred.tool_name, cred.account_label, encrypted_key, cred.sequence_order, cred.tool_type, DEFAULT_USER_ID
            )
            return {"status": "success", "message": f"Credential for {cred.tool_name} added successfully."}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


@router.delete("/credentials/{cred_id}")
async def delete_credential(cred_id: int):
    """Delete a credential by ID."""
    async with get_connection() as conn:
        await conn.execute("DELETE FROM api_credentials WHERE id = $1 AND user_id = $2", cred_id, DEFAULT_USER_ID)
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


import uuid
import asyncio

planning_jobs = {}

async def background_plan_feature(job_id: str, req: PlanFeatureRequest):
    try:
        from core import pm_llm, context_manager
        
        ctx = await context_manager.get_context(req.project_id)
        ctx_str = ctx.model_dump_json() if ctx else ""
        
        # Run the synchronous LLM call in a thread to not block the event loop
        tasks_plan = await asyncio.to_thread(pm_llm.decompose_feature, req.project_id, req.feature_description, ctx_str)
        
        if not tasks_plan:
            planning_jobs[job_id] = {"status": "failed", "error": "Failed to generate task plan (empty)."}
            return
            
        created_task_ids = {} # map title -> db id
        
        for t in tasks_plan:
            dep_title = t.get("depends_on")
            dep_id = created_task_ids.get(dep_title) if dep_title else None
            
            ac = t.get("acceptance_criteria", "")
            if isinstance(ac, list):
                ac = "\n".join([f"- {item}" for item in ac])
                
            brief = t.get("brief", "")
            if isinstance(brief, list):
                brief = "\n".join(brief)
            
            db_task = await add_task(
                project_id=req.project_id,
                title=t.get("title", "Untitled Task"),
                category=t.get("category", "boilerplate"),
                brief=brief,
                acceptance_criteria=ac,
                complexity_score=t.get("complexity_score", 1),
                depends_on=dep_id,
                repo_url=req.repo_url
            )
            created_task_ids[db_task.title] = db_task.id
            
        planning_jobs[job_id] = {"status": "completed"}
    except Exception as e:
        print(f"Background planning failed: {e}")
        planning_jobs[job_id] = {"status": "failed", "error": str(e)}

@router.post("/plan_feature")
async def api_plan_feature(req: PlanFeatureRequest):
    """Start the AI PM to generate a list of tasks in the background."""
    job_id = str(uuid.uuid4())
    planning_jobs[job_id] = {"status": "processing"}
    
    asyncio.create_task(background_plan_feature(job_id, req))
    
    return {"status": "processing", "job_id": job_id}

@router.get("/plan_feature/{job_id}")
async def get_plan_feature_status(job_id: str):
    """Poll the status of a planning job."""
    if job_id not in planning_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return planning_jobs[job_id]

class SwarmToggle(BaseModel):
    enabled: bool

@router.post("/swarm/toggle")
async def toggle_swarm(req: SwarmToggle):
    """Start or stop the autonomous Agent Swarm."""
    from core.task_manager import set_swarm_status
    set_swarm_status(req.enabled)
    return {"status": "success", "swarm_enabled": req.enabled}

@router.get("/swarm/status")
async def get_swarm_status():
    """Get the current state of the Swarm."""
    from core.task_manager import get_swarm_status
    return {"swarm_enabled": get_swarm_status()}


@router.post("/tasks/retry_failed")
async def retry_failed_tasks():
    """Reset any failed tasks to ready so the swarm can re-process them."""
    async with get_connection() as conn:
        res = await conn.execute(
            "UPDATE tasks SET status = 'ready', assigned_tool = NULL WHERE status = 'failed' AND repo_url IS NOT NULL"
        )
        return {"status": "success", "message": res}


@router.post("/tasks/{task_id}/done")
async def mark_task_done(task_id: int):
    """Mark a task done and unblock its dependents."""
    from core.task_manager import update_task_status
    await update_task_status(task_id, TaskStatus.DONE, assigned_agent="QA Agent")
    return {"status": "success", "message": f"Task #{task_id} marked as done and dependents unblocked."}




