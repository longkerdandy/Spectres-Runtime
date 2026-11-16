"""Synthetic Mi Fitness mapping and canonical health-contract tests."""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from spectres.extensions.mi_health.mapping import map_body, map_daily, map_profile, map_sleep, map_workout
from spectres.health.contracts import SleepSession

pytestmark = pytest.mark.unit
_EPOCH = 1763222400


def _row(key: str, value: dict[str, object], *, epoch: int = _EPOCH) -> dict[str, object]:
    return {"key": key, "sid": "device-a", "time": epoch, "zone_name": "Asia/Shanghai", "zone_offset": 28800, "value": json.dumps(value)}


def test_profile_retains_only_selected_context_and_goals() -> None:
    """Profile mapping excludes names, account identifiers, weight, and raw JSON."""
    profile = map_profile(
        {
            "height": 175,
            "birth": "1990-01-02",
            "sex": "female",
            "daily_step_goal": 8000,
            "daily_cal_goal": 400,
            "stand_goal": 12,
            "regular_goal_list": [{"field": 4, "value": 30}],
            "name": "synthetic-private-name",
            "weight": 70,
            "uid": "synthetic-account",
        }
    )

    assert profile.height_cm == Decimal("175")
    assert profile.birth_year == 1990
    assert profile.activity_goal_minutes == 30
    assert not hasattr(profile, "weight")
    assert "synthetic-private-name" not in repr(profile)
    assert "synthetic-account" not in repr(profile)


def test_daily_partial_merge_preserves_activity_zero_and_unavailable_measurements() -> None:
    """Activity zero is real while HR/SpO2 placeholders become explicit NULLs."""
    activity = map_daily(_row("steps", {"steps": 0, "distance": 0, "calories": 0, "stand": 0, "active_minutes": 0}))
    heart = map_daily(_row("heart_rate", {"avg_hr": 0, "min_hr": 0, "max_hr": 65, "avg_rhr": 0}))
    oxygen = map_daily(_row("spo2", {"avg_spo2": 0, "min_spo2": 0, "max_spo2": 98}))

    assert activity.steps == 0
    assert activity.distance_m == 0
    assert activity.stand_count == 0
    assert activity.intensity_minutes == 0
    assert "steps" in activity.model_fields_set
    assert heart.avg_hr_bpm is None and heart.max_hr_bpm == 65
    assert "avg_hr_bpm" in heart.model_fields_set
    assert "steps" not in heart.model_fields_set
    assert oxygen.avg_spo2_pct is None and oxygen.max_spo2_pct == 98


def test_daily_sleep_all_zero_breakdown_is_unavailable() -> None:
    """A positive sleep total with an all-zero stage breakdown retains only the total."""
    summary = map_daily(
        _row(
            "sleep",
            {
                "total_duration": 420,
                "sleep_deep_duration": 0,
                "sleep_light_duration": 0,
                "sleep_rem_duration": 0,
                "sleep_awake_duration": 0,
                "score": 80,
            },
        )
    )

    assert summary.sleep_total_minutes == 420
    assert summary.sleep_deep_minutes is None
    assert summary.sleep_light_minutes is None
    assert summary.sleep_rem_minutes is None
    assert summary.sleep_awake_minutes is None
    assert summary.sleep_score == 80


def test_raw_sleep_identity_timezone_stages_and_tombstone() -> None:
    """Raw stages survive unchanged and deletion retains a stable source key."""
    value = {
        "bedtime": _EPOCH,
        "wake_up_time": _EPOCH + 25200,
        "duration": 420,
        "sleep_deep_duration": 90,
        "sleep_light_duration": 240,
        "sleep_rem_duration": 60,
        "sleep_awake_duration": 30,
        "awake_count": 2,
        "items": [{"start_time": _EPOCH, "end_time": _EPOCH + 3600, "state": 99}],
        "timezone": 32,
    }
    first = map_sleep(_row("sleep", value))
    replay = map_sleep(_row("sleep", value))
    deleted = dict(value, deleted=True)
    deleted_row = _row("sleep", deleted)
    deleted_row["deleted"] = True
    tombstone = map_sleep(deleted_row)

    assert first.source_record_id == replay.source_record_id == tombstone.source_record_id
    assert first.source_record_id.startswith("v1:sleep:device-a:sleep:")
    assert first.started_at == datetime.fromtimestamp(_EPOCH, UTC)
    assert first.utc_offset_seconds == 28800
    assert first.raw_payload["items"][0]["state"] == 99
    assert tombstone.is_deleted is True


def test_body_composition_availability_and_numeric_values() -> None:
    """Weight-only, unavailable, and measured composition remain distinct."""
    weight_only = map_body(_row("weight", {"time": _EPOCH, "weight": "70.25", "bmi": 0}))
    unavailable = map_body(_row("weight", {"time": _EPOCH, "weight": 70, "body_fat_rate": 0, "muscle_mass": 0}))
    measured = map_body(
        _row(
            "weight",
            {
                "time": _EPOCH,
                "weight": 70,
                "body_fat_rate": "20.5",
                "fat_mass": "14.35",
                "muscle_mass": 0,
                "basal_metabolism": 1500,
                "bpm": 60,
            },
        )
    )

    assert weight_only.composition_status == "not_reported"
    assert weight_only.weight_kg == Decimal("70.25")
    assert weight_only.bmi is None
    assert unavailable.composition_status == "unavailable"
    assert unavailable.body_fat_rate is None and unavailable.muscle_mass_kg is None
    assert measured.composition_status == "measured"
    assert measured.body_fat_rate == Decimal("20.5")
    assert measured.fat_mass_kg == Decimal("14.35")
    assert measured.muscle_mass_kg is None
    assert measured.basal_metabolism_kcal == 1500


def test_workout_preserves_provider_code_without_inventing_canonical_type() -> None:
    """Workout summaries retain source codes, corrections, and raw values only."""
    workout = map_workout(
        _row(
            "sport",
            {
                "sport_type": 999,
                "start_time": _EPOCH,
                "end_time": _EPOCH + 1800,
                "duration": 1800,
                "distance": 5000,
                "calories": 300,
                "total_cal": 330,
                "steps": 6000,
                "avg_hrm": 130,
                "max_hrm": 160,
                "gps": "not-a-canonical-field",
            },
        )
    )

    assert workout.activity_type is None
    assert workout.provider_activity_code == "999"
    assert workout.duration_seconds == 1800
    assert workout.total_calories_kcal == 330
    assert workout.raw_payload["gps"] == "not-a-canonical-field"


def test_contract_rejects_bare_uuid_and_naive_instants() -> None:
    """Source identity is deterministic and all persisted instants carry zones."""
    with pytest.raises(ValidationError, match="deterministic provider key"):
        SleepSession(source_record_id=str(uuid.uuid4()), started_at=datetime.now(UTC), ended_at=datetime.now(UTC))
    with pytest.raises(ValidationError, match="timezone-aware"):
        SleepSession(source_record_id="v1:sleep:sid:sleep:1", started_at=datetime(2026, 1, 1), ended_at=datetime(2026, 1, 2))
