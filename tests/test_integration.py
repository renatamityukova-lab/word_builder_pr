"""Сквозные тесты подтверждения работоспособности.

Проверяются четыре обязательных сценария через реальный HTTP-слой FastAPI
(``TestClient``), реальные ``services`` и ``cache``; подменяется только
внешний HTTP-клиент LLM (:class:`FakeClient`), поэтому сеть не используется.

1. Валидный запрос → успешный ответ ``200``.
2. Некорректный ввод → ошибка валидации ``400`` (до вызова LLM).
3. Сбой внешнего вызова → fallback на резервную модель; отключённый ключ → ``503``.
4. Повторный запрос → ответ из кеша, LLM не вызывается, в логе ``Кеш: попадание``.
"""

from __future__ import annotations

import logging
import time

import pytest
from fastapi.testclient import TestClient

import llm.client as llm_client
from api.server import app
from cache import reset_words_cache
from config.settings import CacheSettings, LLMSettings, Settings


class FakeResponse:
    """Минимальная замена ``httpx.Response`` для успешного ответа модели."""

    def __init__(self, status: int = 200, content: str = "ok") -> None:
        self.status_code = status
        self._content = content
        self.text = ""

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class FakeClient:
    """Подмена ``httpx.Client``: отдаёт заранее заданные исходы по порядку."""

    outcomes: list = []
    calls: list[str] = []
    delay: float = 0.0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def post(self, url, json=None):
        if FakeClient.delay:
            time.sleep(FakeClient.delay)
        FakeClient.calls.append(json["model"])
        outcome = FakeClient.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @classmethod
    def reset(cls, outcomes: list | None = None, delay: float = 0.0) -> None:
        cls.outcomes = list(outcomes or [])
        cls.calls = []
        cls.delay = delay


@pytest.fixture()
def settings() -> Settings:
    """Детерминированные настройки: не зависят от ``.env`` рабочей папки."""
    return Settings(
        llm=LLMSettings(
            api_key_env="OPENAI_API_KEY",
            model="primary",
            fallback_model="backup",
            max_retries=1,
            timeout_seconds=5,
            trust_env=False,
            base_url="https://example.test/v1",
            reasoning_effort=None,
        ),
        cache=CacheSettings(enabled=True, ttl_seconds=600, max_size=100),
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> TestClient:
    """TestClient с подменённым HTTP-клиентом LLM и чистым кешем."""
    reset_words_cache()
    FakeClient.reset()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("services.word_builder.get_settings", lambda: settings)
    monkeypatch.setattr(llm_client.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *_: None)

    yield TestClient(app, raise_server_exceptions=False)

    reset_words_cache()
    FakeClient.reset()


# --- 1. Корректный сценарий: валидный запрос → успешный ответ ---------------


def test_valid_request_returns_words(client: TestClient) -> None:
    FakeClient.reset([FakeResponse(200, "ток\nкто\nок")])

    response = client.post("/build", json={"word": "кот"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.json() == {
        "word": "кот",
        "words": ["кто", "ток", "ок"],
        "total": 3,
        "from_cache": False,
    }
    assert FakeClient.calls == ["primary"]


# --- 2. Ошибка ввода: некорректные данные → ошибка валидации ----------------


@pytest.mark.parametrize(
    "payload",
    [
        {"word": "два слова"},
        {"word": "кот1"},
        {"word": "я"},
        {"word": ""},
        {"word": "а" * 101},
    ],
)
def test_invalid_input_returns_400_without_llm(
    client: TestClient, payload: dict
) -> None:
    response = client.post("/build", json=payload)

    assert response.status_code == 400
    assert "detail" in response.json()
    assert "errors" in response.json()
    # Некорректный ввод не доходит до внешнего вызова.
    assert FakeClient.calls == []


# --- 3. Сбой внешнего вызова → fallback -------------------------------------


def test_primary_failure_falls_back_to_reserve_model(client: TestClient) -> None:
    # max_retries=1 → две попытки основной модели, затем резервная.
    FakeClient.reset([FakeResponse(500), FakeResponse(503), FakeResponse(200, "ток")])

    response = client.post("/build", json={"word": "кот"})

    assert response.status_code == 200
    assert response.json()["words"] == ["ток"]
    assert FakeClient.calls == ["primary", "primary", "backup"]


def test_disabled_api_key_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    response = client.post("/build", json={"word": "кот"})

    assert response.status_code == 503
    assert "LLM не настроена" in response.json()["detail"]
    # Без ключа внешний вызов не выполняется вовсе.
    assert FakeClient.calls == []


# --- 4. Кеш: повторный запрос быстрее и пишет cache hit в лог ---------------


def test_repeated_request_served_from_cache(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    FakeClient.reset([FakeResponse(200, "ток\nкто\nок")], delay=0.2)
    caplog.set_level(logging.INFO, logger="services.word_builder")

    started = time.perf_counter()
    first = client.post("/build", json={"word": "кот"})
    first_elapsed = time.perf_counter() - started

    started = time.perf_counter()
    second = client.post("/build", json={"word": "кот"})
    second_elapsed = time.perf_counter() - started

    assert first.status_code == second.status_code == 200
    assert first.json()["from_cache"] is False
    assert second.json()["from_cache"] is True
    assert second.json()["words"] == first.json()["words"]

    # LLM вызвана один раз: повторный запрос обслужен кешем.
    assert FakeClient.calls == ["primary"]
    # Повторный ответ заметно быстрее (в первом была искусственная задержка 0.2 с).
    assert second_elapsed < first_elapsed

    messages = [record.getMessage() for record in caplog.records]
    assert any("Кеш: попадание" in message for message in messages), messages
