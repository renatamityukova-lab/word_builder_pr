# Подтверждение работоспособности word_builder

Отчёт фиксирует проверку четырёх обязательных сценариев. Все сценарии
покрыты автоматическими тестами и прогоняются в CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Окружение и команды

| Параметр | Значение |
|----------|----------|
| ОС | Windows 10 |
| Python | 3.11 |
| Виртуальное окружение | `.venv` в корне проекта |

Команды выполняются из корня проекта (`word_builder/`):

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

**Фактический результат прогона (2026-11-27):**

```
145 passed in 18.38s
All checks passed!
```

## Матрица подтверждения сценариев

| № | Сценарий | Как проверяется | Тесты | Ожидаемый результат | Статус |
|---|----------|-----------------|-------|---------------------|--------|
| 1 | Корректный сценарий: валидный запрос → успешный ответ | `POST /build {"word": "кот"}` через `TestClient`; реальные `services` и `cache`, подменён только HTTP-клиент LLM | [`test_valid_request_returns_words`](tests/test_integration.py), [`test_build_success`](tests/test_api.py), [`test_build_words_filters_candidates`](tests/test_word_builder.py) | `200`, поля `word/words/total/from_cache`, заголовок `X-Request-ID`, `from_cache=false` | ✅ |
| 2 | Ошибка ввода: некорректные данные → ошибка валидации | Пустое слово, два слова, цифры, 1 буква, > 100 символов, лишнее поле, невалидный JSON | [`test_invalid_input_returns_400_without_llm`](tests/test_integration.py), [`test_build_validation_returns_400`](tests/test_api.py), [`test_build_rejects_extra_field`](tests/test_api.py), [`test_validation.py`](tests/test_validation.py) | `400`, `detail` + `errors`; LLM не вызывается (`FakeClient.calls == []`) | ✅ |
| 3 | Сбой внешнего вызова → fallback | Основная модель отвечает `500/503` → переключение на `fallback_model`; отключённый ключ → `LLMConfigError` → `503`; UI возвращает безопасный текст | [`test_primary_failure_falls_back_to_reserve_model`](tests/test_integration.py), [`test_disabled_api_key_returns_503`](tests/test_integration.py), [`test_fallback_model_used_after_primary_fails`](tests/test_llm_client.py), [`test_handle_build_returns_fallback`](tests/test_ui.py), [`test_fallback_message`](tests/test_word_builder.py) | Резервная модель отдаёт слова → `200`; без ключа → `503` без сетевого вызова; UI показывает `FALLBACK_*` | ✅ |
| 4 | Кеш: повторный запрос → быстрее и лог cache hit | Два одинаковых `POST /build`; в первом ответе LLM искусственно задержана на 0.2 с | [`test_repeated_request_served_from_cache`](tests/test_integration.py), [`test_builder_uses_cache`](tests/test_cache.py), [`test_cache_key_is_normalized`](tests/test_cache.py), [`test_expiration_by_ttl`](tests/test_cache.py) | Второй ответ `from_cache=true`, LLM вызвана 1 раз, второй запрос быстрее первого, в логе `Кеш: попадание — 'кот'` | ✅ |

## Детали сценария 3 (fallback)

1. **Резервная модель.** При `max_retries=1` основная модель вызывается дважды
   (HTTP 500 и 503), затем клиент переключается на `fallback_model` и получает
   успешный ответ. Последовательность вызовов в тесте:
   `["primary", "primary", "backup"]`.
2. **Отключённый ключ.** При пустой переменной `OPENAI_API_KEY`
   [`complete()`](llm/client.py) сразу возбуждает `LLMConfigError`, HTTP-клиент
   не создаётся; API отвечает `503` с `detail: "LLM не настроена: ..."`.
3. **UI.** [`handle_build()`](ui/gradio_app.py) перехватывает `LLMError` и
   возвращает короткий `fallback_message()` без технических деталей.

## Детали сценария 4 (кеш)

- Ключ кеша — нормализованное слово: `"Кот"`, `"  кот  "` и `"кот"` дают одно
  попадание ([`test_cache_key_is_normalized`](tests/test_cache.py)).
- Пустой результат не кешируется ([`test_empty_result_is_not_cached`](tests/test_cache.py)).
- TTL и вытеснение по размеру проверены с управляемыми часами
  ([`test_expiration_by_ttl`](tests/test_cache.py), [`test_max_size_evicts_oldest_expiring`](tests/test_cache.py)).
- Лог cache hit проверяется через `caplog`: запись
  `Кеш: попадание — 'кот', слов=N (…)` из
  [`build_words()`](services/word_builder.py).

## Дополнительно: гигиена секретов

Тесты [`tests/test_secrets.py`](tests/test_secrets.py) подтверждают, что ключ
не может попасть в публикуемый репозиторий:

- ни в одном файле проекта нет строк, похожих на ключ (`sk-…`, GitHub-токены,
  приватные ключи, `Bearer …`);
- `config/config*.yaml` хранят только имя переменной `api_key_env`;
- `.env.example` содержит заглушку `your_api_key_here`;
- `.gitignore` исключает `.env` (с сохранением `.env.example`), `logs/`,
  `__pycache__/`, `.venv/`, `.pytest_cache/`;
- `LLMSettings` не раскрывает ключ в `repr`/`model_dump`/`model_dump_json`.

Та же проверка вынесена в CI job `secrets`: она падает, если `.env` отслеживается
git или в файлах найдена строка, похожая на секрет.

## Ограничения проверки

- Реальный внешний LLM не вызывался: ключ в тестах не требуется, HTTP-клиент
  подменяется на `FakeClient`. Это проверяет всю логику сервиса (ретраи,
  fallback, статусы), но не качество ответов конкретной модели.
- Замер «быстрее» выполнен с искусственной задержкой 0.2 с в фейковом HTTP-клиенте,
  чтобы результат не зависел от скорости машины; в реальной эксплуатации
  выигрыш определяется временем ответа LLM (обычно 15–30 с против миллисекунд).
- Ручные проверки через Postman/скриншоты в этом проекте не прикладываются:
  подтверждение обеспечивается автоматическими тестами и прогоном в CI.
