# price_manager
Manage prices, stocks and more in the Price Manager web app

## Redis cache and Celery

- Django cache uses Redis via the `REDIS_URL` environment variable.
- Celery uses Redis as both broker and result backend by default.
- `docker compose up --build` now starts `web`, `worker`, `redis`, and `db`.
- To execute tasks synchronously in tests or local debugging, set `CELERY_TASK_ALWAYS_EAGER=1`.

