"""Typed public HTTP contracts for Mi Health account binding."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class BindingStatusResponse(BaseModel):
    """Non-sensitive current-user binding status."""

    status: Literal["unbound", "authenticated", "reauth_required"]
    region: Literal["cn"]
    bound_at: datetime | None
    last_verified_at: datetime | None
    last_renewed_at: datetime | None


class QRChallengeResponse(BaseModel):
    """Owner-only QR presentation material; never includes the polling URL."""

    challenge_id: str
    qr_payload: str
    created_at: datetime
    server_timeout_seconds: int | None


class QRChallengePollResponse(BaseModel):
    """QR approval outcome and safe binding state when authenticated."""

    state: Literal["waiting", "authenticated", "owner_action_required", "failed"]
    failure_code: str | None = None
    binding: BindingStatusResponse | None = None
