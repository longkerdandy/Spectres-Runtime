"""Ownership validation shared by ETF Grid services."""


def _require_user_id(user_id: str) -> str:
    if not user_id:
        raise ValueError("user_id is required")
    return user_id
