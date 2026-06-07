"""Unit tests for ``spectres_runtime.config`` — pure, no DB, no network.

Settings declares no defaults, so these tests supply values explicitly (via constructor
kwargs or env) and check they load and map onto the embedder and chat model. The live
embed / chat calls live in the ``integration`` tier (see ``test_embedder_integration``).
"""

from __future__ import annotations

import pytest
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.moonshot import MoonShot
from pydantic import SecretStr

from spectres_runtime.config import Settings, get_settings

_ENV = {
    "DATABASE_URL": "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime",
    "EMBEDDER_MODEL": "Qwen/Qwen3-Embedding-0.6B",
    "EMBEDDER_BASE_URL": "https://api.siliconflow.cn/v1",
    "EMBEDDER_DIMENSIONS": "1024",
    "EMBEDDER_API_KEY": "sk-secret",
    "CHAT_MODEL": "kimi-for-coding",
    "CHAT_BASE_URL": "https://api.kimi.com/coding/v1",
    "CHAT_API_KEY": "sk-chat-secret",
}


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)

    settings = get_settings()

    assert settings.database_url == "postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime"
    assert settings.embedder_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.embedder_base_url == "https://api.siliconflow.cn/v1"
    assert settings.embedder_dimensions == 1024
    # Secret stays wrapped; not exposed by repr.
    assert settings.embedder_api_key.get_secret_value() == "sk-secret"
    assert settings.chat_model == "kimi-for-coding"
    assert settings.chat_base_url == "https://api.kimi.com/coding/v1"
    assert settings.chat_api_key.get_secret_value() == "sk-chat-secret"


def test_missing_required_field_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_build_embedder_maps_every_field() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime",
        embedder_model="custom/model",
        embedder_base_url="https://example.test/v1",
        embedder_dimensions=512,
        embedder_api_key=SecretStr("sk-secret"),
        chat_model="kimi-for-coding",
        chat_base_url="https://api.kimi.com/coding/v1",
        chat_api_key=SecretStr("sk-chat-secret"),
    )

    embedder = settings.build_embedder()

    assert isinstance(embedder, OpenAIEmbedder)
    assert embedder.id == "custom/model"
    assert embedder.base_url == "https://example.test/v1"
    assert embedder.dimensions == 512
    # SecretStr is unwrapped to a plain string for the OpenAI client.
    assert embedder.api_key == "sk-secret"


def _chat_settings() -> Settings:
    """Settings double carrying the required chat fields (and embedder/db fillers)."""
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://developer:devpass@localhost:5532/spectres_runtime",
        embedder_model="custom/model",
        embedder_base_url="https://example.test/v1",
        embedder_dimensions=512,
        embedder_api_key=SecretStr("sk-secret"),
        chat_model="kimi-for-coding",
        chat_base_url="https://api.kimi.com/coding/v1",
        chat_api_key=SecretStr("sk-chat-secret"),
    )


def test_build_chat_model_maps_every_field() -> None:
    chat_model = _chat_settings().build_chat_model()

    assert isinstance(chat_model, MoonShot)
    assert chat_model.id == "kimi-for-coding"
    assert chat_model.base_url == "https://api.kimi.com/coding/v1"
    # SecretStr is unwrapped to a plain string for the OpenAI-compatible client.
    assert chat_model.api_key == "sk-chat-secret"
