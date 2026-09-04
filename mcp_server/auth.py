import os
import secrets
from typing import Optional
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.params import Depends

# HTTPBearer extracts the Bearer token, auto_error=False allows falling back to query param
security = HTTPBearer(auto_error=False)

async def verify_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    FastAPI dependency to verify the auth token matches MCP_AUTH_TOKEN.
    Accepts token via Authorization Bearer header, or via ?token=<value>
    query parameter as a fallback when the header is absent.
    """
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif request:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        elif "token" in request.query_params:
            token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid token"
        )

    expected = os.environ.get("MCP_AUTH_TOKEN")
    if expected:
        if not secrets.compare_digest(token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid auth token"
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MCP_AUTH_TOKEN not configured on server"
        )

    return token

