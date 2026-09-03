import pytest
from asyncpg import Connection

from core.credential_manager import get_next_credential, mark_credential_exhausted, rotate_credential
from core.models import CredentialStatus
from core.encryption import encrypt_key


@pytest.mark.asyncio
async def test_credential_rotation(db_conn: Connection):
    """Test getting, decrypting, and rotating credentials."""
    # Insert some credentials
    enc_key1 = encrypt_key("secret1")
    enc_key2 = encrypt_key("secret2")
    
    await db_conn.execute(
        """
        INSERT INTO api_credentials (tool_name, account_label, api_key, sequence_order, status, tool_type)
        VALUES 
        ('test_api', 'acc1', $1, 1, 'available', 'api_based'),
        ('test_api', 'acc2', $2, 2, 'available', 'api_based')
        """,
        enc_key1, enc_key2
    )

    # First fetch should give acc1 and decrypt the key
    cred1 = await get_next_credential('test_api', conn=db_conn)
    assert cred1 is not None
    assert cred1.account_label == 'acc1'
    assert cred1.api_key == "secret1"  # Decrypted

    # Mark it exhausted
    await mark_credential_exhausted(cred1.id, conn=db_conn)
    
    # Next fetch (or rotation) should give acc2
    cred2 = await rotate_credential('test_api', conn=db_conn)
    assert cred2 is not None
    assert cred2.account_label == 'acc2'
    assert cred2.api_key == "secret2"
    
    # Mark acc2 exhausted
    await mark_credential_exhausted(cred2.id, conn=db_conn)
    
    # Rotation should now return None
    cred3 = await rotate_credential('test_api', conn=db_conn)
    assert cred3 is None
