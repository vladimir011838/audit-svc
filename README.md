# audit-svc

Учебный сервис: принимает по HTTP события аудита («кто, что и в каком приложении сделал») и сохраняет их в PostgreSQL. Написан на Python (aiohttp + asyncpg), собирается Poetry, как и `counter-backend`.

## API

| Метод  | Путь          | Ответ |
|--------|---------------|-------|
| `POST` | `/api/events` | `201 {"id": N}`: событие сохранено; `400`: некорректное тело; `503`: БД недоступна |
| `GET`  | `/api/events?app=billing&limit=50` | `200 {"events": [...]}`: последние события, фильтр по приложению необязателен, `limit` от 1 до 500 |
| `GET`  | `/healthz`    | `200 {"status": "ok"}`: сервис работает и видит БД; иначе `503` |
| `GET`  | `/metrics`    | метрики Prometheus |
| `POST` | `/reload`     | перечитать конфиг (см. ниже): `200 {"status": "reloaded", "changed": true/false}`; `500`: конфиг не читается; `503`: с новыми параметрами не удалось подключиться к БД. В обоих случаях ошибки сервис продолжает работать со старыми настройками |

Тело события:

```json
{
  "app": "billing",
  "action": "login",
  "actor": "user1",
  "payload": {"ip": "10.0.0.1"}
}
```

- `app`: имя приложения, строчные латинские буквы, цифры, `-` и `_` (`^[a-z0-9][a-z0-9_-]{0,63}$`);
- `action`, `actor`: непустые строки до 128 символов;
- `payload`: произвольный JSON-объект, необязателен.

```bash
curl -s -X POST localhost:8080/api/events \
  -H 'Content-Type: application/json' \
  -d '{"app": "billing", "action": "login", "actor": "user1"}'
```

## Конфигурация

Параметры подключения к БД сервис читает из YAML-файла. Путь к нему задаёт переменная `AUDIT_SVC_CONFIG`, по умолчанию `/etc/audit-svc/config.yaml`:

```yaml
database:
  host: postgres
  port: 5432
  name: audit
  user: audit_svc
  password: change-me
```

Остальное задаётся переменными окружения:

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `AUDIT_SVC_CONFIG` | `/etc/audit-svc/config.yaml` | путь к конфигу |
| `HOST` | `0.0.0.0` | адрес, на котором слушает сервер |
| `PORT` | `8080` | порт |
| `LOG_LEVEL` | `INFO` | уровень логирования |

Особенности:

- если файла конфига нет или он некорректен, сервис **не запускается** и пишет причину в лог;
- если БД недоступна при старте, сервис запускается, отвечает `503` и пробует подключиться заново при каждом запросе;
- конфиг перечитывается **только** по `POST /reload`. Сервис открывает новый пул соединений с новыми параметрами и, если подключение удалось, закрывает старый. Перезапускать процесс не нужно.

> [!WARNING]
> `/reload` не требует авторизации, поэтому снаружи он должен быть закрыт: прокси перед сервисом не должен пропускать к нему запросы.

## Метрики

| Метрика | Тип | Метки | Что считает |
|---------|-----|-------|-------------|
| `audit_events_received_total` | counter | `app` | сохранённые события |
| `audit_http_requests_total` | counter | `method`, `handler`, `code` | HTTP-запросы. `handler` — шаблон маршрута (`/api/events`), для неизвестных путей `unmatched` |
| `audit_http_request_duration_seconds` | histogram | `method`, `handler` | время обработки запроса |
| `audit_config_reloads_total` | counter | `result` (`success`/`failure`) | вызовы `/reload` |
| `audit_db_up` | gauge | — | `1`, если есть подключение к PostgreSQL |

Плюс стандартные метрики процесса `process_*` и `python_*` из `prometheus-client`.

## Скрипты

Скрипты объявлены в `pyproject.toml` (`[tool.poetry.scripts]`). При установке пакета через `pip` они становятся командами в `PATH` (в образе: `/usr/local/bin/migrate` и т. д.).

| Скрипт | Команда | Что делает |
|--------|---------|------------|
| `server` | `server` или `python -m audit_svc` | запускает сервис |
| `migrate` | `migrate [--config path]` | создаёт таблицы в БД. Применённые миграции записываются в `schema_migrations`, поэтому повторный запуск безопасен. Конфиг тот же, что у сервиса |
| `generate` | `generate --url http://localhost:8080 --rate 20 --duration 300` | генерирует нагрузку: случайные события четырёх приложений с разной частотой, ~5 % некорректных (`400`) и ~10 % чтений (`200`). `--duration 0` — до Ctrl+C |

Пользователь из конфига должен иметь право создавать таблицы. Проще всего сделать его **владельцем** базы: начиная с PostgreSQL 15, в схеме `public` создавать объекты могут только владелец БД и те, кому явно выдано `CREATE`.

## Сборка

Те же команды, что у `counter-backend`:

```bash
python -m pip install poetry poetry-plugin-export setuptools wheel

mkdir -p dist
poetry export --without-hashes --format constraints.txt --output dist/constraints.txt
poetry run python -m pip wheel --isolated --requirement dist/constraints.txt --wheel-dir dist/vendor
poetry build --format wheel
```

Затем установить все колёса из `dist` и `dist/vendor` командой `pip install --no-index --no-deps ...` (см. ДЗ 3) и запустить `python -m audit_svc`.

Сборка `asyncpg` из исходников требует компилятора, но для Linux x86_64/arm64 и Python 3.11 на PyPI есть готовые колёса, так что с образом `python:3.11-slim-bookworm` ничего доустанавливать не нужно.

## Локальный запуск и тесты

```bash
poetry install
poetry run pytest                 # тесты не требуют PostgreSQL

docker run -d --name audit-pg -e POSTGRES_PASSWORD=pg -p 127.0.0.1:5432:5432 postgres:17
docker exec audit-pg psql -U postgres -c "CREATE ROLE audit_svc LOGIN PASSWORD 'change-me'" \
                                      -c "CREATE DATABASE audit OWNER audit_svc"
cat >config.yaml <<'EOF'
database: {host: localhost, port: 5432, name: audit, user: audit_svc, password: change-me}
EOF
AUDIT_SVC_CONFIG=config.yaml poetry run migrate
AUDIT_SVC_CONFIG=config.yaml poetry run server
poetry run generate --duration 30          # в соседнем терминале
```
