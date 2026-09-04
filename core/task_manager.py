from typing import Optional, Tuple, List
from datetime import datetime, timezone

from asyncpg import Connection

from db.connection import get_connection
from core.models import Task, TaskStatus, QuotaEvent
from core.quota_tracker import get_quota_status, mark_exhausted, log_event
from core.credential_manager import get_next_credential, mark_credential_exhausted


async def pick_tool(category: str, conn: Optional[Connection] = None) -> Tuple[Optional[str], Optional[str]]:
    """Walks tool_skills in priority order for that category, returns the first
    (tool_name, model_name) pair where quota_status shows available.
    """
    async def _execute(c: Connection):
        skills = await c.fetch(
            """
            SELECT tool_name, model_name 
            FROM tool_skills 
            WHERE task_category = $1 
            ORDER BY priority ASC
            """,
            category
        )
        for skill in skills:
            tool_name = skill['tool_name']
            model_name = skill['model_name']
            
            # get_quota_status auto-recovers if reset_at has passed
            status = await get_quota_status(tool_name, model_name, conn=c)
            # If there's no row, we assume it's available by default
            if not status or status.status == 'available':
                return tool_name, model_name
                
        return None, None

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def get_next_task(
    project_id: str, tool_name: str, available_models: List[str] = None, conn: Optional[Connection] = None
) -> Optional[Task]:
    """Returns the oldest task with status='ready' and assigned_tool IS NULL for that project.
    If model_name is given, ensures the category matches tool_skills.
    Marks it in_progress.
    """
    async def _execute(c: Connection):
        # Determine capability tier of available models
        # Tier 5: Frontier/Pro, Tier 4: Sonnet, Tier 2: Flash/Mini/Haiku, Tier 1: Basic
        max_tier = 1
        assigned_model = ""
        if available_models:
            assigned_model = available_models[0] # Record the primary one being used
            for m in available_models:
                m_lower = m.lower()
                if "pro" in m_lower or "opus" in m_lower or "4o" in m_lower or "4.6" in m_lower or "o1" in m_lower or "o3" in m_lower:
                    tier = 5
                elif "sonnet" in m_lower:
                    tier = 4
                elif "flash" in m_lower or "haiku" in m_lower or "mini" in m_lower:
                    tier = 2
                else:
                    tier = 1
                max_tier = max(max_tier, tier)
        else:
            max_tier = 5 # If not specified, assume capable of anything

        # Find the oldest ready task matching capability
        query = f"""
            SELECT id 
            FROM tasks 
            WHERE project_id = $1 AND status = 'ready' AND assigned_tool IS NULL 
            AND complexity_score <= $2
            ORDER BY created_at ASC 
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """
        args = [project_id, max_tier]

        row = await c.fetchrow(query, *args)
        if not row:
            return None

        task_id = row['id']
        
        # Mark in_progress
        updated = await c.fetchrow(
            """
            UPDATE tasks 
            SET status = 'in_progress', assigned_tool = $1::text, assigned_model = $2::text, updated_at = NOW()
            WHERE id = $3
            RETURNING *
            """,
            tool_name, assigned_model, task_id
        )
        return Task(**dict(updated))

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def report_progress(
    task_id: int, 
    success: bool, 
    summary: str, 
    quota_exceeded: bool = False, 
    raw_response: str = "", 
    model_exhausted: str = "",
    partial_summary: str = "",
    working_branch: str = "",
    reset_hint_hours: float = 24.0,
    conn: Optional[Connection] = None
) -> str:
    """Report progress on a task. Handles success dependency unblocking and quota exhaustion fallback."""
    async def _execute(c: Connection):
        task_row = await c.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        if not task_row:
            return f"Error: Task {task_id} not found."
            
        task = Task(**dict(task_row))
        t_name = task.assigned_tool or "unknown"
        m_name = task.assigned_model or ""

        if success:
            await c.execute(
                """
                UPDATE tasks 
                SET status = 'done', result_summary = $1, updated_at = NOW() 
                WHERE id = $2
                """,
                summary, task_id
            )
            await log_event(t_name, m_name, QuotaEvent.CALL_SUCCESS, task_id, raw_response, conn=c)
            
            # Unblock dependents
            await c.execute(
                """
                UPDATE tasks 
                SET status = 'ready', updated_at = NOW() 
                WHERE depends_on = $1 AND status = 'blocked'
                """,
                task_id
            )
            return f"Task {task_id} marked done. Dependents unblocked."

        elif quota_exceeded:
            await c.execute(
                """
                UPDATE tasks 
                SET status = 'waiting_quota', assigned_tool = NULL, assigned_model = NULL, updated_at = NOW(),
                    partial_summary = COALESCE($2, partial_summary), working_branch = COALESCE($3, working_branch)
                WHERE id = $1
                """,
                task_id, partial_summary or None, working_branch or None
            )
            exhausted_model = model_exhausted or m_name
            await mark_exhausted(t_name, exhausted_model, reset_hint_hours, conn=c)
            await log_event(t_name, exhausted_model, QuotaEvent.QUOTA_EXCEEDED, task_id, raw_response, conn=c)
            
            # Determine tool type and fallback message
            tool_row = await c.fetchrow("SELECT tool_type FROM api_credentials WHERE tool_name = $1 LIMIT 1", t_name)
            tool_type = tool_row['tool_type'] if tool_row else 'ide_native'

            if tool_type == 'api_based':
                # Mark current active credential as exhausted
                curr_cred_row = await c.fetchrow(
                    "SELECT id, account_label FROM api_credentials WHERE tool_name = $1 AND status = 'available' ORDER BY sequence_order ASC LIMIT 1",
                    t_name
                )
                if curr_cred_row:
                    await mark_credential_exhausted(curr_cred_row['id'], conn=c)
                
                # Check for next credential
                next_cred = await get_next_credential(t_name, conn=c)
                if next_cred:
                    # We have a fallback credential! We also need to recover the model quota so it can be picked again immediately
                    await c.execute("UPDATE quota_status SET status = 'available', reset_at = NULL WHERE tool_name = $1 AND model_name = $2", t_name, m_name)
                    return f"Switched {t_name} to {next_cred.account_label}, continuing silently."
                else:
                    status = await get_quota_status(t_name, m_name, conn=c)
                    reset_time = status.reset_at.strftime("%Y-%m-%d %H:%M:%S UTC") if status and status.reset_at else f"~{reset_hint_hours}h"
                    return f"All API keys exhausted for {t_name}. Earliest reset: {reset_time}. Add a new key or wait."
            else:
                return f"Log into a different account for {t_name}, or wait ~{reset_hint_hours}h, or skip this tool's tasks for now."
                
        else:
            # Generic failure
            await c.execute(
                """
                UPDATE tasks 
                SET status = 'failed', result_summary = $1, updated_at = NOW() 
                WHERE id = $2
                """,
                summary, task_id
            )
            await log_event(t_name, m_name, QuotaEvent.CALL_FAILED, task_id, raw_response, conn=c)
            return f"Task {task_id} failed."

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def add_task(
    project_id: str, 
    title: str, 
    category: str, 
    description: Optional[str] = None, 
    brief: Optional[str] = None,
    acceptance_criteria: Optional[str] = None,
    complexity_score: int = 1,
    depends_on: Optional[int] = None, 
    repo_url: Optional[str] = None, 
    branch: Optional[str] = None, 
    target_folder: Optional[str] = None, 
    base_branch: str = 'main',
    conn: Optional[Connection] = None
) -> Task:
    """Add a new task. Sets status to blocked if depends_on is given, else ready."""
    status = 'blocked' if depends_on else 'ready'
    
    async def _execute(c: Connection):
        # Validate dependency exists if provided
        if depends_on:
            dep_exists = await c.fetchval("SELECT 1 FROM tasks WHERE id = $1", depends_on)
            if not dep_exists:
                raise ValueError(f"Dependency task {depends_on} does not exist.")

        row = await c.fetchrow(
            """
            INSERT INTO tasks (
                project_id, title, category, description, brief, acceptance_criteria, complexity_score, status, 
                depends_on, repo_url, branch, target_folder, base_branch
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            """,
            project_id, title, category, description, brief, acceptance_criteria, complexity_score, status,
            depends_on, repo_url, branch, target_folder, base_branch
        )
        return Task(**dict(row))

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def retry_waiting_tasks(project_id: str, conn: Optional[Connection] = None) -> int:
    """Checks all 'waiting_quota' tasks and re-promotes to 'ready' if pick_tool finds an available fallback.
    Returns number of tasks promoted.
    """
    async def _execute(c: Connection):
        waiting = await c.fetch("SELECT id, category FROM tasks WHERE project_id = $1 AND status = 'waiting_quota'", project_id)
        promoted = 0
        
        for task in waiting:
            t, m = await pick_tool(task['category'], conn=c)
            if t is not None:
                await c.execute("UPDATE tasks SET status = 'ready', updated_at = NOW() WHERE id = $1", task['id'])
                promoted += 1
                
        return promoted

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def get_task(task_id: int, conn: Optional[Connection] = None) -> Optional[Task]:
    """Retrieve a single task by ID."""
    async def _execute(c: Connection):
        row = await c.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        if row:
            return Task(**dict(row))
        return None

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    conn: Optional[Connection] = None
) -> List[Task]:
    """Retrieve tasks with optional filtering by project_id and status."""
    async def _execute(c: Connection):
        clauses = []
        args = []
        if project_id:
            args.append(project_id)
            clauses.append(f"project_id = ${len(args)}")
        if status:
            args.append(status)
            clauses.append(f"status = ${len(args)}")
        
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        args.append(limit)
        query = f"SELECT * FROM tasks {where} ORDER BY id ASC LIMIT ${len(args)}"
        rows = await c.fetch(query, *args)
        return [Task(**dict(r)) for r in rows]

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)

