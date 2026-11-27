"""Работа с LLM: клиент API, промпты и типизированные ошибки."""

from llm.client import complete
from llm.errors import (
    LLMConfigError,
    LLMError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from llm.prompts import SYSTEM_PROMPT, build_messages, build_user_prompt

__all__ = [
    "LLMConfigError",
    "LLMError",
    "LLMRequestRejectedError",
    "LLMResponseError",
    "LLMUnavailableError",
    "SYSTEM_PROMPT",
    "build_messages",
    "build_user_prompt",
    "complete",
]
