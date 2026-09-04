import json
from mcp_server.server import mcp
from core import task_manager
from core import context_manager


@mcp.tool()
async def get_next_task(project_id: str, tool_name: str, available_models: list[str] = None) -> str:
    """
    Fetch the next available task for this project that matches your tool's model capabilities.
    Provide available_models (list of strings) to ensure you only get tasks you have quota to handle.
    Returns a JSON string of the task details, or a message indicating no tasks are ready.
    """
    task = await task_manager.get_next_task(project_id, tool_name, available_models)
    if not task:
        return json.dumps({"message": f"No ready tasks found for {tool_name} on project {project_id} matching capability."})
    
    return task.model_dump_json()


@mcp.tool()
async def report_task_progress(
    task_id: int, 
    success: bool, 
    summary: str, 
    quota_exceeded: bool = False, 
    raw_response: str = "",
    model_exhausted: str = "",
    partial_summary: str = "",
    working_branch: str = "",
    reset_hint_hours: float = 24.0
) -> str:
    """
    Report the completion, failure, or quota exhaustion for a specific task.
    If success=True, dependent tasks will be unblocked.
    If quota_exceeded=True, provide model_exhausted, partial_summary, and working_branch to allow seamless handoff to the next available model/agent.
    """
    result_msg = await task_manager.report_progress(
        task_id, success, summary, quota_exceeded, raw_response, 
        model_exhausted, partial_summary, working_branch, reset_hint_hours
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


@mcp.tool()
async def plan_feature(project_id: str, feature_description: str) -> str:
    """
    Use the AI Project Manager to decompose a vague feature request into a dependency-ordered task graph.
    The tasks are automatically added to the queue and returned as JSON.
    """
    from core import pm_llm
    ctx = await context_manager.get_context(project_id)
    ctx_str = ctx.model_dump_json() if ctx else ""
    
    tasks_plan = pm_llm.decompose_feature(project_id, feature_description, ctx_str)
    if not tasks_plan:
        return json.dumps({"error": "Failed to generate task plan."})
        
    created_task_ids = {} # map title -> db id
    results = []
    
    for t in tasks_plan:
        # resolve depends_on
        dep_title = t.get("depends_on")
        dep_id = created_task_ids.get(dep_title) if dep_title else None
        
        db_task = await task_manager.add_task(
            project_id=project_id,
            title=t.get("title", "Untitled Task"),
            category=t.get("category", "boilerplate"),
            brief=t.get("brief", ""),
            acceptance_criteria=t.get("acceptance_criteria", ""),
            complexity_score=t.get("complexity_score", 1),
            depends_on=dep_id
        )
        created_task_ids[db_task.title] = db_task.id
        results.append(db_task.model_dump())
        
    return json.dumps({"tasks_created": len(results), "tasks": results}, default=str)


@mcp.tool()
async def escalate_to_pm(task_id: int, current_state: str, blocker_description: str) -> str:
    """
    Escalate a blocked or confusing task to the AI Project Manager for a strategy pivot.
    Do this BEFORE asking the human user for help. The PM will provide a concrete unblocking strategy.
    """
    from core import pm_llm
    task = await task_manager.get_task(task_id)
    if not task:
        return json.dumps({"error": f"Task {task_id} not found."})
        
    ctx = await context_manager.get_context(task.project_id)
    ctx_str = ctx.model_dump_json() if ctx else ""
    
    strategy = pm_llm.resolve_escalation(
        task_id=task.id, 
        task_brief=task.brief or task.title, 
        current_state=current_state, 
        blocker_description=blocker_description, 
        project_context=ctx_str
    )
    
    return json.dumps({
        "status": "escalation_resolved",
        "strategy_pivot": strategy
    })

