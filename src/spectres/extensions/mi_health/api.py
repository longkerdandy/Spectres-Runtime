"""Thin FastAPI adapter for Mi Health account binding and sessions."""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request, Response, status

from spectres.extensions.mi_health.auth import require_user_id
from spectres.extensions.mi_health.credentials import CredentialProtectionError
from spectres.extensions.mi_health.schemas import BindingStatusResponse, QRChallengePollResponse, QRChallengeResponse
from spectres.extensions.mi_health.service import (
    BindingExistsError,
    ChallengeNotFoundError,
    MiHealthBindingService,
    MiHealthSessionService,
    NotBoundError,
)
from spectres.extensions.mi_health.xiaomi import AuthenticationRequiredError, ChallengeExpiredError, OwnerActionRequiredError, XiaomiError

logger = logging.getLogger(__name__)


def create_router(*, bindings: MiHealthBindingService, sessions: MiHealthSessionService) -> APIRouter:
    """Build the self-scoped Mi Health REST router."""
    router = APIRouter(prefix="/api/v1/extensions/mi-health", tags=["mi-health"])

    @router.get("/status", response_model=BindingStatusResponse)
    def get_status(request: Request) -> object:
        user_id = require_user_id(request)
        return bindings.status(user_id)

    @router.post("/auth/qr-challenges", response_model=QRChallengeResponse)
    async def create_qr_challenge(request: Request) -> object:
        user_id = require_user_id(request)
        try:
            challenge = await bindings.create_qr_challenge(user_id)
        except (XiaomiError, CredentialProtectionError, BindingExistsError, ChallengeNotFoundError, NotBoundError) as exc:
            _raise_safe(exc)
        logger.info("Mi Health QR challenge created", extra={"event": "mi_health_qr_started", "user_id": user_id})
        return challenge

    @router.post("/auth/qr-challenges/{challenge_id}/poll", response_model=QRChallengePollResponse)
    async def poll_qr_challenge(challenge_id: str, request: Request) -> QRChallengePollResponse:
        user_id = require_user_id(request)
        try:
            binding = await bindings.poll_qr_challenge(user_id, challenge_id)
        except (XiaomiError, CredentialProtectionError, ChallengeNotFoundError) as exc:
            _raise_safe(exc)
        logger.info("Mi Health account bound", extra={"event": "mi_health_bound", "user_id": user_id})
        return QRChallengePollResponse(state="authenticated", binding=BindingStatusResponse.model_validate(binding, from_attributes=True))

    @router.delete("/auth/qr-challenges/{challenge_id}", status_code=status.HTTP_204_NO_CONTENT)
    def cancel_qr_challenge(challenge_id: str, request: Request) -> Response:
        user_id = require_user_id(request)
        try:
            bindings.cancel_qr_challenge(user_id, challenge_id)
        except ChallengeNotFoundError as exc:
            _raise_safe(exc)
        logger.info("Mi Health QR challenge cancelled", extra={"event": "mi_health_qr_cancelled", "user_id": user_id})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/binding", status_code=status.HTTP_204_NO_CONTENT)
    def unbind(request: Request) -> Response:
        user_id = require_user_id(request)
        try:
            bindings.unbind(user_id)
        except NotBoundError as exc:
            _raise_safe(exc)
        logger.info("Mi Health account unbound", extra={"event": "mi_health_unbound", "user_id": user_id})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/session/renew", response_model=BindingStatusResponse)
    async def renew(request: Request) -> object:
        user_id = require_user_id(request)
        try:
            result = await sessions.renew(user_id)
        except (XiaomiError, CredentialProtectionError, NotBoundError) as exc:
            _raise_safe(exc)
        logger.info("Mi Health session renewed", extra={"event": "mi_health_session_renewed", "user_id": user_id})
        return result

    @router.post("/session/verify", response_model=BindingStatusResponse)
    async def verify(request: Request) -> object:
        user_id = require_user_id(request)
        try:
            result = await sessions.verify(user_id)
        except (XiaomiError, CredentialProtectionError, NotBoundError) as exc:
            _raise_safe(exc)
        logger.info("Mi Health connection verified", extra={"event": "mi_health_session_verified", "user_id": user_id})
        return result

    return router


def _raise_safe(exc: Exception) -> NoReturn:
    if isinstance(exc, CredentialProtectionError):
        code, http_status, message = "credential_protection_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE, "Mi Health credential protection is unavailable"
    elif isinstance(exc, ChallengeNotFoundError):
        code, http_status, message = "challenge_not_found", status.HTTP_404_NOT_FOUND, "Mi Health QR challenge was not found"
    elif isinstance(exc, ChallengeExpiredError):
        code, http_status, message = "challenge_expired", status.HTTP_410_GONE, "Mi Health QR challenge expired; start a new challenge"
    elif isinstance(exc, NotBoundError):
        code, http_status, message = "not_bound", status.HTTP_404_NOT_FOUND, "Mi Health is not bound"
    elif isinstance(exc, BindingExistsError):
        code, http_status, message = "binding_exists", status.HTTP_409_CONFLICT, "Mi Health is already bound"
    elif isinstance(exc, OwnerActionRequiredError):
        code, http_status, message = "owner_action_required", status.HTTP_409_CONFLICT, "Xiaomi requires owner action; start a new QR challenge"
    elif isinstance(exc, AuthenticationRequiredError):
        code, http_status, message = "authentication_required", status.HTTP_409_CONFLICT, "Xiaomi authentication is required"
    else:
        code, http_status, message = "provider_unavailable", status.HTTP_502_BAD_GATEWAY, "Xiaomi is unavailable or returned an invalid response"
    logger.warning("Mi Health operation failed", extra={"event": "mi_health_operation_failed", "code": code, "reason": str(exc)})
    raise HTTPException(status_code=http_status, detail={"code": code, "message": message}) from None
