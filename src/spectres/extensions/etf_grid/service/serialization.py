"""Shared JSON serialization for service outputs."""

from datetime import date, datetime
from decimal import Decimal
from typing import cast


def to_jsonable[T](value: T) -> T:
    """Normalize service outputs into JSON-serializable structures.

    Decimals become strings, dates/datetimes ISO strings, applied
    recursively through dicts and sequences. Shared by the toolkit and
    API adapters so the chat and HTTP surfaces serialize identically.
    The container shape is preserved; only leaf scalar types change
    (hence the casts: T describes the container, not the leaves).
    """
    if isinstance(value, Decimal):
        return cast(T, str(value))
    if isinstance(value, datetime):
        return cast(T, value.isoformat())
    if isinstance(value, date):
        return cast(T, value.isoformat())
    if isinstance(value, dict):
        return cast(T, {key: to_jsonable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return cast(T, [to_jsonable(item) for item in value])
    return value
