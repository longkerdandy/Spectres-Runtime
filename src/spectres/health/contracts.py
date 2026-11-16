"""Typed canonical inputs accepted by provider-neutral health ingestion."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonObject = dict[str, Any]
CompositionStatus = Literal["not_reported", "unavailable", "measured"]


class HealthContract(BaseModel):
    """Base contract with provider-owned provenance and selected raw values."""

    model_config = ConfigDict(frozen=True)

    provider_metadata: JsonObject = Field(default_factory=dict)


class ProfileSnapshot(HealthContract):
    """Latest non-sensitive profile context supplied by one provider."""

    height_cm: Decimal | None = Field(default=None, gt=0)
    birth_year: int | None = Field(default=None, ge=1800, le=2200)
    sex: str | None = Field(default=None, max_length=16)
    daily_step_goal: int | None = Field(default=None, ge=0)
    daily_calorie_goal_kcal: int | None = Field(default=None, ge=0)
    stand_goal: int | None = Field(default=None, ge=0)
    activity_goal_minutes: int | None = Field(default=None, ge=0)


class DailySummary(HealthContract):
    """One provider-local health day with explicit partial-field semantics."""

    day: date
    steps: int | None = Field(default=None, ge=0)
    distance_m: int | None = Field(default=None, ge=0)
    active_calories_kcal: int | None = Field(default=None, ge=0)
    stand_count: int | None = Field(default=None, ge=0, le=32767)
    intensity_minutes: int | None = Field(default=None, ge=0)
    avg_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    min_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    max_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    resting_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    avg_spo2_pct: int | None = Field(default=None, gt=0, le=100)
    min_spo2_pct: int | None = Field(default=None, gt=0, le=100)
    max_spo2_pct: int | None = Field(default=None, gt=0, le=100)
    sleep_total_minutes: int | None = Field(default=None, ge=0)
    sleep_deep_minutes: int | None = Field(default=None, ge=0)
    sleep_light_minutes: int | None = Field(default=None, ge=0)
    sleep_rem_minutes: int | None = Field(default=None, ge=0)
    sleep_awake_minutes: int | None = Field(default=None, ge=0)
    sleep_score: int | None = Field(default=None, gt=0, le=32767)
    sleep_avg_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    sleep_min_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    sleep_max_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    sleep_avg_spo2_pct: int | None = Field(default=None, gt=0, le=100)
    raw_payload: JsonObject = Field(default_factory=dict)


class SourcedHealthContract(HealthContract):
    """Canonical history record keyed by deterministic provider identity."""

    source_record_id: str = Field(min_length=1, max_length=1024)
    source_device_id: str | None = None
    timezone_name: str | None = Field(default=None, max_length=64)
    utc_offset_seconds: int | None = None
    provider_updated_at: datetime | None = None
    is_deleted: bool = False
    raw_payload: JsonObject = Field(default_factory=dict)

    @field_validator("source_record_id")
    @classmethod
    def deterministic_source_identity(cls, value: str) -> str:
        """Reject blank and bare random-UUID record identities."""
        normalized = value.strip()
        if not normalized or normalized != value:
            raise ValueError("source_record_id must be non-blank and trimmed")
        try:
            uuid.UUID(value)
        except ValueError:
            return value
        raise ValueError("source_record_id must be a deterministic provider key")

    @field_validator("provider_updated_at", "started_at", "ended_at", "measured_at", check_fields=False)
    @classmethod
    def timezone_aware_instants(cls, value: datetime | None) -> datetime | None:
        """Require explicit timezone context for normalized provider instants."""
        if value is not None and value.utcoffset() is None:
            raise ValueError("health instants must be timezone-aware")
        return value


class SleepSession(SourcedHealthContract):
    """One raw provider sleep event, retaining unnormalized stage details."""

    started_at: datetime
    ended_at: datetime
    duration_minutes: int | None = Field(default=None, ge=0)
    deep_minutes: int | None = Field(default=None, ge=0)
    light_minutes: int | None = Field(default=None, ge=0)
    rem_minutes: int | None = Field(default=None, ge=0)
    awake_minutes: int | None = Field(default=None, ge=0)
    awake_count: int | None = Field(default=None, ge=0)
    avg_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    min_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    max_hr_bpm: int | None = Field(default=None, gt=0, le=32767)


class BodyMeasurement(SourcedHealthContract):
    """One weight measurement with explicitly available composition values."""

    measured_at: datetime
    weight_kg: Decimal = Field(gt=0)
    bmi: Decimal | None = Field(default=None, gt=0)
    composition_status: CompositionStatus = "not_reported"
    body_fat_rate: Decimal | None = Field(default=None, gt=0)
    fat_mass_kg: Decimal | None = Field(default=None, gt=0)
    muscle_mass_kg: Decimal | None = Field(default=None, gt=0)
    muscle_rate: Decimal | None = Field(default=None, gt=0)
    skeletal_muscle_mass_kg: Decimal | None = Field(default=None, gt=0)
    body_moisture_mass_kg: Decimal | None = Field(default=None, gt=0)
    moisture_rate: Decimal | None = Field(default=None, gt=0)
    bone_mass_kg: Decimal | None = Field(default=None, gt=0)
    protein_mass_kg: Decimal | None = Field(default=None, gt=0)
    protein_rate: Decimal | None = Field(default=None, gt=0)
    basal_metabolism_kcal: int | None = Field(default=None, gt=0)
    visceral_fat: Decimal | None = Field(default=None, gt=0)
    heart_rate_bpm: int | None = Field(default=None, gt=0, le=32767)


class Workout(SourcedHealthContract):
    """One provider workout summary without tracks or workout-detail payloads."""

    activity_type: str | None = Field(default=None, max_length=32)
    provider_activity_code: str | None = Field(default=None, max_length=64)
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    distance_m: int | None = Field(default=None, ge=0)
    active_calories_kcal: int | None = Field(default=None, ge=0)
    total_calories_kcal: int | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    avg_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
    max_hr_bpm: int | None = Field(default=None, gt=0, le=32767)
