"""Authenticated identity helper for self-scoped Mi Health routes."""

from fastapi import HTTPException, Request, status


def require_user_id(request: Request) -> str:
    """Require a normal verified user, excluding internal-service callers."""
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, str) or not user_id or getattr(request.state, "is_internal_service", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="authenticated user identity required")
    return user_id
