"""Централизованная настройка логирования проекта word_builder.

Возможности:

- консоль — читаемый текстовый формат;
- файл — структурированный JSON (один объект на строку) с ротацией;
- ``request_id`` в каждой записи: идентификатор кладётся в ``contextvars``
  (для API — middleware, для UI — обработчик кнопки), поэтому все сообщения
  одного запроса (UI/API → services → LLM) связаны;
- приглушение шумных логов сторонних библиотек.

Ключ LLM в логи не попадает: клиент пишет только имя модели и URL.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path

from config.settings import PROJECT_DIR, LoggingSettings, get_settings

DEFAULT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Идентификатор текущего запроса (``-`` вне запроса).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_configured = False
_original_record_factory = logging.getLogRecordFactory()
_record_factory_installed = False

#: Логгеры сторонних библиотек, которые логируют слишком подробно.
_NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "urllib3")


def _request_id_record_factory(*args, **kwargs) -> logging.LogRecord:
    """Фабрика записей: ``request_id`` доступен в любом обработчике и формате."""
    record = _original_record_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record


def _install_record_factory() -> None:
    """Установить фабрику записей один раз за процесс."""
    global _record_factory_installed
    if not _record_factory_installed:
        logging.setLogRecordFactory(_request_id_record_factory)
        _record_factory_installed = True


class RequestIdFilter(logging.Filter):
    """Добавляет в запись лога поле ``request_id`` из контекста."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """Структурированный формат лога: JSON-объект на строку."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def set_request_id(request_id: str) -> Token:
    """Установить идентификатор текущего запроса; вернуть токен для сброса."""
    return request_id_var.set(request_id)


def reset_request_id(token: Token) -> None:
    """Восстановить предыдущее значение идентификатора запроса."""
    request_id_var.reset(token)


def get_request_id() -> str:
    """Вернуть идентификатор текущего запроса (``-``, если его нет)."""
    return request_id_var.get()


def _resolve_level(level: str | int) -> int:
    """Преобразовать уровень логирования (``"INFO"``/``20``) в числовой код."""
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).strip().upper())
    if isinstance(resolved, int):
        return resolved
    raise ValueError(f"Неизвестный уровень логирования: {level!r}")


def _resolve_file_path(file_path: str) -> Path:
    """Относительный путь к лог-файлу трактуется от каталога ``word_builder/``."""
    path = Path(file_path)
    return path if path.is_absolute() else PROJECT_DIR / path


def _build_text_formatter(settings: LoggingSettings) -> logging.Formatter:
    return logging.Formatter(
        fmt=settings.format or DEFAULT_FORMAT,
        datefmt=settings.date_format or DEFAULT_DATE_FORMAT,
    )


def _remove_handlers(root: logging.Logger) -> None:
    """Снять обработчики; закрывать только созданные этим модулем."""
    for handler in list(root.handlers):
        root.removeHandler(handler)
        if getattr(handler, "_word_builder_handler", False):
            handler.close()


def _mark(handler: logging.Handler) -> logging.Handler:
    handler._word_builder_handler = True  # type: ignore[attr-defined]
    return handler


def _utf8_stream(stream):
    """Переключить консольный поток на UTF-8 с заменой непечатаемых символов."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    return stream


def setup_logging(
    settings: LoggingSettings | None = None,
    *,
    force: bool = False,
) -> logging.Logger:
    """Настроить корневой логгер: консоль + файл с ротацией.

    :param settings: параметры логирования (по умолчанию — из конфигурации)
    :param force: перенастроить логирование, даже если оно уже выполнено
    :returns: корневой логгер
    """
    global _configured

    if _configured and not force:
        return logging.getLogger()

    if settings is None:
        settings = get_settings().logging

    _install_record_factory()
    root = logging.getLogger()
    _remove_handlers(root)

    if not settings.enabled:
        root.addHandler(_mark(logging.NullHandler()))
        root.setLevel(logging.CRITICAL + 1)
        _configured = True
        return root

    level = _resolve_level(settings.level)
    root.setLevel(level)

    text_formatter = _build_text_formatter(settings)
    json_formatter = JsonFormatter()
    request_filter = RequestIdFilter()

    if settings.console:
        console = _mark(logging.StreamHandler(stream=_utf8_stream(sys.stdout)))
        console.setLevel(level)
        console.setFormatter(text_formatter)
        console.addFilter(request_filter)
        root.addHandler(console)

    if settings.file:
        path = _resolve_file_path(settings.file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = _mark(
                logging.handlers.RotatingFileHandler(
                    path,
                    maxBytes=settings.max_bytes,
                    backupCount=settings.backup_count,
                    encoding="utf-8",
                )
            )
        except OSError as exc:
            root.warning(
                "Не удалось открыть лог-файл %s (%s) — остаётся только консоль",
                path,
                exc,
            )
        else:
            file_handler.setLevel(level)
            file_handler.setFormatter(json_formatter if settings.json_file else text_formatter)
            file_handler.addFilter(request_filter)
            root.addHandler(file_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True
    root.debug(
        "Логирование настроено: level=%s, console=%s, file=%s, json=%s",
        settings.level,
        settings.console,
        _resolve_file_path(settings.file_path) if settings.file else "—",
        settings.json_file,
    )
    return root


def reset_logging() -> None:
    """Снять обработчики и сбросить состояние (тесты, повторная настройка)."""
    global _configured
    _remove_handlers(logging.getLogger())
    _configured = False


__all__ = [
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_FORMAT",
    "JsonFormatter",
    "RequestIdFilter",
    "get_request_id",
    "request_id_var",
    "reset_logging",
    "reset_request_id",
    "set_request_id",
    "setup_logging",
]
