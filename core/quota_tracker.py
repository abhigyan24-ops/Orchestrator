from datetime import datetime, timedelta, timezone
from typing import Optional
import json

from asyncpg import Connection

from db.connection import get_connection
from core.models import QuotaStatus, QuotaState, QuotaEvent


async def get_quota_status(
    tool_name: str, model_name: str, conn: Optional[Connection] = None
) -> Optional[QuotaStatus]:
    """Get the current quota status for a (tool, model) pair. 
    Auto-recovers to AVAILABLE if reset_at has passed.
    """
    async def _execute(c: Connection):
        # Auto-recovery check first
        now = datetime.now(timezone.utc)
        await c.execute(
            """
            UPDATE quota_status 
            SET status = 'available', reset_at = NULL 
            WHERE tool_name = $1 AND model_name = $2 
              AND status = 'exhausted' AND reset_at <= $3
            """,
            tool_name, model_name, now
        )
        
        row = await c.fetchrow(
            """
            SELECT tool_name, model_name, account_label, status, last_checked, reset_at, notes 
            FROM quota_status 
            WHERE tool_name = $1 AND model_name = $2
            """,
            tool_name, model_name
        )
        if row:
            return QuotaStatus(**dict(row))
        return None

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def mark_exhausted(
    tool_name: str, model_name: str, reset_hint_hours: float = 24.0, conn: Optional[Connection] = None
) -> None:
    """Mark a (tool, model) pair as exhausted and set the reset_at time."""
    reset_at = datetime.now(timezone.utc) + timedelta(hours=reset_hint_hours)
    
    async def _execute(c: Connection):
        await c.execute(
            """
            INSERT INTO quota_status (tool_name, model_name, status, reset_at, last_checked)
            VALUES ($1, $2, 'exhausted', $3, NOW())
            ON CONFLICT (tool_name, model_name) DO UPDATE 
            SET status = 'exhausted', reset_at = EXCLUDED.reset_at, last_checked = EXCLUDED.last_checked
            """,
            tool_name, model_name, reset_at
        )

    if conn:
        await _execute(conn)
    else:
        async with get_connection() as c:
            await _execute(c)


async def log_event(
    tool_name: str, 
    model_name: str, 
    event: QuotaEvent, 
    task_id: Optional[int] = None, 
    raw_response: Optional[str] = None, 
    conn: Optional[Connection] = None
) -> None:
    """Append an event to the quota_log."""
    async def _execute(c: Connection):
        await c.execute(
            """
            INSERT INTO quota_log (tool_name, model_name, task_id, event, timestamp, raw_response)
            VALUES ($1, $2, $3, $4, NOW(), $5)
            """,
            tool_name, model_name, task_id, event.value, raw_response
        )

    if conn:
        await _execute(conn)
    else:
        async with get_connection() as c:
            await _execute(c)


async def check_and_recover(conn: Optional[Connection] = None) -> int:
    """Scan all exhausted entries and recover any past their reset_at.
    Returns the number of recovered quotas.
    """
    now = datetime.now(timezone.utc)
    
    async def _execute(c: Connection):
        result = await c.execute(
            """
            UPDATE quota_status 
            SET status = 'available', reset_at = NULL 
            WHERE status = 'exhausted' AND reset_at <= $1
            """,
            now
        )
        # asyncpg execute returns a string like "UPDATE N"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)
