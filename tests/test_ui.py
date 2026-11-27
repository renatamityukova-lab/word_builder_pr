"""Тесты обработчика Gradio UI: валидация, успех, кеш и fallback-ответ."""

from __future__ import annotations

import pytest

import ui.gradio_app as gradio_app
from llm.errors import LLMConfigError, LLMUnavailableError
from services.word_builder import (
    EMPTY_RESULT,
    FALLBACK_CONFIG,
    FALLBACK_UNAVAILABLE,
    BuildResult,
)


def test_handle_build_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gradio_app,
        "build_words",
        lambda word: BuildResult(source=word, words=["кто", "ток"], elapsed_seconds=1.2),
    )

    output = gradio_app.handle_build("кот")

    assert "Исходное слово: кот" in output
    assert "Найдено слов: 2" in output
    assert "из кеша" not in output
    assert "кто" in output and "ток" in output


def test_handle_build_marks_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gradio_app,
        "build_words",
        lambda word: BuildResult(source=word, words=["кто"], from_cache=True),
    )

    output = gradio_app.handle_build("кот")

    assert "из кеша" in output


def test_handle_build_validation_error_skips_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        gradio_app, "build_words", lambda word: called.append(word)
    )

    output = gradio_app.handle_build("два слова")

    assert "Нужно одно слово без пробелов." in output
    assert called == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (LLMConfigError("нет ключа"), FALLBACK_CONFIG),
        (LLMUnavailableError("нет сети"), FALLBACK_UNAVAILABLE),
    ],
)
def test_handle_build_returns_fallback(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: str
) -> None:
    def failing(word: str):
        raise error

    monkeypatch.setattr(gradio_app, "build_words", failing)

    assert gradio_app.handle_build("кот") == expected


def test_handle_build_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gradio_app, "build_words", lambda word: BuildResult(source=word, words=[])
    )

    assert gradio_app.handle_build("кот") == EMPTY_RESULT
