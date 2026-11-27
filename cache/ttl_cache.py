"""Простой in-memory кеш «словарь + TTL».

Потокобезопасен (``threading.Lock``), не требует внешних зависимостей.
Подходит для одного процесса; для нескольких воркеров предусмотрены бэкенды
``file`` и ``redis`` (пока не реализованы).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from threading import Lock
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    """Кеш с временем жизни записей.

    :param ttl_seconds: время жизни записи в секундах
    :param max_size: максимальное число записей (при переполнении вытесняется
        запись с ближайшим истечением срока); ``None`` — без ограничения
    :param clock: источник времени (по умолчанию ``time.monotonic``; подменяется в тестах)
    """

    def __init__(
        self,
        ttl_seconds: float,
        *,
        max_size: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds должен быть положительным")
        self._ttl = float(ttl_seconds)
        self._max_size = max_size
        self._clock = clock
        self._data: dict[K, _Entry[V]] = {}
        self._lock = Lock()

    def get(self, key: K) -> V | None:
        """Вернуть значение или ``None``, если записи нет либо истёк TTL."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at <= self._clock():
                del self._data[key]
                return None
            return entry.value

    def set(self, key: K, value: V) -> None:
        """Сохранить значение с текущим TTL."""
        with self._lock:
            if (
                self._max_size is not None
                and key not in self._data
                and len(self._data) >= self._max_size
            ):
                self._evict_expired()
                if len(self._data) >= self._max_size:
                    oldest_key = min(
                        self._data, key=lambda item: self._data[item].expires_at
                    )
                    del self._data[oldest_key]
            self._data[key] = _Entry(value=value, expires_at=self._clock() + self._ttl)

    def delete(self, key: K) -> None:
        """Удалить запись, если она есть."""
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        """Очистить кеш полностью."""
        with self._lock:
            self._data.clear()

    def purge_expired(self) -> int:
        """Удалить просроченные записи и вернуть их количество."""
        with self._lock:
            return self._evict_expired()

    def _evict_expired(self) -> int:
        now = self._clock()
        expired = [key for key, entry in self._data.items() if entry.expires_at <= now]
        for key in expired:
            del self._data[key]
        return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: object) -> bool:
        return self.get(key) is not None  # type: ignore[arg-type]

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            return iter(list(self._data))


__all__ = ["TTLCache"]
