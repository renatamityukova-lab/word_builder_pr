"""Гигиена секретов: ключ LLM живёт только в ``.env`` и не попадает в репозиторий.

Тесты не читают реальный ``.env`` и не обращаются к сети. Проверяется, что:

- в исходниках, конфигурации, документации и CI нет строк, похожих на ключ;
- YAML-профили содержат только имя переменной (``api_key_env``), а не сам ключ;
- шаблон ``.env.example`` содержит заглушку, а не реальный ключ;
- ``.gitignore`` исключает ``.env``, логи и служебные каталоги;
- объект настроек LLM не раскрывает ключ в ``repr``/``model_dump``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from config.settings import LLMSettings

PROJECT_DIR = Path(__file__).resolve().parents[1]

#: Каталоги, которые не сканируются: служебные и с артефактами.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "logs",
    "node_modules",
}
#: Реальный файл с секретом не сканируется и не должен попадать в git.
SKIP_FILES = {".env"}

#: Расширения и имена файлов, которые проверяются на секреты.
SCAN_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".txt",
    ".cfg",
    ".json",
}
SCAN_NAMES = {".gitignore", ".gitattributes", ".env.example"}

#: Шаблоны, по которым распознаются реальные ключи и токены.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|token)\b\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9._-]{24,}"
    ),
)

#: Значения-заглушки, допустимые в ``.env.example``.
PLACEHOLDER_API_KEY = "your_api_key_here"


def _iter_project_files() -> Iterator[Path]:
    """Перебрать файлы проекта, которые имеет смысл проверять на секреты."""
    for path in PROJECT_DIR.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(PROJECT_DIR)
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix.lower() in SCAN_SUFFIXES or path.name in SCAN_NAMES:
            yield path


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_DIR).as_posix()


@pytest.mark.parametrize("path", list(_iter_project_files()), ids=_relative)
def test_no_secret_like_strings_in_repository(path: Path) -> None:
    """Ни один файл репозитория не содержит строк, похожих на реальный ключ."""
    text = path.read_text(encoding="utf-8", errors="ignore")

    for pattern in SECRET_PATTERNS:
        assert pattern.search(text) is None, (
            f"{_relative(path)}: найдена строка, похожая на секрет "
            f"(шаблон {pattern.pattern!r}). Ключ должен храниться только в .env."
        )


def test_env_example_contains_placeholder_only() -> None:
    """Шаблон ``.env.example`` содержит заглушку и не содержит реального ключа."""
    text = (PROJECT_DIR / ".env.example").read_text(encoding="utf-8")

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        values[name.strip()] = value.strip()

    assert values.get("OPENAI_API_KEY") == PLACEHOLDER_API_KEY
    assert not any(pattern.search(text) for pattern in SECRET_PATTERNS)


@pytest.mark.parametrize(
    "name", ["config.yaml", "config.dev.yaml", "config.prod.yaml"]
)
def test_yaml_configs_store_no_secret_values(name: str) -> None:
    """YAML-профили хранят только имя переменной с ключом, но не сам ключ."""
    data: Any = yaml.safe_load(
        (PROJECT_DIR / "config" / name).read_text(encoding="utf-8")
    )

    secret_leaf_names = {"api_key", "apikey", "token", "secret", "password"}
    for key, value in _walk_leaves(data):
        leaf = key.rsplit(".", 1)[-1].lower()
        if leaf in secret_leaf_names:
            assert value in (None, ""), (
                f"{name}: секрет не должен храниться в конфигурации ({key})"
            )


def test_base_config_references_api_key_variable_only() -> None:
    """Базовый конфиг знает только имя переменной с ключом."""
    data: Any = yaml.safe_load(
        (PROJECT_DIR / "config" / "config.yaml").read_text(encoding="utf-8")
    )

    assert data["llm"]["api_key_env"] == "OPENAI_API_KEY"
    assert "api_key" not in data["llm"]


def test_gitignore_protects_env_logs_and_artifacts() -> None:
    """``.gitignore`` исключает секреты, логи и служебные каталоги."""
    text = (PROJECT_DIR / ".gitignore").read_text(encoding="utf-8")

    required = (
        ".env",
        "!.env.example",
        "logs/",
        "__pycache__/",
        ".pytest_cache/",
        ".venv/",
    )
    for pattern in required:
        assert pattern in text, f".gitignore не содержит правило {pattern!r}"


def test_llm_settings_do_not_expose_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключ доступен через свойство, но не попадает в repr/дампы настроек."""
    secret = "sk-" + "a" * 40
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    llm = LLMSettings()

    assert llm.api_key == secret
    for dump in (repr(llm), str(llm.model_dump()), llm.model_dump_json()):
        assert secret not in dump


def _walk_leaves(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Обойти вложенный YAML и вернуть пары «путь — скалярное значение»."""
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            yield from _walk_leaves(value, child)
    else:
        yield prefix, node
