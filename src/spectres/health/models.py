"""Core-owned, provider-neutral personal health tables."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Index, Integer, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class HealthBase(DeclarativeBase):
    """Declarative base for canonical personal health data."""


class HealthProfile(HealthBase):
    """Latest retained profile snapshot for one owner and provider."""

    __tablename__ = "health_profiles"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(16))
    daily_step_goal: Mapped[int | None] = mapped_column(Integer)
    daily_calorie_goal_kcal: Mapped[int | None] = mapped_column(Integer)
    stand_goal: Mapped[int | None] = mapped_column(Integer)
    activity_goal_minutes: Mapped[int | None] = mapped_column(Integer)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class HealthDailySummary(HealthBase):
    """Merged daily metric history for one owner, provider, and local day."""

    __tablename__ = "health_daily_summaries"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    steps: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    active_calories_kcal: Mapped[int | None] = mapped_column(Integer)
    stand_count: Mapped[int | None] = mapped_column(SmallInteger)
    intensity_minutes: Mapped[int | None] = mapped_column(Integer)
    avg_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    min_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    resting_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    avg_spo2_pct: Mapped[int | None] = mapped_column(SmallInteger)
    min_spo2_pct: Mapped[int | None] = mapped_column(SmallInteger)
    max_spo2_pct: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_total_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_deep_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_light_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_rem_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_awake_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_avg_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_min_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_max_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_avg_spo2_pct: Mapped[int | None] = mapped_column(SmallInteger)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("steps >= 0 AND distance_m >= 0 AND active_calories_kcal >= 0", name="ck_health_daily_activity_nonnegative"),
        CheckConstraint("stand_count >= 0 AND intensity_minutes >= 0", name="ck_health_daily_activity_goals_nonnegative"),
        CheckConstraint(
            "sleep_total_minutes >= 0 AND sleep_deep_minutes >= 0 AND sleep_light_minutes >= 0 AND sleep_rem_minutes >= 0 AND sleep_awake_minutes >= 0",
            name="ck_health_daily_sleep_nonnegative",
        ),
    )


class HealthSleepSession(HealthBase):
    """Correctable raw sleep history keyed by deterministic source identity."""

    __tablename__ = "health_sleep_sessions"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_device_id: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    deep_minutes: Mapped[int | None] = mapped_column(Integer)
    light_minutes: Mapped[int | None] = mapped_column(Integer)
    rem_minutes: Mapped[int | None] = mapped_column(Integer)
    awake_minutes: Mapped[int | None] = mapped_column(Integer)
    awake_count: Mapped[int | None] = mapped_column(Integer)
    avg_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    min_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    timezone_name: Mapped[str | None] = mapped_column(String(64))
    utc_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_health_sleep_sessions_user_started", "user_id", "started_at"),
        CheckConstraint("ended_at >= started_at", name="ck_health_sleep_sessions_time_order"),
        CheckConstraint(
            "duration_minutes >= 0 AND deep_minutes >= 0 AND light_minutes >= 0 AND rem_minutes >= 0 AND awake_minutes >= 0 AND awake_count >= 0",
            name="ck_health_sleep_sessions_nonnegative",
        ),
    )


class HealthBodyMeasurement(HealthBase):
    """Correctable weight and body-composition history."""

    __tablename__ = "health_body_measurements"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_device_id: Mapped[str | None] = mapped_column(Text)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    bmi: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    composition_status: Mapped[str] = mapped_column(String(16))
    body_fat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    fat_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    muscle_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    muscle_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    skeletal_muscle_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    body_moisture_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    moisture_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    bone_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    protein_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    protein_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    basal_metabolism_kcal: Mapped[int | None] = mapped_column(Integer)
    visceral_fat: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    heart_rate_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    timezone_name: Mapped[str | None] = mapped_column(String(64))
    utc_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_health_body_measurements_user_measured", "user_id", "measured_at"),
        CheckConstraint("weight_kg > 0", name="ck_health_body_measurements_weight_positive"),
        CheckConstraint("composition_status IN ('not_reported', 'unavailable', 'measured')", name="ck_health_body_measurements_composition_status"),
    )


class HealthWorkout(HealthBase):
    """Correctable workout summary history without tracks or detail files."""

    __tablename__ = "health_workouts"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_device_id: Mapped[str | None] = mapped_column(Text)
    activity_type: Mapped[str | None] = mapped_column(String(32))
    provider_activity_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    active_calories_kcal: Mapped[int | None] = mapped_column(Integer)
    total_calories_kcal: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[int | None] = mapped_column(Integer)
    avg_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    max_hr_bpm: Mapped[int | None] = mapped_column(SmallInteger)
    timezone_name: Mapped[str | None] = mapped_column(String(64))
    utc_offset_seconds: Mapped[int | None] = mapped_column(Integer)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_health_workouts_user_started", "user_id", "started_at"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_health_workouts_time_order"),
        CheckConstraint(
            "duration_seconds >= 0 AND distance_m >= 0 AND active_calories_kcal >= 0 AND total_calories_kcal >= 0 AND steps >= 0",
            name="ck_health_workouts_nonnegative",
        ),
    )


class HealthIngestionState(HealthBase):
    """Latest safe checkpoint for one owner, provider, and stream."""

    __tablename__ = "health_ingestion_states"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    stream: Mapped[str] = mapped_column(String(64), primary_key=True)
    backfill_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_successful_window_end: Mapped[int | None] = mapped_column(BigInteger)
    last_run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (CheckConstraint("consecutive_failures >= 0 AND revision >= 0", name="ck_health_ingestion_states_nonnegative"),)
