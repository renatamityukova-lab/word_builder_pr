"""Тесты TTL-кеша и его интеграции с бизнес-логикой."""

from __future__ import annotations

import pytest

from cache import get_words_cache, reset_words_cache
from cache.ttl_cache import TTLCache
from config.settings import CacheSettings, Settings
from services.word_builder import build_words


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_words_cache()
    yield
    reset_words_cache()


def test_set_and_get() -> None:
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=60)
    cache.set("key", "value")
    assert cache.get("key") == "value"
    assert len(cache) == 1
    assert "key" in cache


def test_expiration_by_ttl() -> None:
    clock = FakeClock()
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=10, clock=clock)
    cache.set("key", "value")

    clock.advance(9)
    assert cache.get("key") == "value"

    clock.advance(1)
    assert cache.get("key") is None
    assert len(cache) == 0


def test_max_size_evicts_oldest_expiring() -> None:
    clock = FakeClock()
    cache: TTLCache[str, str] = TTLCache(ttl_seconds=10, max_size=2, clock=clock)

    cache.set("a", "1")
    clock.advance(1)
    cache.set("b", "2")
    clock.advance(1)
    cache.set("c", "3")

    assert len(cache) == 2
    assert cache.get("a") is None
    assert cache.get("b") == "2"
    assert cache.get("c") == "3"


def test_invalid_ttl_rejected() -> None:
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=0)


def test_cache_disabled_returns_none() -> None:
    settings = Settings(cache=CacheSettings(enabled=False))
    assert get_words_cache(settings) is None


def test_default_ttl_is_ten_minutes() -> None:
    assert Settings().cache.ttl_seconds == 600


def test_builder_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_complete(system_prompt, user_prompt, **kwargs):
        calls.append(user_prompt)
        return "ток\nкто\nок"

    monkeypatch.setattr("services.word_builder.complete", fake_complete)

    settings = Settings(cache=CacheSettings(enabled=True, ttl_seconds=600))

    first = build_words("кот", settings=settings)
    second = build_words("кот", settings=settings)

    assert first.words == ["кто", "ток", "ок"]
    assert first.from_cache is False
    assert second.from_cache is True
    assert len(calls) == 1  # второй запрос обслужен кешем


def test_cache_key_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "services.word_builder.complete",
        lambda *args, **kwargs: calls.append("call") or "ток",
    )
    settings = Settings(cache=CacheSettings(enabled=True, ttl_seconds=600))

    build_words("Кот", settings=settings)
    build_words("  кот  ", settings=settings)

    assert len(calls) == 1


def test_cache_disabled_calls_llm_every_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "services.word_builder.complete",
        lambda *args, **kwargs: calls.append("call") or "ток",
    )
    settings = Settings(cache=CacheSettings(enabled=False))

    build_words("кот", settings=settings)
    build_words("кот", settings=settings)

    assert len(calls) == 2


def test_empty_result_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "services.word_builder.complete",
        lambda *args, **kwargs: calls.append("call") or "дом\nкошка",
    )
    settings = Settings(cache=CacheSettings(enabled=True, ttl_seconds=600))

    assert build_words("кот", settings=settings).words == []
    assert build_words("кот", settings=settings).words == []

    assert len(calls) == 2  # пустой результат не закеширован
