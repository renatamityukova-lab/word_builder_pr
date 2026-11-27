"""Эндпоинты API «Наборщика».

Роутеры только принимают и валидируют запрос, затем делегируют работу
в слой ``services``. Обращений к LLM и кешу на этом уровне нет.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter

from api.schemas import BuildRequest, BuildResponse
from services.word_builder import build_words

logger = logging.getLogger(__name__)

router = APIRouter(tags=["builder"])


@router.post(
    "/build",
    response_model=BuildResponse,
    summary="Составить слова из букв исходного слова",
    description=(
        "Принимает одно слово (только буквы, до 100 символов) и возвращает "
        "все слова, которые можно составить из его букв с учётом количества. "
        "Повторный запрос в течение 10 минут обслуживается из кеша."
    ),
)
def build(payload: BuildRequest) -> BuildResponse:
    """Подобрать слова для исходного слова."""
    started = time.perf_counter()
    logger.info(
        "POST /build — запрос: word=%r (длина %d)",
        payload.word,
        len(payload.word),
    )

    result = build_words(payload.word)

    logger.info(
        "POST /build — ответ: слов=%d, from_cache=%s за %.3f с",
        result.total,
        result.from_cache,
        time.perf_counter() - started,
    )
    return BuildResponse(
        word=result.source,
        words=result.words,
        total=result.total,
        from_cache=result.from_cache,
    )


__all__ = ["router"]
