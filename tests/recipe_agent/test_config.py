"""Unit tests for ``spectres_runtime.recipe_agent.config`` — pure, no DB, no network.

Mirrors the source split: ``RecipeAgentSettings`` lives in the ``recipe_agent``
package, so its tests live alongside the package's other tests rather than in the
top-level config suite. Covers the ``RECIPE_AGENT_`` prefix mapping and the
no-defaults contract.
"""

from __future__ import annotations

import pytest

from spectres_runtime.recipe_agent.config import RecipeAgentSettings


def test_recipe_agent_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The `RECIPE_AGENT_` prefix maps `RECIPE_AGENT_<FIELD>` -> `<field>`.
    monkeypatch.setenv("RECIPE_AGENT_INSTRUCTIONS", "Search recipes before answering.")
    monkeypatch.setenv("RECIPE_AGENT_NUM_HISTORY_RUNS", "5")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_MODEL", "model-id")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_API_KEY", "sk-secret")

    settings = RecipeAgentSettings()

    assert settings.instructions == "Search recipes before answering."
    assert settings.num_history_runs == 5
    assert settings.chat_model == "model-id"
    assert settings.chat_base_url == "https://chat.example/v1"
    assert settings.chat_api_key.get_secret_value() == "sk-secret"


def test_recipe_agent_settings_optional_chat_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional OpenAI-compatible parameters are parsed and forwarded."""
    monkeypatch.setenv("RECIPE_AGENT_INSTRUCTIONS", "")
    monkeypatch.setenv("RECIPE_AGENT_NUM_HISTORY_RUNS", "3")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_MODEL", "model-id")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_API_KEY", "sk-secret")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_TEMPERATURE", "0.7")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_TOP_P", "0.9")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_MAX_TOKENS", "1024")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_REASONING_EFFORT", "low")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_THINKING", "enabled")
    monkeypatch.setenv("RECIPE_AGENT_CHAT_REQUEST_PARAMS", '{"custom_param": "value"}')

    settings = RecipeAgentSettings()

    assert settings.chat_temperature == 0.7
    assert settings.chat_top_p == 0.9
    assert settings.chat_max_tokens == 1024
    assert settings.chat_reasoning_effort == "low"
    assert settings.chat_thinking == "enabled"
    assert settings.chat_request_params == {"custom_param": "value"}

    model = settings.build_chat_model()
    assert model.temperature == 0.7
    assert model.top_p == 0.9
    assert model.max_tokens == 1024
    assert model.reasoning_effort == "low"
    assert model.request_params == {
        "thinking": {"type": "enabled"},
        "custom_param": "value",
    }


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECIPE_AGENT_INSTRUCTIONS", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_NUM_HISTORY_RUNS", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_MODEL", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("RECIPE_AGENT_CHAT_API_KEY", raising=False)

    # No defaults: with nothing in the env (and `.env` bypassed) construction fails.
    with pytest.raises(ValueError):
        RecipeAgentSettings(_env_file=None)
