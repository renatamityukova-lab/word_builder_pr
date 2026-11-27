"""Gradio-интерфейс игры «Наборщик» (Word Builder).

Поток: валидация ввода → бизнес-логика (кеш/LLM/фильтрация) → текст результата.
Сетевой вызов инкапсулирован в :mod:`llm.client`, UI его не дублирует.
"""

from __future__ import annotations

import logging
import time
import uuid

import gradio as gr

from config.logging_config import reset_request_id, set_request_id
from llm.errors import LLMError
from services.validation import MAX_WORD_LENGTH, validate_source_word
from services.word_builder import EMPTY_RESULT, build_words, fallback_message

logger = logging.getLogger(__name__)

TITLE = "Наборщик (Word Builder)"
DESCRIPTION = (
    "Введите слово — приложение покажет все слова, которые можно составить "
    "из его букв с учётом их количества. "
    "Первый запрос к новому слову может занять 15–30 секунд, "
    "повторный в течение 10 минут обслуживается из кеша."
)

EXAMPLES = [["простокваша"], ["библиотека"], ["праздник"]]


def handle_build(word: str) -> str:
    """Обработчик кнопки: валидация → кеш/LLM → отформатированный результат.

    Ошибки валидации возвращаются текстом и не доходят до LLM.
    При недоступности модели возвращается безопасный fallback-ответ.
    """
    token = set_request_id(uuid.uuid4().hex[:8])
    started = time.perf_counter()

    try:
        logger.info("UI: запрос — слово=%r", word)

        error = validate_source_word(word)
        if error:
            logger.warning("UI: ошибка валидации — %s", error)
            return error

        try:
            result = build_words(word)
        except LLMError as exc:
            message = fallback_message(exc)
            logger.error(
                "UI: fallback — %s: %s", type(exc).__name__, exc
            )
            return message

        if not result.words:
            logger.info("UI: пустой результат для %r", result.source)
            return EMPTY_RESULT

        header = f"Исходное слово: {result.source}"
        timing = (
            "из кеша"
            if result.from_cache
            else f"{result.elapsed_seconds:.1f} с"
        )
        body = "\n".join(result.words)

        logger.info(
            "UI: ответ — слов=%d за %.3f с",
            result.total,
            time.perf_counter() - started,
        )
        return f"{header}\nНайдено слов: {result.total} ({timing})\n\n{body}"
    finally:
        reset_request_id(token)


def create_app() -> gr.Blocks:
    """Собрать интерфейс: ввод → обработчик → вывод."""
    with gr.Blocks(title=TITLE) as demo:
        gr.Markdown(f"# {TITLE}\n{DESCRIPTION}")

        word_input = gr.Textbox(
            label="Исходное слово",
            placeholder="Например: простокваша",
            info=(
                f"Одно слово, только буквы, не более {MAX_WORD_LENGTH} символов. "
                "Повторный запрос того же слова — из кеша."
            ),
            lines=1,
            max_lines=1,
        )
        build_button = gr.Button("Составить слова", variant="primary")
        result_output = gr.Textbox(
            label="Найденные слова",
            lines=20,
            interactive=False,
        )

        gr.Examples(examples=EXAMPLES, inputs=word_input)

        build_button.click(
            fn=handle_build,
            inputs=word_input,
            outputs=result_output,
        )
        word_input.submit(
            fn=handle_build,
            inputs=word_input,
            outputs=result_output,
        )

    return demo


__all__ = ["EXAMPLES", "create_app", "handle_build"]
