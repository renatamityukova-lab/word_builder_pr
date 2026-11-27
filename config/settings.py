"""Загрузка конфигурации: базовый YAML + профиль окружения + переопределения.

Источники и приоритет (сверху — важнее):

1. переменные окружения (``.env`` или окружение процесса);
2. профиль ``config/config.<APP_ENV>.yaml`` (``dev`` | ``prod``);
3. базовый ``config/config.yaml``;
4. значения по умолчанию из моделей Pydantic.

Профиль выбирается переменной ``APP_ENV`` (по умолчанию ``dev``).
Секреты в YAML не хранятся — только имя переменной окружения с ключом.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

#: Базовый файл с общими значениями.
BASE_CONFIG_PATH = BASE_DIR / "config.yaml"
#: Обратная совместимость: раньше базовый файл назывался просто CONFIG_PATH.
CONFIG_PATH = BASE_CONFIG_PATH
#: Локальный файл с секретами (не коммитится).
ENV_PATH = PROJECT_DIR / ".env"

#: Поддерживаемые профили окружения.
SUPPORTED_ENVS = ("dev", "prod")
#: Профиль по умолчанию, если APP_ENV не задан.
DEFAULT_ENV = "dev"

#: Значение по умолчанию для URL LLM — единственный источник в проекте.
DEFAULT_BASE_URL = "https://llm.enplus.group/v1"


class AppSettings(BaseModel):
    """Параметры API-слоя."""

    model_config = ConfigDict(extra="ignore")

    name: str = "word_builder"
    env: str = DEFAULT_ENV
    host: str = "127.0.0.1"
    port: int = 8000


class UISettings(BaseModel):
    """Параметры запуска Gradio-интерфейса."""

    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 7860
    share: bool = False


class LLMSettings(BaseModel):
    """Параметры подключения к LLM."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "openai"
    model: str = "gpt-oss-120b"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    trust_env: bool = True
    fallback_model: str | None = None
    fallback_base_url: str | None = None
    temperature: float = 0.0
    timeout_seconds: float = 60.0
    max_retries: int = 1
    max_tokens: int = 1500
    max_words: int = 100
    reasoning_effort: str | None = "low"

    @property
    def api_key(self) -> str | None:
        """Ключ доступа к LLM из переменной окружения (``None``, если не задан)."""
        return os.getenv(self.api_key_env, "").strip() or None

    @property
    def api_url(self) -> str:
        """URL метода chat/completions."""
        base = (self.base_url or DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/chat/completions"


class CacheSettings(BaseModel):
    """Параметры кеша результатов."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    backend: str = "memory"
    ttl_seconds: int = 600
    max_size: int = 5000


class LoggingSettings(BaseModel):
    """Параметры логирования: консоль и файл с ротацией."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    level: str = "INFO"
    console: bool = True
    file: bool = True
    file_path: str = "logs/word_builder.log"
    json_file: bool = True
    max_bytes: int = 5_000_000
    backup_count: int = 5
    format: str = (
        "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s"
    )
    date_format: str = "%Y-%m-%d %H:%M:%S"


class BuilderSettings(BaseModel):
    """Правила формирования списка слов."""

    model_config = ConfigDict(extra="ignore")

    max_input_length: int = 100
    min_word_length: int = 2
    max_results: int = 300


class Settings(BaseModel):
    """Корневые настройки приложения."""

    model_config = ConfigDict(extra="ignore")

    app: AppSettings = AppSettings()
    ui: UISettings = UISettings()
    llm: LLMSettings = LLMSettings()
    cache: CacheSettings = CacheSettings()
    logging: LoggingSettings = LoggingSettings()
    builder: BuilderSettings = BuilderSettings()


def _read_yaml(path: Path) -> dict[str, Any]:
    """Прочитать YAML-конфигурацию (пустой словарь, если файла нет)."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно объединить словари: значения ``override`` важнее."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_env_name() -> str:
    """Имя профиля из ``APP_ENV`` (``dev``, если переменная не задана)."""
    return (os.getenv("APP_ENV") or "").strip().lower() or DEFAULT_ENV


def resolve_config_path(env_name: str) -> Path:
    """Путь к YAML-профилю окружения (``config/config.<env>.yaml``).

    :raises ValueError: профиль не входит в :data:`SUPPORTED_ENVS`
    """
    if env_name not in SUPPORTED_ENVS:
        supported = ", ".join(SUPPORTED_ENVS)
        raise ValueError(
            f"Неизвестное окружение APP_ENV={env_name!r}; допустимые: {supported}"
        )
    return BASE_DIR / f"config.{env_name}.yaml"


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Переопределить значения из YAML переменными окружения (пустые игнорируются)."""
    llm = data.setdefault("llm", {})
    cache = data.setdefault("cache", {})
    app = data.setdefault("app", {})
    ui = data.setdefault("ui", {})
    log = data.setdefault("logging", {})
    builder = data.setdefault("builder", {})

    mapping: dict[str, tuple[dict[str, Any], str]] = {
        "LLM_PROVIDER": (llm, "provider"),
        "LLM_MODEL": (llm, "model"),
        "LLM_BASE_URL": (llm, "base_url"),
        "LLM_TRUST_ENV": (llm, "trust_env"),
        "LLM_FALLBACK_MODEL": (llm, "fallback_model"),
        "LLM_FALLBACK_BASE_URL": (llm, "fallback_base_url"),
        "LLM_TIMEOUT_SECONDS": (llm, "timeout_seconds"),
        "LLM_MAX_RETRIES": (llm, "max_retries"),
        "LLM_MAX_TOKENS": (llm, "max_tokens"),
        "LLM_MAX_WORDS": (llm, "max_words"),
        "LLM_REASONING_EFFORT": (llm, "reasoning_effort"),
        "CACHE_ENABLED": (cache, "enabled"),
        "CACHE_BACKEND": (cache, "backend"),
        "CACHE_TTL_SECONDS": (cache, "ttl_seconds"),
        "CACHE_MAX_SIZE": (cache, "max_size"),
        "APP_HOST": (app, "host"),
        "APP_PORT": (app, "port"),
        "UI_HOST": (ui, "host"),
        "UI_PORT": (ui, "port"),
        "UI_SHARE": (ui, "share"),
        "LOG_ENABLED": (log, "enabled"),
        "LOG_LEVEL": (log, "level"),
        "LOG_CONSOLE": (log, "console"),
        "LOG_FILE": (log, "file"),
        "LOG_FILE_PATH": (log, "file_path"),
        "LOG_JSON_FILE": (log, "json_file"),
        "LOG_MAX_BYTES": (log, "max_bytes"),
        "LOG_BACKUP_COUNT": (log, "backup_count"),
        "LOG_FORMAT": (log, "format"),
        "BUILDER_MAX_INPUT_LENGTH": (builder, "max_input_length"),
        "BUILDER_MIN_WORD_LENGTH": (builder, "min_word_length"),
        "BUILDER_MAX_RESULTS": (builder, "max_results"),
    }

    for env_name, (target, key) in mapping.items():
        raw = os.getenv(env_name)
        if raw is None or not raw.strip():
            continue
        target[key] = raw.strip()

    return data


def _load_config(env_name: str) -> dict[str, Any]:
    """Собрать конфигурацию: базовый YAML + профиль + переменные окружения.

    :raises FileNotFoundError: профиль окружения отсутствует
    """
    data = _read_yaml(BASE_CONFIG_PATH)
    profile_path = resolve_config_path(env_name)
    if not profile_path.exists():
        raise FileNotFoundError(
            f"Не найден файл конфигурации окружения {env_name!r}: {profile_path}. "
            "Проверьте APP_ENV и наличие config/config.<env>.yaml."
        )
    data = _deep_merge(data, _read_yaml(profile_path))
    data.setdefault("app", {})["env"] = env_name
    return _apply_env_overrides(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Собрать настройки приложения (кешируется на время жизни процесса).

    Профиль определяется переменной ``APP_ENV``; значения ``.env`` и окружения
    процесса имеют приоритет над YAML. Для перечитывания используйте
    ``get_settings.cache_clear()``.
    """
    load_dotenv(ENV_PATH, override=False)
    return Settings.model_validate(_load_config(resolve_env_name()))
