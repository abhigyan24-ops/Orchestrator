import pytest
from asyncpg import Connection
from datetime import datetime, timezone, timedelta

from core.quota_tracker import get_quota_status, mark_exhausted, log_event, check_and_recover
from core.models import QuotaState, QuotaEvent


@pytest.mark.asyncio
async def test_mark_exhausted_and_get_status(db_conn: Connection):
    """Test marking exhausted sets the right state and reset_at, and get_quota_status reads it."""
    # Mark exhausted
    await mark_exhausted("antigravity", "gemini-2.5-pro", reset_hint_hours=2.0, conn=db_conn)
    
    q = await get_quota_status("antigravity", "gemini-2.5-pro", conn=db_conn)
    assert q is not None
    assert q.status == QuotaState.EXHAUSTED
    
    # reset_at should be ~2 hours from now
    now = datetime.now(timezone.utc)
    assert q.reset_at is not None
    diff = (q.reset_at - now).total_seconds() / 3600
    assert 1.9 < diff < 2.1


@pytest.mark.asyncio
async def test_get_quota_auto_recovers(db_conn: Connection):
    """Test that get_quota_status automatically recovers an exhausted quota if reset_at has passed."""
    # Mark exhausted but with a past reset_at
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_conn.execute(
        """
        UPDATE quota_status 
        SET status = 'exhausted', reset_at = $1 
        WHERE tool_name = 'cursor'
        """,
        past
    )
    
    # When we fetch it, it should auto-recover
    q = await get_quota_status("cursor", "", conn=db_conn)
    assert q.status == QuotaState.AVAILABLE
    assert q.reset_at is None


@pytest.mark.asyncio
async def test_check_and_recover(db_conn: Connection):
    """Test bulk recovery script."""
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    
    # Exhaust two, one in past, one in future
    await db_conn.execute("UPDATE quota_status SET status = 'exhausted', reset_at = $1 WHERE tool_name = 'cursor'", past)
    await db_conn.execute("UPDATE quota_status SET status = 'exhausted', reset_at = $1 WHERE tool_name = 'kiro'", future)
    
    recovered = await check_and_recover(conn=db_conn)
    assert recovered == 1
    
    q_cursor = await get_quota_status("cursor", "", conn=db_conn)
    assert q_cursor.status == QuotaState.AVAILABLE
    
    # Get direct from DB so we don't trigger auto-recovery again just in case test logic is flawed
    q_kiro = await db_conn.fetchrow("SELECT status FROM quota_status WHERE tool_name = 'kiro'")
    assert q_kiro['status'] == 'exhausted'


@pytest.mark.asyncio
async def test_log_event(db_conn: Connection):
    """Test quota_log appending."""
    await log_event("cursor", "", QuotaEvent.CALL_SUCCESS, task_id=None, raw_response="OK", conn=db_conn)
    
    rows = await db_conn.fetch("SELECT * FROM quota_log WHERE tool_name = 'cursor'")
    assert len(rows) >= 1
    
    # Verify the most recent
    latest = sorted(rows, key=lambda x: x['timestamp'], reverse=True)[0]
    assert latest['event'] == 'call_success'
    assert latest['raw_response'] == 'OK'
