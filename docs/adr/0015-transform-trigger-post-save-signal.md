# Трансформация запускается через post_save-сигнал, не явным вызовом в views

Celery-задача трансформации (`run_transform_task`) запускается через `post_save`-сигнал на `SupplierFeed` при переходе статуса в `matched` или `done`, а не явным вызовом в каждом API-view.

## Рассмотренные варианты

- **Явный вызов в views** — прозрачно, легко трейсить. Но `STATUS_DONE` выставляется в четырёх местах (`resolve`, `create_product`, `bulk_create_products`, `ignore`), `STATUS_MATCHED` — в `run_feed_matching_task`. Пять точек синхронизировать — риск пропустить при будущем расширении.
- **`post_save`-сигнал** — единственная точка регистрации триггера. Покрывает все текущие и будущие пути к закрытому статусу. Риск двойного запуска снимается Redis-локом внутри `run_transform_task` (паттерн уже используется в `run_feed_matching_task`).

## Решение

`post_save`-сигнал. Условие срабатывания: `instance.status in (STATUS_MATCHED, STATUS_DONE)`. Задача idempotent — перезаписывает все матченые снимки сессии целиком.
