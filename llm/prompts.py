"""Промпты для LLM: генерация слов для игры «Наборщик».

Модель получает исходное слово и инвентарь букв (буква × количество),
а также жёсткие правила формата ответа. Финальную проверку букв выполняет
:mod:`services.normalizer` — модели доверяем только как генератору кандидатов.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

SYSTEM_PROMPT = (
    "Ты — помощник в игре «Наборщик» (Word Builder). "
    "Твоя задача — составлять русские слова из букв исходного слова. "
    "Не рассуждай вслух и не описывай ход мыслей — сразу выводи список слов. "
    "Отвечай строго в заданном формате: только слова, по одному на строку, "
    "без нумерации, пояснений, markdown и вступлений."
)

_USER_PROMPT_TEMPLATE = """Составь как можно больше русских слов, которые можно собрать из букв исходного слова.

Исходное слово: {word}
Доступные буквы (буква × количество): {letters}

Правила:
- используй ТОЛЬКО буквы исходного слова и не больше раз, чем они встречаются;
- только нарицательные существительные в именительном падеже, единственном числе;
- без имён собственных, аббревиатур, жаргона и устаревших слов;
- минимальная длина слова — {min_length} буквы;
- не включай само исходное слово;
- не повторяй слова;
- верни не больше {max_words} слов.

Формат ответа: только слова, по одному на строку. Без нумерации, запятых,
пояснений, кавычек и markdown."""


def _format_letters(letter_counts: Mapping[str, int] | str) -> str:
    """Отформатировать инвентарь букв как ``а×2, б×1``."""
    counts = (
        Counter(letter_counts.lower())
        if isinstance(letter_counts, str)
        else Counter(letter_counts)
    )
    return ", ".join(f"{letter}×{count}" for letter, count in sorted(counts.items()))


def build_user_prompt(
    word: str,
    letter_counts: Mapping[str, int] | str,
    *,
    min_length: int = 2,
    max_words: int = 300,
) -> str:
    """Сформировать пользовательский запрос для генерации слов.

    :param word: исходное слово
    :param letter_counts: доступные буквы и их количество (``Counter``/``dict``/строка)
    :param min_length: минимальная длина слова в ответе
    :param max_words: максимум слов в ответе
    """
    return _USER_PROMPT_TEMPLATE.format(
        word=word.strip(),
        letters=_format_letters(letter_counts),
        min_length=min_length,
        max_words=max_words,
    )


def build_messages(
    word: str,
    letter_counts: Mapping[str, int] | str,
    *,
    min_length: int = 2,
    max_words: int = 300,
) -> list[dict[str, str]]:
    """Собрать сообщения для chat/completions: system + user."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_prompt(
                word,
                letter_counts,
                min_length=min_length,
                max_words=max_words,
            ),
        },
    ]


__all__ = ["SYSTEM_PROMPT", "build_messages", "build_user_prompt"]
