"""Тесты разбора ответа LLM и фильтрации слов по буквам."""

from __future__ import annotations

from services.normalizer import (
    can_build,
    filter_words,
    letter_counts,
    normalize_word,
    parse_candidates,
)


def test_normalize_word() -> None:
    assert normalize_word("  ЁЖ  ") == "еж"
    assert normalize_word('"Слово"') == "слово"


def test_letter_counts() -> None:
    assert letter_counts("ёж") == {"е": 1, "ж": 1}
    assert letter_counts("мама") == {"м": 2, "а": 2}


def test_can_build_respects_counts() -> None:
    available = letter_counts("кот")
    assert can_build("ток", available)
    assert can_build("кто", available)
    assert can_build("ок", available)
    assert not can_build("котт", available)
    assert not can_build("кошка", available)


def test_parse_candidates_various_formats() -> None:
    raw = """
    - кот
    1. ток
    • кто
    сок, дом
    слово — это пояснение
    "ёж"
    """
    assert parse_candidates(raw) == ["кот", "ток", "кто", "сок", "дом", "слово", "еж"]


def test_parse_candidates_skips_explanations() -> None:
    raw = "Вот список слов:\nкот\nток — река"
    assert parse_candidates(raw) == ["кот", "ток"]


def test_filter_words_basic() -> None:
    candidates = ["кот", "ток", "кто", "ок", "кошка", "ток", "дом"]
    result = filter_words(candidates, "кот")
    # Исходное слово исключено, повторы убраны, лишние буквы отброшены.
    assert result == ["кто", "ток", "ок"]


def test_filter_words_min_length() -> None:
    result = filter_words(["ок", "ток", "кто"], "кот", min_length=3)
    assert result == ["кто", "ток"]


def test_filter_words_max_results() -> None:
    result = filter_words(["ок", "ток", "кто"], "кот", max_results=1)
    assert len(result) == 1


def test_filter_words_yo_normalization() -> None:
    result = filter_words(["еж", "ёж"], "ёж", exclude_source=True)
    # После нормализации ё→е исходное слово тоже стало «еж» и исключено.
    assert result == []


def test_filter_words_includes_source_when_allowed() -> None:
    result = filter_words(["кот"], "кот", exclude_source=False)
    assert result == ["кот"]
