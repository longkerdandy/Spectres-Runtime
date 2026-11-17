"""Typed public HTTP contracts for Mi Health binding and synchronization."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from spectres.extensions.mi_health.service.runs import SyncFailureStage, SyncRunStatus, SyncRunStreamStatus


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


class SyncRunStreamResponse(BaseModel):
    """Safe outcome metadata for one stream within a synchronization run."""

    stream: str
    status: SyncRunStreamStatus
    record_count: int
    failure_stage: SyncFailureStage | None
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


class SyncRunResponse(BaseModel):
    """One current-process synchronization run without owner or health values."""

    id: str
    trigger_type: Literal["manual", "scheduled"]
    status: SyncRunStatus
    streams: list[SyncRunStreamResponse]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SyncStreamHealthResponse(BaseModel):
    """Current checkpoint health independently of any selected run."""

    stream: str
    status: Literal["never_synced", "succeeded", "failed"]
    last_run_started_at: datetime | None
    last_succeeded_at: datetime | None
    last_failed_at: datetime | None
    last_successful_window_end: datetime | None
    backfill_completed: bool
    last_error_code: str | None


class SyncStatusResponse(BaseModel):
    """Active/latest runs and current stream health for the verified owner."""

    active_run: SyncRunResponse | None
    last_run: SyncRunResponse | None
    streams: list[SyncStreamHealthResponse]
