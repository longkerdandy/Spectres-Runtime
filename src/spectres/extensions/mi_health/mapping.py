"""Pure Xiaomi Mi Fitness to canonical Core health mapping."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from spectres.health.contracts import BodyMeasurement, DailySummary, ProfileSnapshot, SleepSession, Workout

PROVIDER = "mi_fitness"
_COMPOSITION_FIELDS = {
    "body_fat_rate": "body_fat_rate",
    "fat_mass": "fat_mass_kg",
    "muscle_mass": "muscle_mass_kg",
    "muscle_rate": "muscle_rate",
    "skeletal_muscle_mass": "skeletal_muscle_mass_kg",
    "body_moisture_mass": "body_moisture_mass_kg",
    "moisture_rate": "moisture_rate",
    "bone_mass": "bone_mass_kg",
    "protein_mass": "protein_mass_kg",
    "protein_rate": "protein_rate",
    "visceral_fat": "visceral_fat",
}


class MiFitnessMappingError(ValueError):
    """A provider record lacks required validated canonical semantics."""


def map_profile(payload: dict[str, Any]) -> ProfileSnapshot:
    """Map only retained profile context and goals, excluding identity fields."""
    values: dict[str, Any] = {}
    _assign(values, "height_cm", payload, "height", _positive_decimal)
    _assign(values, "birth_year", payload, "birth_year", _birth_year)
    if "birth" in payload and "birth_year" not in values:
        values["birth_year"] = _birth_year(payload["birth"])
    _assign(values, "daily_step_goal", payload, "daily_step_goal", _nonnegative_int)
    _assign(values, "daily_calorie_goal_kcal", payload, "daily_cal_goal", _nonnegative_int)
    _assign(values, "stand_goal", payload, "stand_goal", _nonnegative_int)
    sex = payload.get("sex")
    if sex in {"male", "female", "other"}:
        values["sex"] = sex
    goals = payload.get("regular_goal_list")
    if isinstance(goals, list):
        for goal in goals:
            if isinstance(goal, dict) and goal.get("field") == 4 and "value" in goal:
                values["activity_goal_minutes"] = _nonnegative_int(goal["value"])
    return ProfileSnapshot(**values, provider_metadata={"source": "profile"})


def map_daily(row: dict[str, Any]) -> DailySummary:
    """Map one selected daily metric while retaining partial-merge semantics."""
    key = _required_text(row.get("key"), "daily metric key")
    value = _value(row)
    day = _day(row.get("time"))
    values: dict[str, Any] = {}
    if key == "steps":
        _assign(values, "steps", value, "steps", _nonnegative_int)
        _assign(values, "distance_m", value, "distance", _nonnegative_int)
        _assign(values, "active_calories_kcal", value, "calories", _nonnegative_int)
        _assign_any(values, "stand_count", value, ("stand_count", "stand", "activity_count"), _nonnegative_int)
        _assign_any(values, "intensity_minutes", value, ("intensity_minutes", "intensity", "active_minutes"), _nonnegative_int)
    elif key == "heart_rate":
        _assign(values, "avg_hr_bpm", value, "avg_hr", _positive_int)
        _assign(values, "min_hr_bpm", value, "min_hr", _positive_int)
        _assign(values, "max_hr_bpm", value, "max_hr", _positive_int)
        _assign(values, "resting_hr_bpm", value, "avg_rhr", _positive_int)
    elif key == "spo2":
        _assign(values, "avg_spo2_pct", value, "avg_spo2", _positive_int)
        _assign(values, "min_spo2_pct", value, "min_spo2", _positive_int)
        _assign(values, "max_spo2_pct", value, "max_spo2", _positive_int)
    elif key == "sleep":
        _assign(values, "sleep_total_minutes", value, "total_duration", _nonnegative_int)
        stage_fields = {
            "sleep_deep_minutes": "sleep_deep_duration",
            "sleep_light_minutes": "sleep_light_duration",
            "sleep_rem_minutes": "sleep_rem_duration",
            "sleep_awake_minutes": "sleep_awake_duration",
        }
        for target, source in stage_fields.items():
            _assign(values, target, value, source, _nonnegative_int)
        if values.get("sleep_total_minutes", 0) > 0 and all(values.get(field) == 0 for field in stage_fields):
            for field in stage_fields:
                if field in values:
                    values[field] = None
        _assign_any(values, "sleep_score", value, ("sleep_score", "score"), _positive_int)
        _assign_any(values, "sleep_avg_hr_bpm", value, ("sleep_avg_hr", "avg_hr", "avg_hrm"), _positive_int)
        _assign_any(values, "sleep_min_hr_bpm", value, ("sleep_min_hr", "min_hr", "min_hrm"), _positive_int)
        _assign_any(values, "sleep_max_hr_bpm", value, ("sleep_max_hr", "max_hr", "max_hrm"), _positive_int)
        _assign_any(values, "sleep_avg_spo2_pct", value, ("sleep_avg_spo2", "avg_spo2"), _positive_int)
    else:
        raise MiFitnessMappingError("Unsupported Mi Fitness daily metric")
    metadata = {
        key: {
            "sid": row.get("sid"),
            "time": row.get("time"),
            "source_sid_list": row.get("source_sid_list", []),
            "zone_name": row.get("zone_name"),
            "zone_offset": row.get("zone_offset"),
        }
    }
    return DailySummary(day=day, **values, provider_metadata=metadata, raw_payload={key: value})


def map_sleep(row: dict[str, Any]) -> SleepSession:
    """Map one raw sleep event without normalizing provider stage codes."""
    value = _value(row)
    start = _epoch(value.get("bedtime") or value.get("device_bedtime") or value.get("bed_timestamp"))
    end = _epoch(value.get("wake_up_time") or value.get("device_wake_up_time") or value.get("out_bed_timestamp") or row.get("time"))
    source_time = row.get("time") or value.get("wake_up_time") or value.get("bedtime")
    source_epoch = _integer(source_time, "sleep source epoch")
    values: dict[str, Any] = {}
    _assign(values, "duration_minutes", value, "duration", _nonnegative_int)
    _assign_any(values, "deep_minutes", value, ("deep_duration", "sleep_deep_duration"), _nonnegative_int)
    _assign_any(values, "light_minutes", value, ("light_duration", "sleep_light_duration"), _nonnegative_int)
    _assign_any(values, "rem_minutes", value, ("rem_duration", "sleep_rem_duration"), _nonnegative_int)
    _assign_any(values, "awake_minutes", value, ("awake_duration", "sleep_awake_duration"), _nonnegative_int)
    _assign_any(values, "awake_count", value, ("awake_count", "wake_count"), _nonnegative_int)
    _assign_any(values, "avg_hr_bpm", value, ("avg_hr", "avg_hrm"), _positive_int)
    _assign_any(values, "min_hr_bpm", value, ("min_hr", "min_hrm"), _positive_int)
    _assign_any(values, "max_hr_bpm", value, ("max_hr", "max_hrm"), _positive_int)
    return SleepSession(
        source_record_id=_source_id("sleep", row, source_epoch),
        source_device_id=_optional_text(row.get("sid")),
        started_at=start,
        ended_at=end,
        timezone_name=_optional_text(row.get("zone_name")),
        utc_offset_seconds=_offset(row, value),
        provider_updated_at=_optional_epoch(value.get("update_time") or row.get("update_time")),
        is_deleted=_deleted(row),
        provider_metadata=_source_metadata(row, source_epoch),
        raw_payload=value,
        **values,
    )


def map_body(row: dict[str, Any]) -> BodyMeasurement:
    """Map weight and explicitly distinguish unavailable body composition."""
    value = _value(row)
    measured_at = _epoch(value.get("time") or row.get("time"))
    source_epoch = _integer(row.get("time") or value.get("time"), "weight source epoch")
    weight = _positive_decimal(value.get("weight"))
    if weight is None:
        raise MiFitnessMappingError("Mi Fitness weight is missing or unavailable")
    supplied = any(field in value for field in _COMPOSITION_FIELDS) or any(field in value for field in ("basal_metabolism", "bpm"))
    composition: dict[str, Any] = {}
    for source, target in _COMPOSITION_FIELDS.items():
        if source in value:
            composition[target] = _positive_decimal(value[source])
    if "basal_metabolism" in value:
        composition["basal_metabolism_kcal"] = _positive_int(value["basal_metabolism"])
    if "bpm" in value:
        composition["heart_rate_bpm"] = _positive_int(value["bpm"])
    measured = any(item is not None for item in composition.values())
    status: Any = "not_reported" if not supplied else "measured" if measured else "unavailable"
    return BodyMeasurement(
        source_record_id=_source_id("weight", row, source_epoch),
        source_device_id=_optional_text(row.get("sid")),
        measured_at=measured_at,
        weight_kg=weight,
        bmi=_positive_decimal(value.get("bmi")),
        composition_status=status,
        timezone_name=_optional_text(row.get("zone_name")),
        utc_offset_seconds=_offset(row, value),
        provider_updated_at=_optional_epoch(value.get("update_time") or row.get("update_time")),
        is_deleted=_deleted(row),
        provider_metadata=_source_metadata(row, source_epoch),
        raw_payload=value,
        **composition,
    )


def map_workout(row: dict[str, Any]) -> Workout:
    """Map a workout summary while preserving its unverified activity code."""
    value = _value(row)
    start_epoch = _integer(value.get("start_time") or row.get("time"), "workout start")
    source_epoch = _integer(row.get("time") or start_epoch, "workout source epoch")
    duration = _nonnegative_int(value.get("duration"))
    end_value = value.get("end_time")
    ended_at = _optional_epoch(end_value)
    if ended_at is None and end_value is None and duration is not None:
        ended_at = _epoch(start_epoch + duration)
    code = value.get("sport_type") or row.get("category") or row.get("key")
    return Workout(
        source_record_id=_source_id("workout", row, source_epoch),
        source_device_id=_optional_text(row.get("sid")),
        activity_type=None,
        provider_activity_code=_optional_text(code),
        started_at=_epoch(start_epoch),
        ended_at=ended_at,
        duration_seconds=duration,
        distance_m=_nonnegative_int(value.get("distance")),
        active_calories_kcal=_nonnegative_int(value.get("calories")),
        total_calories_kcal=_nonnegative_int(value.get("total_cal")),
        steps=_nonnegative_int(value.get("steps") if "steps" in value else value.get("total_steps")),
        avg_hr_bpm=_positive_int(value.get("avg_hrm")),
        max_hr_bpm=_positive_int(value.get("max_hrm")),
        timezone_name=_optional_text(row.get("zone_name")),
        utc_offset_seconds=_offset(row, value),
        provider_updated_at=_optional_epoch(value.get("update_time") or row.get("update_time")),
        is_deleted=_deleted(row),
        provider_metadata=_source_metadata(row, source_epoch),
        raw_payload=value,
    )


def filter_raw_window(rows: list[dict[str, Any]], *, start_time: int, end_time: int) -> list[dict[str, Any]]:
    """Apply local inclusive filtering after the provider first-bucket margin."""
    selected: list[dict[str, Any]] = []
    for row in rows:
        timestamp = _integer(row.get("time"), "raw record time")
        if start_time <= timestamp <= end_time:
            selected.append(row)
    return selected


def _value(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise MiFitnessMappingError("Mi Fitness record value is invalid") from None
    if not isinstance(value, dict):
        raise MiFitnessMappingError("Mi Fitness record value is not an object")
    return value


def _source_id(kind: str, row: dict[str, Any], source_epoch: int) -> str:
    sid = _required_text(row.get("sid"), "source device")
    outer_key = _optional_text(row.get("key")) or kind
    return f"v1:{kind}:{sid}:{outer_key}:{source_epoch}"


def _source_metadata(row: dict[str, Any], source_epoch: int) -> dict[str, Any]:
    return {
        "sid": row.get("sid"),
        "key": row.get("key"),
        "category": row.get("category"),
        "source_epoch": source_epoch,
        "deleted": _deleted(row),
        "zone_name": row.get("zone_name"),
        "zone_offset": row.get("zone_offset"),
    }


def _deleted(row: dict[str, Any]) -> bool:
    return row.get("deleted") is True or row.get("deleted") == 1


def _offset(row: dict[str, Any], value: dict[str, Any]) -> int | None:
    if row.get("zone_offset") is not None:
        return _integer(row["zone_offset"], "zone offset")
    if value.get("timezone") is not None:
        return _integer(value["timezone"], "nested timezone") * 900
    return None


def _day(value: Any) -> date:
    return _epoch(value).date()


def _epoch(value: Any) -> datetime:
    return datetime.fromtimestamp(_integer(value, "epoch"), UTC)


def _optional_epoch(value: Any) -> datetime | None:
    return _epoch(value) if value is not None else None


def _birth_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    year = _integer(value, "birth year")
    return year if 1800 <= year <= 2200 else None


def _assign(values: dict[str, Any], target: str, source: dict[str, Any], key: str, mapper: Any) -> None:
    if key in source:
        values[target] = mapper(source[key])


def _assign_any(values: dict[str, Any], target: str, source: dict[str, Any], keys: tuple[str, ...], mapper: Any) -> None:
    for key in keys:
        if key in source:
            values[target] = mapper(source[key])
            return


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise MiFitnessMappingError(f"Mi Fitness {name} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise MiFitnessMappingError(f"Mi Fitness {name} is invalid") from None
    if isinstance(value, float) and not value.is_integer():
        raise MiFitnessMappingError(f"Mi Fitness {name} is invalid")
    return result


def _nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    result = _integer(value, "measurement")
    if result < 0:
        raise MiFitnessMappingError("Mi Fitness measurement is negative")
    return result


def _positive_int(value: Any) -> int | None:
    result = _nonnegative_int(value)
    return result if result and result > 0 else None


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MiFitnessMappingError("Mi Fitness decimal measurement is invalid") from None
    if not result.is_finite() or result < 0:
        raise MiFitnessMappingError("Mi Fitness decimal measurement is invalid")
    return result if result > 0 else None


def _required_text(value: Any, name: str) -> str:
    text = _optional_text(value)
    if not text:
        raise MiFitnessMappingError(f"Mi Fitness {name} is missing")
    return text


def _optional_text(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (str, int)):
        text = str(value).strip()
        return text or None
    return None
