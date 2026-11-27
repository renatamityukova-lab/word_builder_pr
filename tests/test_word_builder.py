"""Тесты оркестрации «Наборщика» и fallback-сообщений."""

from __future__ import annotations

import pytest

from cache import reset_words_cache
from config.settings import CacheSettings, Settings
from llm.errors import (
    LLMConfigError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from services.word_builder import (
    FALLBACK_BAD_RESPONSE,
    FALLBACK_CONFIG,
    FALLBACK_UNAVAILABLE,
    FALLBACK_UNKNOWN,
    build_words,
    fallback_message,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_words_cache()
    yield
    reset_words_cache()


def _settings() -> Settings:
    return Settings(cache=CacheSettings(enabled=False))


def test_build_words_filters_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.word_builder.complete",
        lambda *args, **kwargs: "кот\nток\nкто\nкошка\nдом\nок",
    )

    result = build_words("кот", settings=_settings())

    assert result.source == "кот"
    assert result.words == ["кто", "ток", "ок"]
    assert result.total == 3


def test_build_words_normalizes_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "services.word_builder.complete",
        lambda *args, **kwargs: "еж",
    )

    result = build_words("  ЁЖ  ", settings=_settings())
    assert result.source == "еж"
    # Исходное слово исключено из результата.
    assert result.words == []


def test_build_words_propagates_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_complete(*args, **kwargs):
        raise LLMUnavailableError("нет сети")

    monkeypatch.setattr("services.word_builder.complete", failing_complete)

    with pytest.raises(LLMUnavailableError):
        build_words("кот", settings=_settings())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LLMConfigError("x"), FALLBACK_CONFIG),
        (LLMUnavailableError("x"), FALLBACK_UNAVAILABLE),
        (LLMResponseError("x"), FALLBACK_BAD_RESPONSE),
        (LLMRequestRejectedError("x"), FALLBACK_BAD_RESPONSE),
        (LLMUnavailableError("x"), FALLBACK_UNAVAILABLE),
    ],
)
def test_fallback_message(error: Exception, expected: str) -> None:
    assert fallback_message(error) == expected


def test_fallback_message_unknown() -> None:
    from llm.errors import LLMError

    assert fallback_message(LLMError("x")) == FALLBACK_UNKNOWN
