"""Ошибки слоя работы с LLM.

Иерархия позволяет различать ситуации и отдавать клиенту разные HTTP-статусы:

- :class:`LLMConfigError` — сервис не настроен или провайдер отклонил доступ
  (нет ключа, 401/403, неизвестная модель);
- :class:`LLMRequestRejectedError` — провайдер отклонил запрос (HTTP 4xx, кроме 401/403/429);
- :class:`LLMUnavailableError` — временная недоступность (таймаут, сеть, 5xx, 429);
  только такие ошибки имеет смысл повторять;
- :class:`LLMResponseError` — ответ получен, но невалиден (не JSON, нет `choices`, пустой текст).
"""

from __future__ import annotations


class LLMError(RuntimeError):
    """Базовая ошибка обращения к LLM."""


class LLMConfigError(LLMError):
    """Неверная конфигурация: нет ключа, доступ отклонён, неизвестная модель."""


class LLMRequestRejectedError(LLMError):
    """Провайдер отклонил запрос (HTTP 4xx)."""


class LLMUnavailableError(LLMError):
    """Временная недоступность LLM — операцию можно повторить."""


class LLMResponseError(LLMError):
    """Ответ модели невалиден или бесполезен."""


__all__ = [
    "LLMConfigError",
    "LLMError",
    "LLMRequestRejectedError",
    "LLMResponseError",
    "LLMUnavailableError",
]
