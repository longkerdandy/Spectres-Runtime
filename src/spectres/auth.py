"""Authentication integrations owned by Spectres Runtime."""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class UserProfileSyncMiddleware(BaseHTTPMiddleware):
    """Refresh directory profile fields that Agno only writes on first login."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Synchronize a verified JWT display name before the route handles the request."""
        claims: Any = getattr(request.state, "claims", None)
        user_id = getattr(request.state, "user_id", None)
        user_store = getattr(request.app.state, "user_store", None)
        if user_store is not None and user_id and isinstance(claims, dict):
            name_claim = getattr(request.app.state, "user_name_claim", "name")
            name = claims.get(name_claim)
            if isinstance(name, str) and name:
                user = await user_store.aget(user_id)
                if user is not None and user.get("name") != name:
                    await user_store.aupsert(user_id, name=name, actor="system:jwt")
        return await call_next(request)
