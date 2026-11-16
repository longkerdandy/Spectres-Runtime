"""Create the six provider-neutral Core personal health tables.

Revision ID: 0002_personal_health
Revises: 0001_runtime_state
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_personal_health"
down_revision: str | None = "0001_runtime_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity() -> list[sa.Column[Any]]:
    return [
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
    ]


def _sync_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _history_identity() -> list[sa.Column[Any]]:
    return [
        *_identity(),
        sa.Column("source_record_id", sa.Text(), nullable=False),
        sa.Column("source_device_id", sa.Text(), nullable=True),
    ]


def _history_provenance() -> list[sa.Column[Any]]:
    return [
        sa.Column("timezone_name", sa.String(length=64), nullable=True),
        sa.Column("utc_offset_seconds", sa.Integer(), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    """Create canonical health history and ingestion-state tables."""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("health_profiles"):
        op.create_table(
            "health_profiles",
            *_identity(),
            sa.Column("height_cm", sa.Numeric(5, 2), nullable=True),
            sa.Column("birth_year", sa.Integer(), nullable=True),
            sa.Column("sex", sa.String(length=16), nullable=True),
            sa.Column("daily_step_goal", sa.Integer(), nullable=True),
            sa.Column("daily_calorie_goal_kcal", sa.Integer(), nullable=True),
            sa.Column("stand_goal", sa.Integer(), nullable=True),
            sa.Column("activity_goal_minutes", sa.Integer(), nullable=True),
            *_sync_columns(),
            sa.PrimaryKeyConstraint("user_id", "provider"),
        )
    if not inspector.has_table("health_daily_summaries"):
        op.create_table(
            "health_daily_summaries",
            *_identity(),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("steps", sa.Integer(), nullable=True),
            sa.Column("distance_m", sa.Integer(), nullable=True),
            sa.Column("active_calories_kcal", sa.Integer(), nullable=True),
            sa.Column("stand_count", sa.SmallInteger(), nullable=True),
            sa.Column("intensity_minutes", sa.Integer(), nullable=True),
            sa.Column("avg_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("min_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("max_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("resting_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("avg_spo2_pct", sa.SmallInteger(), nullable=True),
            sa.Column("min_spo2_pct", sa.SmallInteger(), nullable=True),
            sa.Column("max_spo2_pct", sa.SmallInteger(), nullable=True),
            sa.Column("sleep_total_minutes", sa.Integer(), nullable=True),
            sa.Column("sleep_deep_minutes", sa.Integer(), nullable=True),
            sa.Column("sleep_light_minutes", sa.Integer(), nullable=True),
            sa.Column("sleep_rem_minutes", sa.Integer(), nullable=True),
            sa.Column("sleep_awake_minutes", sa.Integer(), nullable=True),
            sa.Column("sleep_score", sa.SmallInteger(), nullable=True),
            sa.Column("sleep_avg_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("sleep_min_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("sleep_max_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("sleep_avg_spo2_pct", sa.SmallInteger(), nullable=True),
            sa.Column("provider_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("user_id", "provider", "day"),
            sa.CheckConstraint("steps >= 0 AND distance_m >= 0 AND active_calories_kcal >= 0", name="ck_health_daily_activity_nonnegative"),
            sa.CheckConstraint("stand_count >= 0 AND intensity_minutes >= 0", name="ck_health_daily_activity_goals_nonnegative"),
            sa.CheckConstraint(
                "sleep_total_minutes >= 0 AND sleep_deep_minutes >= 0 AND sleep_light_minutes >= 0 AND sleep_rem_minutes >= 0 AND sleep_awake_minutes >= 0",
                name="ck_health_daily_sleep_nonnegative",
            ),
        )
    if not inspector.has_table("health_sleep_sessions"):
        op.create_table(
            "health_sleep_sessions",
            *_history_identity(),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("deep_minutes", sa.Integer(), nullable=True),
            sa.Column("light_minutes", sa.Integer(), nullable=True),
            sa.Column("rem_minutes", sa.Integer(), nullable=True),
            sa.Column("awake_minutes", sa.Integer(), nullable=True),
            sa.Column("awake_count", sa.Integer(), nullable=True),
            sa.Column("avg_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("min_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("max_hr_bpm", sa.SmallInteger(), nullable=True),
            *_history_provenance(),
            sa.PrimaryKeyConstraint("user_id", "provider", "source_record_id"),
            sa.CheckConstraint("ended_at >= started_at", name="ck_health_sleep_sessions_time_order"),
            sa.CheckConstraint(
                "duration_minutes >= 0 AND deep_minutes >= 0 AND light_minutes >= 0 AND rem_minutes >= 0 AND awake_minutes >= 0 AND awake_count >= 0",
                name="ck_health_sleep_sessions_nonnegative",
            ),
        )
        op.create_index("ix_health_sleep_sessions_user_started", "health_sleep_sessions", ["user_id", "started_at"])
    if not inspector.has_table("health_body_measurements"):
        op.create_table(
            "health_body_measurements",
            *_history_identity(),
            sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
            sa.Column("bmi", sa.Numeric(5, 2), nullable=True),
            sa.Column("composition_status", sa.String(length=16), nullable=False),
            sa.Column("body_fat_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("fat_mass_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("muscle_mass_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("muscle_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("skeletal_muscle_mass_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("body_moisture_mass_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("moisture_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("bone_mass_kg", sa.Numeric(5, 2), nullable=True),
            sa.Column("protein_mass_kg", sa.Numeric(6, 2), nullable=True),
            sa.Column("protein_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("basal_metabolism_kcal", sa.Integer(), nullable=True),
            sa.Column("visceral_fat", sa.Numeric(5, 2), nullable=True),
            sa.Column("heart_rate_bpm", sa.SmallInteger(), nullable=True),
            *_history_provenance(),
            sa.PrimaryKeyConstraint("user_id", "provider", "source_record_id"),
            sa.CheckConstraint("weight_kg > 0", name="ck_health_body_measurements_weight_positive"),
            sa.CheckConstraint("composition_status IN ('not_reported', 'unavailable', 'measured')", name="ck_health_body_measurements_composition_status"),
        )
        op.create_index("ix_health_body_measurements_user_measured", "health_body_measurements", ["user_id", "measured_at"])
    if not inspector.has_table("health_workouts"):
        op.create_table(
            "health_workouts",
            *_history_identity(),
            sa.Column("activity_type", sa.String(length=32), nullable=True),
            sa.Column("provider_activity_code", sa.String(length=64), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("distance_m", sa.Integer(), nullable=True),
            sa.Column("active_calories_kcal", sa.Integer(), nullable=True),
            sa.Column("total_calories_kcal", sa.Integer(), nullable=True),
            sa.Column("steps", sa.Integer(), nullable=True),
            sa.Column("avg_hr_bpm", sa.SmallInteger(), nullable=True),
            sa.Column("max_hr_bpm", sa.SmallInteger(), nullable=True),
            *_history_provenance(),
            sa.PrimaryKeyConstraint("user_id", "provider", "source_record_id"),
            sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_health_workouts_time_order"),
            sa.CheckConstraint(
                "duration_seconds >= 0 AND distance_m >= 0 AND active_calories_kcal >= 0 AND total_calories_kcal >= 0 AND steps >= 0",
                name="ck_health_workouts_nonnegative",
            ),
        )
        op.create_index("ix_health_workouts_user_started", "health_workouts", ["user_id", "started_at"])
    if not inspector.has_table("health_ingestion_states"):
        op.create_table(
            "health_ingestion_states",
            *_identity(),
            sa.Column("stream", sa.String(length=64), nullable=False),
            sa.Column("backfill_completed", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("last_successful_window_end", sa.BigInteger(), nullable=True),
            sa.Column("last_run_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_succeeded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
            sa.Column("last_error_code", sa.String(length=64), nullable=True),
            sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("user_id", "provider", "stream"),
            sa.CheckConstraint("consecutive_failures >= 0 AND revision >= 0", name="ck_health_ingestion_states_nonnegative"),
        )


def downgrade() -> None:
    """Destructive downgrades are intentionally not supported during startup."""
    raise NotImplementedError("reviewed downgrade must be run explicitly")
