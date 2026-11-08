"""Aggregate router for Runtime-owned HTTP APIs."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from spectres.extensions.base import LoadedExtension
from spectres.extensions.state import ExtensionState, ExtensionStateService


class ExtensionStateResponse(BaseModel):
    """Public metadata and activation state for one built-in Extension."""

    id: str
    name: str
    description: str
    enabled: bool
    updated_at: datetime


class ExtensionCatalogResponse(BaseModel):
    """Current built-in Extension catalog."""

    items: list[ExtensionStateResponse]


class ExtensionStateUpdate(BaseModel):
    """Administrator activation update."""

    enabled: bool


def _state_response(extension: LoadedExtension, state: ExtensionState) -> ExtensionStateResponse:
    return ExtensionStateResponse(
        id=extension.id,
        name=extension.name,
        description=extension.description,
        enabled=state.enabled,
        updated_at=state.updated_at,
    )


def _require_admin(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    scopes = getattr(request.state, "scopes", [])
    if not isinstance(user_id, str) or not user_id or not isinstance(scopes, list) or "agent_os:admin" not in scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent_os:admin scope required")
    return user_id


def create_api_router(state_service: ExtensionStateService, extensions: list[LoadedExtension]) -> APIRouter:
    """Assemble core versioned APIs, including built-in Extension activation."""
    router = APIRouter(prefix="/api/v1")

    @router.get("/extensions")
    def list_extensions() -> ExtensionCatalogResponse:
        states = {state.id: state for state in state_service.list_states()}
        return ExtensionCatalogResponse(items=[_state_response(extension, states[extension.id]) for extension in extensions if extension.id in states])

    @router.patch("/extensions/{extension_id}")
    def update_extension(extension_id: str, body: ExtensionStateUpdate, request: Request) -> ExtensionStateResponse:
        admin_id = _require_admin(request)
        extension = next((extension for extension in extensions if extension.id == extension_id), None)
        if extension is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="extension not found")
        try:
            state = state_service.set_enabled(extension_id, enabled=body.enabled, updated_by=admin_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="extension not found") from exc
        return _state_response(extension, state)

    return router
