from typing import Optional

from asyncpg import Connection

from db.connection import get_connection
from core.models import ApiCredential
from core.encryption import decrypt_key


DEFAULT_USER_ID = "owner"


async def get_next_credential(
    tool_name: str, user_id: str = DEFAULT_USER_ID, conn: Optional[Connection] = None
) -> Optional[ApiCredential]:
    """Get the next available credential for a tool, ordered by sequence_order.
    The returned credential will have its api_key decrypted in memory.
    """
    async def _execute(c: Connection):
        row = await c.fetchrow(
            """
            SELECT id, tool_name, account_label, api_key, sequence_order, status, tool_type, user_id
            FROM api_credentials
            WHERE tool_name = $1 AND user_id = $2 AND status = 'available'
            ORDER BY sequence_order ASC
            LIMIT 1
            """,
            tool_name, user_id
        )
        if row:
            cred_dict = dict(row)
            # Decrypt the key in memory before returning
            cred_dict['api_key'] = decrypt_key(cred_dict['api_key'])
            return ApiCredential(**cred_dict)
        return None

    if conn:
        return await _execute(conn)
    else:
        async with get_connection() as c:
            return await _execute(c)


async def mark_credential_exhausted(
    credential_id: int, conn: Optional[Connection] = None
) -> None:
    """Mark a specific credential ID as exhausted."""
    async def _execute(c: Connection):
        await c.execute(
            """
            UPDATE api_credentials
            SET status = 'exhausted'
            WHERE id = $1
            """,
            credential_id
        )

    if conn:
        await _execute(conn)
    else:
        async with get_connection() as c:
            await _execute(c)


async def rotate_credential(
    tool_name: str, conn: Optional[Connection] = None
) -> Optional[ApiCredential]:
    """Find the next available credential for a tool, and return it.
    Returns None if all credentials for this tool are exhausted.
    (This is essentially an alias for get_next_credential but explicitly for the rotation flow).
    """
    return await get_next_credential(tool_name, conn)
