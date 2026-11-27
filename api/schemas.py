"""Pydantic-схемы API-слоя (запрос/ответ эндпоинта «Наборщика»)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.validation import MAX_WORD_LENGTH, validate_source_word


class BuildRequest(BaseModel):
    """Запрос на подбор слов.

    ``word`` — одно слово (только буквы), не длиннее 100 символов.
    Пробелы по краям обрезаются, пустое значение и несколько слов отклоняются.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    word: str = Field(
        ...,
        min_length=1,
        max_length=MAX_WORD_LENGTH,
        description="Исходное слово, например простокваша",
        examples=["простокваша"],
    )

    @field_validator("word")
    @classmethod
    def _check_word(cls, value: str) -> str:
        error = validate_source_word(value)
        if error:
            raise ValueError(error)
        return value


class BuildResponse(BaseModel):
    """Результат подбора слов."""

    word: str = Field(..., description="Исходное слово после нормализации")
    words: list[str] = Field(..., description="Найденные слова (по убыванию длины)")
    total: int = Field(..., description="Количество найденных слов")
    from_cache: bool = Field(..., description="Ответ получен из кеша")


__all__ = ["BuildRequest", "BuildResponse"]
