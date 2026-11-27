"""Валидация входного слова до обращения к LLM.

Правила из постановки задачи: строка, одно слово, не более 100 символов.
Дополнительно: только буквы (без цифр, пробелов и знаков), минимум 2 буквы.
"""

from __future__ import annotations

MAX_WORD_LENGTH = 100
MIN_WORD_LENGTH = 2

EMPTY_MESSAGE = "Введите слово."
NOT_STRING_MESSAGE = "Слово должно быть строкой."
TOO_LONG_MESSAGE = f"Слишком длинное слово — не более {MAX_WORD_LENGTH} символов."
NOT_SINGLE_WORD_MESSAGE = "Нужно одно слово без пробелов."
NOT_LETTERS_MESSAGE = "Слово должно состоять только из букв."
TOO_SHORT_MESSAGE = f"Слово должно содержать минимум {MIN_WORD_LENGTH} буквы."


def normalize_source_word(value: str) -> str:
    """Привести слово к сравнимому виду: нижний регистр, ``ё`` → ``е``."""
    return value.strip().lower().replace("ё", "е")


def validate_source_word(
    value: object,
    *,
    max_length: int = MAX_WORD_LENGTH,
    min_length: int = MIN_WORD_LENGTH,
) -> str | None:
    """Проверить входное слово.

    :return: сообщение об ошибке или ``None``, если ввод корректен.
    """
    if not isinstance(value, str):
        return NOT_STRING_MESSAGE

    text = value.strip()
    if not text:
        return EMPTY_MESSAGE
    if len(text) > max_length:
        return TOO_LONG_MESSAGE
    if any(char.isspace() for char in text):
        return NOT_SINGLE_WORD_MESSAGE
    if not all(char.isalpha() for char in text):
        return NOT_LETTERS_MESSAGE

    normalized = normalize_source_word(text)
    if len(normalized) < min_length:
        return TOO_SHORT_MESSAGE
    return None


__all__ = [
    "EMPTY_MESSAGE",
    "MAX_WORD_LENGTH",
    "MIN_WORD_LENGTH",
    "NOT_LETTERS_MESSAGE",
    "NOT_SINGLE_WORD_MESSAGE",
    "NOT_STRING_MESSAGE",
    "TOO_LONG_MESSAGE",
    "TOO_SHORT_MESSAGE",
    "normalize_source_word",
    "validate_source_word",
]
