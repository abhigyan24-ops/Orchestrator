from typing import Optional

from asyncpg import Connection

from db.connection import get_connection
from core.models import ProjectContext


async def get_context(project_id: str, conn: Optional[Connection] = None) -> Optional[ProjectContext]:
    """Get the current context for a project."""
    async def _execute(c: Connection):
        row = await c.fetchrow(
            """
            SELECT project_id, architecture, progress_log, handoff_notes, updated_at
            FROM project_context
            WHERE project_id = $1
            """,
            project_id
        )
        if row:
            return ProjectContext(**dict(row))
        return None

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def upsert_context(
    project_id: str,
    architecture: Optional[str] = None,
    progress_log: Optional[str] = None,
    handoff_notes: Optional[str] = None,
    conn: Optional[Connection] = None
) -> ProjectContext:
    """Insert or update a project context."""
    async def _execute(c: Connection):
        # We need to only update the fields that are provided, or just overwrite them all if provided.
        # The prompt says upsert_context(project_id, architecture, progress_log, handoff_notes)
        # We'll use COALESCE to keep existing values if None is passed for an update,
        # but for insert we just insert the None.
        row = await c.fetchrow(
            """
            INSERT INTO project_context (project_id, architecture, progress_log, handoff_notes, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (project_id) DO UPDATE 
            SET 
                architecture = COALESCE($2, project_context.architecture),
                progress_log = COALESCE($3, project_context.progress_log),
                handoff_notes = COALESCE($4, project_context.handoff_notes),
                updated_at = NOW()
            RETURNING *
            """,
            project_id, architecture, progress_log, handoff_notes
        )
        return ProjectContext(**dict(row))

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)
