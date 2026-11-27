"""Точка входа Gradio-приложения «Наборщик» (Word Builder).

Запуск из корня рабочей папки (где лежит ``.venv``):

    .venv\\Scripts\\python.exe word_builder\\main.py

Логирование настраивается до создания интерфейса: консоль + JSON-файл
с ротацией. API-слой запускается отдельно:

    uvicorn api.server:app --app-dir word_builder
"""

from __future__ import annotations

import logging

from config.logging_config import setup_logging
from config.settings import get_settings

# Логирование — до импорта UI, чтобы сообщения Gradio тоже попадали в обработчики.
setup_logging()

from ui.gradio_app import create_app  # noqa: E402  (после setup_logging)

logger = logging.getLogger(__name__)


def main() -> None:
    """Создать и запустить Gradio-приложение."""
    settings = get_settings()
    logger.info(
        "Запуск Gradio-приложения «Наборщик» — env=%s, %s:%d",
        settings.app.env,
        settings.ui.host,
        settings.ui.port,
    )
    demo = create_app()
    demo.launch(
        server_name=settings.ui.host,
        server_port=settings.ui.port,
        share=settings.ui.share,
    )


if __name__ == "__main__":
    main()
