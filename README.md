# price_manager
Manage prices, stocks and more in the Price Manager web app

## Docker Compose (DB + cache + Celery)

В проект добавлен `docker-compose.yml` со следующими сервисами:

- `db` — PostgreSQL 16
- `redis` — Redis 7 (кэш Django + брокер Celery)
- `web` — Django + Gunicorn
- `celery_worker` — Celery worker, очередь `celery`: импорт прайсов, выгрузки, пересчёт цен и остатков
- `celery_worker_pim` — Celery worker, очередь `pim`: синхронизация с PIM (`CELERY_TASK_ROUTES`); параллельность — `CELERY_PIM_CONCURRENCY`, по умолчанию 2
- `celery_beat` — расписание периодических задач

### Быстрый старт

```bash
docker compose up --build
```

После старта приложение будет доступно на `http://localhost:8000` (или на порту из `WEB_PORT`).

## Переменные среды

Ниже перечислены основные переменные окружения, используемые приложением и docker compose.

### Django / приложение

- `SECRET_KEY` — secret key Django.
- `DEBUG` — режим отладки (`true/false`, `1/0`, `yes/no`, `on/off`).
- `ALLOWED_HOSTS` — список хостов через запятую (например: `localhost,127.0.0.1`).
- `CSRF_TRUSTED_ORIGINS` — trusted origins через запятую (актуально при `DEBUG=false`).

### База данных (PostgreSQL)

- `POSTGRES_DB` — имя БД.
- `POSTGRES_USER` — пользователь БД.
- `POSTGRES_PASSWORD` — пароль БД.
- `DB_HOST` — хост БД (`db` внутри docker compose, `localhost` при локальном запуске).
- `DB_PORT` — порт БД (по умолчанию `5432`).

### Redis / кэш / Celery

- `REDIS_URL` — URL Redis для Django cache (например: `redis://redis:6379/1`).
- `CELERY_BROKER_URL` — брокер Celery (например: `redis://redis:6379/0`).
- `CELERY_RESULT_BACKEND` — backend результатов Celery (обычно тот же Redis).
- `CELERY_PIM_CONCURRENCY` — сколько задач синхронизации с PIM идёт одновременно (`celery_worker_pim`, по умолчанию `2`). Больше — синхронизация быстрее, но и нагрузка на PIM выше.

### Порты docker compose

- `WEB_PORT` — внешний порт для web-сервиса (по умолчанию `8000`).
- `REDIS_PORT` — внешний порт Redis (по умолчанию `6379`).
- `DB_PORT` — внешний порт PostgreSQL (по умолчанию `5432`).

### S3/объектное хранилище (опционально)

Если заданы все переменные ниже, проект включает S3-совместимый storage:

- `AWS_S3_ENDPOINT_URL`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_STORAGE_BUCKET_NAME`
- `AWS_S3_REGION_NAME` (опционально, по умолчанию `auto`)