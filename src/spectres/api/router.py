"""Aggregate router for Runtime-owned HTTP APIs."""

from fastapi import APIRouter

from spectres.extensions.base import ExtensionContribution


def create_api_router(contributions: list[ExtensionContribution]) -> APIRouter:
    """Assemble all core API modules under the versioned API prefix."""
    return APIRouter(prefix="/api/v1")
