"""Тесты загрузки конфигурации: профили dev/prod и приоритет источников."""

from __future__ import annotations

import pytest

import config.settings as settings_module
from config.settings import (
    DEFAULT_BASE_URL,
    get_settings,
    resolve_config_path,
    resolve_env_name,
)


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Изолировать тесты от локального .env и внешних переменных окружения."""
    monkeypatch.setattr(settings_module, "ENV_PATH", tmp_path / "absent.env")
    for name in (
        "APP_ENV",
        "APP_HOST",
        "APP_PORT",
        "UI_HOST",
        "UI_PORT",
        "UI_SHARE",
        "LLM_MODEL",
        "CACHE_TTL_SECONDS",
        "LOG_LEVEL",
        "LOG_CONSOLE",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_default_env_is_dev() -> None:
    assert resolve_env_name() == "dev"

    settings = get_settings()

    assert settings.app.env == "dev"
    assert settings.app.host == "127.0.0.1"
    assert settings.logging.level == "DEBUG"


def test_prod_profile_overrides_base_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")

    settings = get_settings()

    assert settings.app.env == "prod"
    assert settings.app.host == "0.0.0.0"
    assert settings.logging.level == "INFO"
    assert settings.logging.console is False
    assert settings.cache.ttl_seconds == 3600


def test_env_variables_win_over_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "42")
    monkeypatch.setenv("UI_PORT", "7999")

    settings = get_settings()

    assert settings.llm.model == "custom-model"
    assert settings.cache.ttl_seconds == 42
    assert settings.ui.port == 7999


def test_empty_env_variable_does_not_override_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LLM_MODEL", "   ")

    settings = get_settings()

    assert settings.llm.model == "gpt-oss-120b"


def test_unknown_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValueError, match="APP_ENV"):
        get_settings()


def test_profile_path_is_derived_from_env_name() -> None:
    assert resolve_config_path("dev").name == "config.dev.yaml"
    assert resolve_config_path("prod").name == "config.prod.yaml"

    with pytest.raises(ValueError, match="APP_ENV"):
        resolve_config_path("staging")


def test_missing_profile_file_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setattr(settings_module, "BASE_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="config.dev.yaml"):
        get_settings()


def test_llm_default_base_url_is_single_source() -> None:
    """URL по умолчанию не дублируется в llm.client."""
    from llm.client import _chat_completions_url

    assert _chat_completions_url(None) == f"{DEFAULT_BASE_URL}/chat/completions"
    assert _chat_completions_url("https://example.test/v1/") == (
        "https://example.test/v1/chat/completions"
    )
