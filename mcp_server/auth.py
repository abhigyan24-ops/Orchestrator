import os
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.params import Depends

# We use HTTPBearer to extract the token, but we'll do custom validation
security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    FastAPI dependency to verify the Bearer token matches MCP_AUTH_TOKEN.
    If MCP_AUTH_TOKEN is not set, we assume local dev without auth, or we fail secure.
    The prompt dictates failing if invalid.
    """
    expected = os.environ.get("MCP_AUTH_TOKEN")
    
    # If no token is set in env, we allow it (for local dev), or we can enforce it.
    # The prompt implies a shared token. Let's enforce it if it's set in env.
    if expected:
        if credentials.credentials != expected:
            raise HTTPException(status_code=401, detail="Invalid auth token")
    else:
        # If no expected token is configured, we reject for security unless explicitly handled.
        raise HTTPException(
            status_code=401, 
            detail="MCP_AUTH_TOKEN not configured on server"
        )
    
    return credentials.credentials
