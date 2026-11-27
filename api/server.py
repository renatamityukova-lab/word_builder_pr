"""FastAPI-приложение «Наборщика» с корректными HTTP-статусами.

Запуск из корня рабочей папки:

    uvicorn api.server:app --app-dir word_builder --reload

Коды ошибок:

- ``400`` — некорректный запрос (валидация полей);
- ``502`` — провайдер LLM отклонил запрос или вернул невалидный ответ;
- ``503`` — LLM не настроена или временно недоступна;
- ``500`` — непредвиденная внутренняя ошибка.
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api import router
from api.schemas import BuildRequest  # noqa: F401  (документирует схему в OpenAPI)
from config.logging_config import reset_request_id, set_request_id, setup_logging
from llm.errors import (
    LLMConfigError,
    LLMError,
    LLMRequestRejectedError,
    LLMResponseError,
    LLMUnavailableError,
)
from services.validation import MAX_WORD_LENGTH

# Логирование настраивается до создания приложения: консоль + JSON-файл.
setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Word Builder",
    description=(
        "Игра «Наборщик»: поиск всех слов, которые можно составить "
        "из букв исходного слова с учётом их количества."
    ),
    version="0.1.0",
)

app.include_router(router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логировать начало, завершение и ошибки каждого HTTP-запроса."""
    request_id = uuid.uuid4().hex[:8]
    token = set_request_id(request_id)
    started = time.perf_counter()
    query = f"?{request.url.query}" if request.url.query else ""
    logger.info(
        "→ %s %s%s — запрос начат (client=%s)",
        request.method,
        request.url.path,
        query,
        request.client.host if request.client else "-",
    )

    try:
        response = await call_next(request)
    except Exception:
        duration = time.perf_counter() - started
        logger.exception(
            "✖ %s %s — необработанная ошибка за %.3f с",
            request.method,
            request.url.path,
            duration,
        )
        raise
    else:
        duration = time.perf_counter() - started
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "← %s %s — %s за %.3f с",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response
    finally:
        reset_request_id(token)


_VALIDATION_MESSAGES = {
    "missing": "обязательное поле",
    "string_type": "должно быть строкой",
    "string_too_short": "не должно быть пустым",
    "string_too_long": f"длина не должна превышать {MAX_WORD_LENGTH} символов",
    "extra_forbidden": "лишнее поле не допускается",
    "json_invalid": "тело запроса должно быть корректным JSON",
    "model_attributes_type": "тело запроса должно быть объектом JSON",
}


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    """Превратить ошибки Pydantic в понятный список «поле — сообщение»."""
    details: list[dict[str, str]] = []
    for error in exc.errors():
        location = error.get("loc", ())
        parts = [
            str(part)
            for part in location
            if part != "body" and not isinstance(part, int)
        ]
        field = ".".join(parts) or "body"
        error_type = str(error.get("type", ""))
        raw_message = str(error.get("msg", "некорректное значение"))
        if error_type == "value_error":
            message = raw_message.removeprefix("Value error, ")
        else:
            message = _VALIDATION_MESSAGES.get(error_type, raw_message)
        details.append({"field": field, "message": message})
    return details


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Ошибки входных данных — 400 с осмысленным текстом."""
    details = _validation_details(exc)
    summary = "; ".join(f"{item['field']}: {item['message']}" for item in details)
    summary = summary or "некорректные данные"
    logger.warning("400 %s %s — %s", request.method, request.url.path, summary)
    return JSONResponse(
        status_code=400,
        content={"detail": f"Некорректный запрос — {summary}", "errors": details},
    )


@app.exception_handler(LLMConfigError)
async def llm_config_handler(request: Request, exc: LLMConfigError) -> JSONResponse:
    """LLM не настроена (нет ключа, доступ отклонён) — 503."""
    logger.error("503 LLM config: %s", exc)
    return JSONResponse(status_code=503, content={"detail": f"LLM не настроена: {exc}"})


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(
    request: Request, exc: LLMUnavailableError
) -> JSONResponse:
    """Временная недоступность модели — 503 (запрос можно повторить позже)."""
    logger.error("503 LLM unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": f"Модель временно недоступна: {exc}"},
    )


@app.exception_handler(LLMResponseError)
async def llm_response_handler(
    request: Request, exc: LLMResponseError
) -> JSONResponse:
    """Модель ответила невалидно — 502."""
    logger.error("502 LLM response: %s", exc)
    return JSONResponse(
        status_code=502, content={"detail": f"Некорректный ответ модели: {exc}"}
    )


@app.exception_handler(LLMRequestRejectedError)
async def llm_rejected_handler(
    request: Request, exc: LLMRequestRejectedError
) -> JSONResponse:
    """Провайдер отклонил запрос (4xx) — 502."""
    logger.error("502 LLM rejected: %s", exc)
    return JSONResponse(
        status_code=502, content={"detail": f"Провайдер LLM отклонил запрос: {exc}"}
    )


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    """Прочие ошибки LLM — 502."""
    logger.error("502 LLM error: %s", exc)
    return JSONResponse(status_code=502, content={"detail": f"Ошибка LLM: {exc}"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Непредвиденная ошибка — 500 без раскрытия внутренних деталей."""
    logger.exception("500 при обработке %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервиса"})


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Проверка работоспособности сервиса."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    from config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "api.server:app",
        host=settings.app.host,
        port=settings.app.port,
        # Автоперезагрузка — только в dev; в prod она вредна и небезопасна.
        reload=settings.app.env == "dev",
    )
