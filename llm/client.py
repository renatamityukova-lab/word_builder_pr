"""Клиент LLM API (chat/completions): timeout, retry и fallback-модель.

Политика ретраев: повторяются **только временные** ошибки
(:class:`LLMUnavailableError` — таймаут, сетевая ошибка, HTTP 429 и 5xx).
Ошибки конфигурации (401/403), отклонённые запросы (прочие 4xx) и невалидные
ответы модели не повторяются — сразу пробрасываются наверх.

Порядок работы :func:`complete`:
1. основная модель — до ``max_retries + 1`` попыток с экспоненциальной паузой;
2. если задана ``fallback_model`` — те же попытки на резервной модели;
3. если недоступны обе — типизированная :class:`LLMError` со списком причин.

Ключ доступа используется только в заголовке ``Authorization`` и никогда
не пишется в логи и тексты ошибок.
"""

from __future__ import annotations

import logging
import time

import httpx

from config.settings import DEFAULT_BASE_URL, LLMSettings, get_settings
from llm.errors import (
    LLMConfigError,
    LLMError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)


def _chat_completions_url(base_url: str | None) -> str:
    """Собрать URL метода chat/completions.

    ``DEFAULT_BASE_URL`` берётся из :mod:`config.settings` — единственного
    источника значения по умолчанию в проекте.
    """
    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/chat/completions"


def _body_snippet(response: httpx.Response, limit: int = 200) -> str:
    """Короткий фрагмент тела ответа для сообщения об ошибке."""
    try:
        return response.text[:limit].replace("\n", " ")
    except Exception:  # noqa: BLE001 — тело может быть недоступно
        return "<тело недоступно>"


def _call_once(
    client: httpx.Client,
    url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None = None,
) -> str:
    """Один запрос к модели (без ретраев). Все ошибки — типизированные."""
    payload: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    # Для reasoning-моделей: меньше скрытых рассуждений — быстрее ответ.
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    logger.info(
        "LLM: запрос — model=%s, POST %s, temperature=%s, max_tokens=%d, "
        "reasoning_effort=%s, промпт %d символов",
        model,
        url,
        temperature,
        max_tokens,
        reasoning_effort or "—",
        len(user_prompt),
    )
    logger.debug("LLM: промпты — system=%r, user=%r", system_prompt, user_prompt)

    started = time.perf_counter()

    try:
        response = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        logger.warning(
            "LLM: таймаут запроса — model=%s, url=%s, %.3f с",
            model,
            url,
            time.perf_counter() - started,
        )
        raise LLMUnavailableError(f"{model}: таймаут запроса") from exc
    except httpx.TransportError as exc:
        logger.warning(
            "LLM: сетевая ошибка — model=%s, %s: %s",
            model,
            type(exc).__name__,
            exc,
        )
        raise LLMUnavailableError(
            f"{model}: сетевая ошибка ({type(exc).__name__})"
        ) from exc

    status = response.status_code
    elapsed = time.perf_counter() - started

    if status == 429 or status >= 500:
        logger.warning(
            "LLM: временная ошибка HTTP %s — model=%s, %.3f с (возможен повтор)",
            status,
            model,
            elapsed,
        )
        raise LLMUnavailableError(f"{model}: временная ошибка HTTP {status}")
    if status in (401, 403):
        logger.error(
            "LLM: доступ отклонён HTTP %s — model=%s (проверьте ключ и имя модели)",
            status,
            model,
        )
        raise LLMConfigError(
            f"{model}: доступ отклонён (HTTP {status}) — проверьте ключ и имя модели"
        )
    if status >= 400:
        logger.error(
            "LLM: запрос отклонён HTTP %s — model=%s: %s",
            status,
            model,
            _body_snippet(response),
        )
        raise LLMRequestRejectedError(
            f"{model}: запрос отклонён (HTTP {status}): {_body_snippet(response)}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        logger.error(
            "LLM: ответ не является JSON — model=%s, HTTP %s, %.3f с",
            model,
            status,
            elapsed,
        )
        raise LLMResponseError(f"{model}: ответ не является JSON") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.error(
            "LLM: неожиданный формат ответа — model=%s (нет choices/message/content)",
            model,
        )
        raise LLMResponseError(
            f"{model}: неожиданный формат ответа (нет choices/message/content)"
        ) from exc

    if not isinstance(content, str) or not content.strip():
        logger.error("LLM: пустой ответ — model=%s, HTTP %s", model, status)
        raise LLMResponseError(f"{model}: модель вернула пустой ответ")

    logger.info(
        "LLM: ответ — model=%s, HTTP %s, %.3f с, %d символов",
        model,
        status,
        elapsed,
        len(content),
    )
    logger.debug("LLM: содержимое ответа (%s): %r", model, content)

    return content


