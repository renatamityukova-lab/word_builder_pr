"""Кеш результатов «Наборщика».

Назначение — не отправлять в LLM повторный запрос для слова, которое уже
разбиралось менее 10 минут назад. Ключ — нормализованное исходное слово,
значение — список найденных слов.
"""

from __future__ import annotations

import logging

from cache.ttl_cache import TTLCache
from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_words_cache: TTLCache[str, list[str]] | None = None


def get_words_cache(settings: Settings | None = None) -> TTLCache[str, list[str]] | None:
    """Вернуть общий кеш слов согласно настройкам.

    :returns: экземпляр кеша либо ``None``, если кеширование отключено
    """
    global _words_cache

    settings = settings or get_settings()
    if not settings.cache.enabled:
        return None

    if _words_cache is None:
        if settings.cache.backend != "memory":
            logger.warning(
                "Бэкенд кеша %r не реализован — используется memory",
                settings.cache.backend,
            )
        _words_cache = TTLCache(
            ttl_seconds=settings.cache.ttl_seconds,
            max_size=settings.cache.max_size,
        )
        logger.info(
            "Кеш: создан — backend=memory, ttl=%d с, max_size=%s",
            settings.cache.ttl_seconds,
            settings.cache.max_size,
        )

    return _words_cache


def reset_words_cache() -> None:
    """Очистить и сбросить общий кеш (тесты, перезагрузка настроек)."""
    global _words_cache
    if _words_cache is not None:
        _words_cache.clear()
    _words_cache = None


__all__ = ["TTLCache", "get_words_cache", "reset_words_cache"]
