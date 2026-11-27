"""Разбор и фильтрация кандидатов, полученных от LLM.

Модель выступает генератором идей, а не источником истины: каждое слово
проверяется по буквам исходного слова с учётом их количества. Модуль не
выполняет сетевых вызовов.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

# Слово — только буквы (Unicode), без цифр и знаков.
_WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)

# Маркеры списка в начале строки: «- », «1. », «• » и т.п.
_BULLET_PREFIX = re.compile(r"^\s*(?:[-–—*•]|\d+[.)])\s*")

# Разделитель «слово — пояснение»: тире, двоеточие, дефис с пробелами.
_EXPLANATION_SEPARATOR = re.compile(r"\s+[-–—:]\s+")

_QUOTES = "`\"'«»“”„‘’"


def normalize_word(text: str) -> str:
    """Привести слово к сравнимому виду: нижний регистр, ``ё`` → ``е``."""
    return text.strip().strip(_QUOTES).lower().replace("ё", "е")


def letter_counts(word: str) -> Counter[str]:
    """Посчитать количество каждой буквы в слове."""
    return Counter(normalize_word(word))


def can_build(candidate: str, available: Mapping[str, int] | Counter[str]) -> bool:
    """Можно ли собрать слово из доступных букв с учётом их количества."""
    needed = Counter(candidate)
    return all(count <= available.get(letter, 0) for letter, count in needed.items())


def parse_candidates(raw_answer: str) -> list[str]:
    """Извлечь слова-кандидаты из ответа модели.

    Понимает списки с маркерами, запятые, кавычки и строки вида
    «слово — пояснение». Пояснения отбрасываются.
    """
    candidates: list[str] = []

    for raw_line in raw_answer.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line = _BULLET_PREFIX.sub("", line).strip()
        if not line:
            continue

        # Пояснение после тире/двоеточия отбрасываем.
        line = _EXPLANATION_SEPARATOR.split(line, maxsplit=1)[0]

        for chunk in re.split(r"[,;]+", line):
            chunk = chunk.strip().strip(_QUOTES).strip()
            if not chunk:
                continue
            if not _WORD_PATTERN.fullmatch(chunk):
                continue
            candidates.append(normalize_word(chunk))

    return candidates


def filter_words(
    candidates: Iterable[str],
    source_word: str,
    *,
    min_length: int = 2,
    max_results: int = 300,
    exclude_source: bool = True,
) -> list[str]:
    """Оставить только валидные слова, собираемые из букв исходного слова.

    Результат: без повторов, отсортирован по убыванию длины, затем по алфавиту.

    :param candidates: слова-кандидаты (в любом регистре)
    :param source_word: исходное слово
    :param min_length: минимальная длина слова
    :param max_results: максимум слов в результате
    :param exclude_source: не включать само исходное слово
    """
    available = letter_counts(source_word)
    normalized_source = normalize_word(source_word)

    seen: set[str] = set()
    result: list[str] = []

    for raw_candidate in candidates:
        word = normalize_word(raw_candidate)
        if not word or word in seen:
            continue
        if len(word) < min_length:
            continue
        if exclude_source and word == normalized_source:
            continue
        if not can_build(word, available):
            continue
        seen.add(word)
        result.append(word)

    result.sort(key=lambda item: (-len(item), item))
    return result[:max_results]


__all__ = [
    "can_build",
    "filter_words",
    "letter_counts",
    "normalize_word",
    "parse_candidates",
]
