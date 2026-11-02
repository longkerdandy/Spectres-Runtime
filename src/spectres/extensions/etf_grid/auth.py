"""Authenticated identity and authorization helpers for ETF Grid routes."""

from fastapi import HTTPException, Request, status


def require_user_id(request: Request) -> str:
    """Return the authenticated caller for a self-scoped portfolio operation."""
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, str) or not user_id or getattr(request.state, "is_internal_service", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="authenticated user identity required")
    return user_id


def require_admin_or_internal(request: Request) -> str:
    """Allow an Agno administrator or the verified internal scheduler caller."""
    if getattr(request.state, "is_internal_service", False) or getattr(request.state, "_agno_verified_internal", False):
        return "internal-scheduler"
    user_id = require_user_id(request)
    scopes = getattr(request.state, "scopes", [])
    if not isinstance(scopes, list) or "agent_os:admin" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent_os:admin scope required")
    return user_id