def _complete_with_retries(
    client: httpx.Client,
    url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None,
    attempts: int,
) -> str:
    """Запрос к одной модели: ретраи только для временных ошибок."""
    last_error: LLMError | None = None

    for attempt in range(attempts):
        logger.info("LLM: попытка %d/%d — model=%s", attempt + 1, attempts, model)
        try:
            return _call_once(
                client,
                url,
                model,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                reasoning_effort,
            )
        except LLMUnavailableError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                delay = min(2**attempt, 5)
                logger.warning(
                    "LLM: попытка %d/%d не удалась (%s) — повтор через %d с",
                    attempt + 1,
                    attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

    logger.error(
        "LLM: model=%s недоступна после %d попыток (%s)",
        model,
        attempts,
        last_error,
    )
    raise LLMUnavailableError(
        f"{model}: недоступна после {attempts} попыток ({last_error})"
    ) from last_error


def complete(
    system_prompt: str,
    user_prompt: str,
    *,
    settings: LLMSettings | None = None,
) -> str:
    """Отправить промпты в LLM и вернуть текст ответа.

    Использует основную модель, при её недоступности — ``fallback_model``.

    :raises LLMConfigError: не задан ключ, провайдер отклонил доступ
    :raises LLMRequestRejectedError: провайдер отклонил запрос (4xx)
    :raises LLMResponseError: модель вернула невалидный/пустой ответ
    :raises LLMUnavailableError: недоступны и основная, и резервная модели
    """
    llm = settings or get_settings().llm

    logger.info(
        "LLM: старт — model=%s, fallback=%s, попыток=%d, timeout=%s с, "
        "max_tokens=%d, reasoning_effort=%s",
        llm.model,
        llm.fallback_model or "—",
        llm.max_retries + 1,
        llm.timeout_seconds,
        llm.max_tokens,
        llm.reasoning_effort or "—",
    )

    api_key = llm.api_key
    if not api_key:
        logger.error(
            "LLM не настроена: переменная %s не заполнена в .env", llm.api_key_env
        )
        raise LLMConfigError(
            f"LLM не настроена: заполните переменную {llm.api_key_env} в файле .env"
        )

    targets: list[tuple[str, str]] = [(llm.model, _chat_completions_url(llm.base_url))]
    if llm.fallback_model:
        targets.append(
            (
                llm.fallback_model,
                _chat_completions_url(llm.fallback_base_url or llm.base_url),
            )
        )

    attempts = llm.max_retries + 1
    errors: list[LLMError] = []

    with httpx.Client(
        timeout=llm.timeout_seconds,
        trust_env=llm.trust_env,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    ) as client:
        for index, (model, url) in enumerate(targets, start=1):
            if index > 1:
                logger.warning(
                    "LLM: переключение на резервную модель %s (%s)", model, url
                )
            try:
                content = _complete_with_retries(
                    client,
                    url,
                    model,
                    system_prompt,
                    user_prompt,
                    llm.temperature,
                    llm.max_tokens,
                    llm.reasoning_effort,
                    attempts,
                )
                logger.info("LLM: успешный ответ от модели %s", model)
                return content
            except LLMError as exc:
                errors.append(exc)
                logger.warning("LLM: модель %s не дала результат: %s", model, exc)

    summary = "; ".join(str(error) for error in errors)
    logger.error("LLM: все модели недоступны — %s", summary)

    # Если были не временные ошибки — сообщаем именно их (они точнее описывают причину).
    for error in errors:
        if not isinstance(error, LLMUnavailableError):
            raise type(error)(f"Не удалось получить слова — {summary}") from error

    raise LLMUnavailableError(f"Все модели недоступны — {summary}") from errors[-1]


__all__ = ["complete"]
