"""Тесты клиента LLM: политика ретраев, типизация ошибок, fallback."""

from __future__ import annotations

import httpx
import pytest

import llm.client as llm_client
from config.settings import LLMSettings
from llm.errors import (
    LLMConfigError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)


class FakeResponse:
    def __init__(
        self, status: int = 200, content: str = "ok", raw_json=None, text: str = ""
    ) -> None:
        self.status_code = status
        self._content = content
        self._raw_json = raw_json
        self.text = text

    def json(self):
        if self._raw_json is not None:
            return self._raw_json
        return {"choices": [{"message": {"content": self._content}}]}


class FakeClient:
    """Подменяет httpx.Client: отдаёт заранее заданные исходы по порядку."""

    outcomes: list = []
    calls: list[str] = []
    payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *args) -> bool:
        return False

    def post(self, url, json=None):
        FakeClient.calls.append(json["model"])
        FakeClient.payloads.append(json)
        outcome = FakeClient.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _fake_http(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.outcomes = []
    FakeClient.calls = []
    FakeClient.payloads = []
    monkeypatch.setattr(llm_client.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_client.time, "sleep", lambda *_: None)
    monkeypatch.setenv("TEST_LLM_KEY", "test-key")


def make_llm(**overrides) -> LLMSettings:
    params = {
        "api_key_env": "TEST_LLM_KEY",
        "model": "primary",
        "fallback_model": None,
        "max_retries": 2,
        "timeout_seconds": 5,
        "trust_env": False,
        "base_url": "https://example.test/v1",
    }
    params.update(overrides)
    return LLMSettings(**params)


def test_retries_on_500_then_succeeds() -> None:
    FakeClient.outcomes = [FakeResponse(500), FakeResponse(200, "ток")]
    assert llm_client.complete("sys", "user", settings=make_llm()) == "ток"
    assert FakeClient.calls == ["primary", "primary"]


def test_payload_contains_limits_and_reasoning_effort() -> None:
    FakeClient.outcomes = [FakeResponse(200, "ок")]
    llm_client.complete("sys", "user", settings=make_llm())

    payload = FakeClient.payloads[0]
    assert payload["max_tokens"] == 1500
    assert payload["reasoning_effort"] == "low"


def test_reasoning_effort_omitted_when_disabled() -> None:
    FakeClient.outcomes = [FakeResponse(200, "ок")]
    llm_client.complete(
        "sys", "user", settings=make_llm(reasoning_effort=None)
    )

    assert "reasoning_effort" not in FakeClient.payloads[0]


def test_retries_on_429() -> None:
    FakeClient.outcomes = [FakeResponse(429), FakeResponse(200, "ok")]
    assert llm_client.complete("sys", "user", settings=make_llm()) == "ok"
    assert len(FakeClient.calls) == 2


def test_retries_on_timeout() -> None:
    FakeClient.outcomes = [httpx.ReadTimeout("timeout"), FakeResponse(200, "ok")]
    assert llm_client.complete("sys", "user", settings=make_llm()) == "ok"
    assert len(FakeClient.calls) == 2


def test_no_retry_on_403() -> None:
    FakeClient.outcomes = [FakeResponse(403)]
    with pytest.raises(LLMConfigError, match="доступ отклонён"):
        llm_client.complete("sys", "user", settings=make_llm())
    assert len(FakeClient.calls) == 1


def test_no_retry_on_400() -> None:
    FakeClient.outcomes = [FakeResponse(400, text="bad model")]
    with pytest.raises(LLMRequestRejectedError, match="запрос отклонён"):
        llm_client.complete("sys", "user", settings=make_llm())
    assert len(FakeClient.calls) == 1


def test_invalid_json_is_not_retried() -> None:
    FakeClient.outcomes = [FakeResponse(200, raw_json={"unexpected": True})]
    with pytest.raises(LLMResponseError, match="формат ответа"):
        llm_client.complete("sys", "user", settings=make_llm())
    assert len(FakeClient.calls) == 1


def test_empty_content_is_not_retried() -> None:
    FakeClient.outcomes = [FakeResponse(200, "   ")]
    with pytest.raises(LLMResponseError, match="пустой ответ"):
        llm_client.complete("sys", "user", settings=make_llm())
    assert len(FakeClient.calls) == 1


def test_all_attempts_exhausted_raises_unavailable() -> None:
    FakeClient.outcomes = [FakeResponse(500), FakeResponse(502), FakeResponse(503)]
    with pytest.raises(LLMUnavailableError, match="после 3 попыток"):
        llm_client.complete("sys", "user", settings=make_llm(max_retries=2))
    assert len(FakeClient.calls) == 3


def test_fallback_model_used_after_primary_fails() -> None:
    FakeClient.outcomes = [FakeResponse(500), FakeResponse(200, "from_fallback")]
    result = llm_client.complete(
        "sys", "user", settings=make_llm(max_retries=0, fallback_model="backup")
    )
    assert result == "from_fallback"
    assert FakeClient.calls == ["primary", "backup"]


def test_missing_api_key_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_LLM_KEY", raising=False)
    with pytest.raises(LLMConfigError, match="LLM не настроена"):
        llm_client.complete("sys", "user", settings=make_llm())
    assert FakeClient.calls == []


def test_config_error_takes_priority_over_unavailable() -> None:
    FakeClient.outcomes = [FakeResponse(403), FakeResponse(500)]
    with pytest.raises(LLMConfigError):
        llm_client.complete(
            "sys", "user", settings=make_llm(max_retries=0, fallback_model="backup")
        )
    assert FakeClient.calls == ["primary", "backup"]
