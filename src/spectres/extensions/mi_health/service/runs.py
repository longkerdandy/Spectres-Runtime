"""Safe volatile snapshots for Mi Health synchronization runs."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SyncRunStatus = Literal["queued", "running", "succeeded", "partially_failed", "failed", "interrupted", "skipped"]
SyncRunStreamStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]
SyncFailureStage = Literal["provider_read", "record_mapping", "database_write", "checkpoint_conflict", "authentication"]


class SyncInProgressError(RuntimeError):
    """The owner already has an active synchronization run."""


@dataclass(frozen=True)
class SyncRunStream:
    """Safe outcome metadata for one stream within one run."""

    stream: str
    status: SyncRunStreamStatus
    record_count: int
    failure_stage: SyncFailureStage | None
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class SyncRun:
    """Safe current-process snapshot of one synchronization run."""

    id: str
    trigger_type: Literal["manual", "scheduled"]
    status: SyncRunStatus
    streams: list[SyncRunStream]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
