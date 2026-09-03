import json
from mcp_server.server import mcp
from core import task_manager
from core import context_manager


@mcp.tool()
async def get_next_task(project_id: str, tool_name: str, model_name: str = "") -> str:
    """
    Fetch the next available task for this project that matches your tool/model's capabilities.
    Returns a JSON string of the task details, or a message indicating no tasks are ready.
    """
    task = await task_manager.get_next_task(project_id, tool_name, model_name)
    if not task:
        return json.dumps({"message": f"No ready tasks found for {tool_name} ({model_name}) on project {project_id}."})
    
    return task.model_dump_json()


@mcp.tool()
async def report_task_progress(
    task_id: int, 
    success: bool, 
    summary: str, 
    quota_exceeded: bool = False, 
    raw_response: str = "",
    reset_hint_hours: float = 24.0
) -> str:
    """
    Report the completion, failure, or quota exhaustion for a specific task.
    If success=True, dependent tasks will be unblocked.
    If quota_exceeded=True, the orchestrator will handle auto-rotation or queue stalling.
    """
    result_msg = await task_manager.report_progress(
        task_id, success, summary, quota_exceeded, raw_response, reset_hint_hours
    )
    return result_msg


@mcp.tool()
async def create_task(
    project_id: str, 
    title: str, 
    category: str, 
    description: str = "", 
    depends_on: int = None, 
    repo_url: str = None, 
    branch: str = None, 
    target_folder: str = None, 
    base_branch: str = "main"
) -> str:
    """
    Add a new task to the orchestrator queue.
    If depends_on is provided, this task will be BLOCKED until the dependent task succeeds.
    """
    task = await task_manager.add_task(
        project_id, title, category, description, depends_on, repo_url, branch, target_folder, base_branch
    )
    return task.model_dump_json()


@mcp.tool()
async def get_project_context(project_id: str) -> str:
    """
    Retrieve the shared project context, including architecture, progress logs, and handoff notes.
    """
    ctx = await context_manager.get_context(project_id)
    if not ctx:
        return json.dumps({"message": "No context found for this project."})
    return ctx.model_dump_json()


@mcp.tool()
async def update_project_context(
    project_id: str, 
    architecture: str = None, 
    progress_log: str = None, 
    handoff_notes: str = None
) -> str:
    """
    Update specific fields in the shared project context. Only fields provided will be updated.
    """
    ctx = await context_manager.upsert_context(project_id, architecture, progress_log, handoff_notes)
    return ctx.model_dump_json()


@mcp.tool()
async def retry_waiting_tasks(project_id: str) -> str:
    """
    Checks all 'waiting_quota' tasks for a project and re-promotes them to 'ready'
    if quota or fallback tools have become available.
    """
    promoted = await task_manager.retry_waiting_tasks(project_id)
    return json.dumps({"promoted_count": promoted, "message": f"Promoted {promoted} task(s) back to ready."})


@mcp.tool()
async def list_tasks(project_id: str = "", status: str = "", limit: int = 50) -> str:
    """
    List tasks in the orchestrator board, optionally filtered by project_id and/or status.
    Returns a JSON list of tasks.
    """
    tasks = await task_manager.list_tasks(project_id=project_id or None, status=status or None, limit=limit)
    return json.dumps([t.model_dump() for t in tasks], default=str)

