"""Тесты API-слоя: статусы ответа и валидация."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from api.server import app
from llm.errors import (
    LLMConfigError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from services.word_builder import BuildResult


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_build_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        routes,
        "build_words",
        lambda word: BuildResult(source=word, words=["кто", "ток"], from_cache=True),
    )

    response = client.post("/build", json={"word": "кот"})

    assert response.status_code == 200
    assert response.json() == {
        "word": "кот",
        "words": ["кто", "ток"],
        "total": 2,
        "from_cache": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"word": ""},
        {"word": "два слова"},
        {"word": "кот1"},
        {"word": "а" * 101},
        {},
    ],
)
def test_build_validation_returns_400(client: TestClient, payload: dict) -> None:
    response = client.post("/build", json=payload)
    assert response.status_code == 400
    assert "detail" in response.json()


def test_build_rejects_extra_field(client: TestClient) -> None:
    response = client.post("/build", json={"word": "кот", "extra": 1})
    assert response.status_code == 400


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (LLMConfigError("no key"), 503),
        (LLMUnavailableError("timeout"), 503),
        (LLMResponseError("bad json"), 502),
        (LLMRequestRejectedError("rejected"), 502),
    ],
)
def test_build_llm_errors_map_to_statuses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
) -> None:
    def failing(word):
        raise error

    monkeypatch.setattr(routes, "build_words", failing)

    response = client.post("/build", json={"word": "кот"})
    assert response.status_code == expected_status
    assert "detail" in response.json()


def test_build_unexpected_error_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(word):
        raise RuntimeError("boom")

    monkeypatch.setattr(routes, "build_words", failing)

    response = client.post("/build", json={"word": "кот"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервиса"}
