"""Бизнес-логика игры «Наборщик» (Word Builder).

Единая точка входа — :func:`build_words`. Оркестрация:

1. нормализация исходного слова;
2. проверка кеша (при попадании LLM **не вызывается**);
3. формирование промпта;
4. вызов LLM;
5. разбор и фильтрация кандидатов по буквам исходного слова;
6. запись результата в кеш (только непустого).

Каждый этап пишется в лог: слово, попадание/промах кеша, формирование
промпта, ответ модели, результат фильтрации и ошибки.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from cache import get_words_cache
from config.settings import Settings, get_settings
from llm.client import complete
from llm.errors import (
    LLMConfigError,
    LLMError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from llm.prompts import SYSTEM_PROMPT, build_user_prompt
from services.normalizer import (
    filter_words,
    letter_counts,
    normalize_word,
    parse_candidates,
)

logger = logging.getLogger(__name__)

FALLBACK_CONFIG = "Сервис не настроен: проверьте ключ доступа к LLM."
FALLBACK_UNAVAILABLE = "Модель временно недоступна. Попробуйте позже."
FALLBACK_BAD_RESPONSE = "Модель вернула некорректный ответ. Попробуйте ещё раз."
FALLBACK_UNKNOWN = "Не удалось получить слова. Попробуйте ещё раз."
EMPTY_RESULT = "Не удалось подобрать слова. Попробуйте другое слово или повторите позже."


@dataclass(frozen=True)
class BuildResult:
    """Результат разбора исходного слова."""

    source: str
    words: list[str] = field(default_factory=list)
    from_cache: bool = False
    elapsed_seconds: float = 0.0

    @property
    def total(self) -> int:
        """Количество найденных слов."""
        return len(self.words)


def build_words(
    source_word: str,
    *,
    settings: Settings | None = None,
    use_cache: bool = True,
) -> BuildResult:
    """Подобрать все слова, которые можно составить из букв исходного слова.

    :param source_word: исходное слово (предполагается прошедшим валидацию)
    :param settings: настройки (по умолчанию — из ``config/config.yaml`` и ``.env``)
    :param use_cache: использовать ли кеш
    :returns: найденные слова и признак ответа из кеша
    :raises LLMError: модель недоступна или вернула бесполезный ответ
    """
    settings = settings or get_settings()
    source = normalize_word(source_word)
    started = time.perf_counter()

    logger.info("Наборщик: старт — слово=%r (длина %d)", source, len(source))

    cache = get_words_cache(settings) if use_cache else None
    if cache is not None:
        cached = cache.get(source)
        if cached is not None:
            elapsed = time.perf_counter() - started
            logger.info(
                "Кеш: попадание — %r, слов=%d (%.3f с)",
                source,
                len(cached),
                elapsed,
            )
            return BuildResult(
                source=source,
                words=list(cached),
                from_cache=True,
                elapsed_seconds=elapsed,
            )
        logger.info("Кеш: промах — %r, требуется вызов LLM", source)

    user_prompt = build_user_prompt(
        source,
        letter_counts(source),
        min_length=settings.builder.min_word_length,
        max_words=settings.llm.max_words,
    )
    logger.info(
        "Промпт: сформирован для %r (%d символов)", source, len(user_prompt)
    )
    logger.debug("Промпт для LLM (%r):\n%s", source, user_prompt)

    try:
        raw_answer = complete(SYSTEM_PROMPT, user_prompt, settings=settings.llm)
    except LLMError as exc:
        logger.error(
            "Ошибка LLM при разборе %r: %s: %s",
            source,
            type(exc).__name__,
            exc,
        )
        raise

    logger.info("Ответ LLM для %r: %d символов", source, len(raw_answer))
    logger.debug("Содержимое ответа LLM (%r): %r", source, raw_answer)

    candidates = parse_candidates(raw_answer)
    words = filter_words(
        candidates,
        source,
        min_length=settings.builder.min_word_length,
        max_results=settings.builder.max_results,
    )
    logger.info(
        "Фильтрация: кандидатов=%d, после проверки букв=%d",
        len(candidates),
        len(words),
    )

    if cache is not None and words:
        cache.set(source, words)
        logger.info("Кеш: сохранено — %r, слов=%d", source, len(words))
    elif cache is not None:
        logger.info("Кеш: пустой результат не сохраняется — %r", source)

    elapsed = time.perf_counter() - started
    logger.info(
        "Наборщик: готово — %r, слов=%d за %.3f с",
        source,
        len(words),
        elapsed,
    )
    return BuildResult(source=source, words=words, elapsed_seconds=elapsed)


def fallback_message(error: LLMError) -> str:
    """Безопасное сообщение пользователю при недоступности модели.

    Технические детали остаются в логах, пользователь видит короткий текст.
    """
    if isinstance(error, LLMConfigError):
        return FALLBACK_CONFIG
    if isinstance(error, LLMUnavailableError):
        return FALLBACK_UNAVAILABLE
    if isinstance(error, (LLMResponseError, LLMRequestRejectedError)):
        return FALLBACK_BAD_RESPONSE
    return FALLBACK_UNKNOWN


__all__ = [
    "BuildResult",
    "EMPTY_RESULT",
    "FALLBACK_BAD_RESPONSE",
    "FALLBACK_CONFIG",
    "FALLBACK_UNAVAILABLE",
    "FALLBACK_UNKNOWN",
    "build_words",
    "fallback_message",
]
