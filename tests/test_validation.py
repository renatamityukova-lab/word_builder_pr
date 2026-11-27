"""Тесты валидации входного слова."""

from __future__ import annotations

import pytest

from services.validation import (
    EMPTY_MESSAGE,
    MAX_WORD_LENGTH,
    NOT_LETTERS_MESSAGE,
    NOT_SINGLE_WORD_MESSAGE,
    NOT_STRING_MESSAGE,
    TOO_LONG_MESSAGE,
    TOO_SHORT_MESSAGE,
    normalize_source_word,
    validate_source_word,
)


@pytest.mark.parametrize("value", ["кот", "Простокваша", "ёж", "  слово  "])
def test_valid_words(value: str) -> None:
    assert validate_source_word(value) is None


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_empty_values(value: str) -> None:
    assert validate_source_word(value) == EMPTY_MESSAGE


def test_not_a_string() -> None:
    assert validate_source_word(None) == NOT_STRING_MESSAGE
    assert validate_source_word(123) == NOT_STRING_MESSAGE


def test_too_long() -> None:
    assert validate_source_word("а" * (MAX_WORD_LENGTH + 1)) == TOO_LONG_MESSAGE
    assert validate_source_word("а" * MAX_WORD_LENGTH) is None


def test_multiple_words_rejected() -> None:
    assert validate_source_word("два слова") == NOT_SINGLE_WORD_MESSAGE


@pytest.mark.parametrize("value", ["кот1", "кот!", "кот-пес", "abc123"])
def test_only_letters(value: str) -> None:
    assert validate_source_word(value) == NOT_LETTERS_MESSAGE


def test_too_short() -> None:
    assert validate_source_word("я") == TOO_SHORT_MESSAGE


def test_normalize_source_word() -> None:
    assert normalize_source_word("  ЁЖИК  ") == "ежик"
    assert normalize_source_word("Простокваша") == "простокваша"
