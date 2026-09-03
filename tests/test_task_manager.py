import pytest
from asyncpg import Connection
from datetime import datetime, timezone, timedelta

from core.task_manager import pick_tool, get_next_task, report_progress, add_task, retry_waiting_tasks
from core.quota_tracker import get_quota_status
from core.models import TaskStatus, QuotaState
from core.encryption import encrypt_key


@pytest.mark.asyncio
async def test_task_assigned_completed_unblocks_dependent(db_conn: Connection):
    """Test standard flow: pick tool, get task, complete, unblock dependent."""
    # 1. Add tasks
    task1 = await add_task("test_proj", "Task 1", "frontend", conn=db_conn)
    task2 = await add_task("test_proj", "Task 2", "frontend", depends_on=task1.id, conn=db_conn)
    
    assert task1.status == TaskStatus.READY
    assert task2.status == TaskStatus.BLOCKED

    # 2. Assign task1
    t, m = await pick_tool("frontend", conn=db_conn)
    assert t == "antigravity"
    assert m == "gemini-2.5-pro"
    
    assigned_task1 = await get_next_task("test_proj", t, m, conn=db_conn)
    assert assigned_task1.id == task1.id
    assert assigned_task1.status == TaskStatus.IN_PROGRESS
    assert assigned_task1.assigned_tool == t

    # 3. Report progress success
    msg = await report_progress(assigned_task1.id, success=True, summary="Done", conn=db_conn)
    assert "marked done" in msg
    assert "Dependents unblocked" in msg

    # 4. Verify DB state
    db_task1 = await db_conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task1.id)
    db_task2 = await db_conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task2.id)
    
    assert db_task1['status'] == 'done'
    assert db_task2['status'] == 'ready'


@pytest.mark.asyncio
async def test_quota_exhaustion_api_based(db_conn: Connection):
    """Test quota exhaustion with an API-based tool, expecting rotation message."""
    # Insert api_credentials for antigravity
    await db_conn.execute(
        """
        INSERT INTO api_credentials (tool_name, account_label, api_key, sequence_order, status, tool_type)
        VALUES 
        ('antigravity', 'acc1', $1, 1, 'available', 'api_based'),
        ('antigravity', 'acc2', $1, 2, 'available', 'api_based')
        """,
        encrypt_key("fake-key")
    )
    
    task1 = await add_task("test_proj", "Task 1", "frontend", conn=db_conn)
    t, m = await pick_tool("frontend", conn=db_conn)
    assigned = await get_next_task("test_proj", t, m, conn=db_conn)
    
    # Report quota exceeded
    msg = await report_progress(assigned.id, success=False, summary="", quota_exceeded=True, conn=db_conn)
    
    # Should say it switched
    assert "Switched antigravity to acc2" in msg
    
    # Task should be waiting_quota
    db_task1 = await db_conn.fetchrow("SELECT status, assigned_tool FROM tasks WHERE id = $1", task1.id)
    assert db_task1['status'] == 'waiting_quota'
    assert db_task1['assigned_tool'] is None


@pytest.mark.asyncio
async def test_quota_exhaustion_ide_native(db_conn: Connection):
    """Test quota exhaustion with IDE-native (or missing api_credentials), expecting wait message."""
    task1 = await add_task("test_proj", "Task 1", "frontend", conn=db_conn)
    t, m = await pick_tool("frontend", conn=db_conn)
    assigned = await get_next_task("test_proj", t, m, conn=db_conn)
    
    # Report quota exceeded (no api_credentials inserted)
    msg = await report_progress(assigned.id, success=False, summary="", quota_exceeded=True, reset_hint_hours=12.0, conn=db_conn)
    
    # Should say log into different account or wait
    assert "Log into a different account for antigravity, or wait ~12.0h" in msg
    
    # Quota should be marked exhausted
    q = await get_quota_status(t, m, conn=db_conn)
    assert q.status == QuotaState.EXHAUSTED


@pytest.mark.asyncio
async def test_tool_fallback_cascade(db_conn: Connection):
    """Test that pick_tool cascades through priorities as quotas exhaust."""
    # Priority 1: antigravity/pro
    # Priority 2: antigravity/flash
    # Priority 3: cursor
    
    t1, m1 = await pick_tool("frontend", conn=db_conn)
    assert t1 == "antigravity" and m1 == "gemini-2.5-pro"
    
    # Mark Pro exhausted
    await db_conn.execute("UPDATE quota_status SET status = 'exhausted' WHERE tool_name = $1 AND model_name = $2", t1, m1)
    
    t2, m2 = await pick_tool("frontend", conn=db_conn)
    assert t2 == "antigravity" and m2 == "gemini-2.5-flash"
    
    # Mark Flash exhausted
    await db_conn.execute("UPDATE quota_status SET status = 'exhausted' WHERE tool_name = $1 AND model_name = $2", t2, m2)
    
    t3, m3 = await pick_tool("frontend", conn=db_conn)
    assert t3 == "cursor" and m3 == ""


@pytest.mark.asyncio
async def test_retry_waiting_tasks(db_conn: Connection):
    """Test that retry_waiting_tasks repromotes tasks if a tool becomes available."""
    task1 = await add_task("test_proj", "Task 1", "frontend", conn=db_conn)
    
    # Mark everything exhausted so there's no fallback
    await db_conn.execute("UPDATE quota_status SET status = 'exhausted'")
    
    # Update task to waiting_quota directly to simulate
    await db_conn.execute("UPDATE tasks SET status = 'waiting_quota' WHERE id = $1", task1.id)
    
    promoted = await retry_waiting_tasks("test_proj", conn=db_conn)
    assert promoted == 0
    
    # Recover one quota
    await db_conn.execute("UPDATE quota_status SET status = 'available' WHERE tool_name = 'cursor'")
    
    promoted2 = await retry_waiting_tasks("test_proj", conn=db_conn)
    assert promoted2 == 1
    
    db_task1 = await db_conn.fetchrow("SELECT status FROM tasks WHERE id = $1", task1.id)
    assert db_task1['status'] == 'ready'
