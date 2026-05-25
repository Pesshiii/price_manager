Реализовано через TDD (11 тестов, все зелёные).

**Что сделано:**
- Создано приложение `supplier_feed` (apps.py, models.py, admin.py, migrations/, tests/)
- Модель `FeedMapping` с миграцией `0001_initial`
- DRF `ModelViewSet` на `/api/supplier-feed/mappings/` — полный CRUD
- DELETE возвращает `409` при наличии связанных сессий выгрузок
- Аутентификация обязательна (анонимный → `401`)
- `supplier_feed` зарегистрирован в `INSTALLED_APPS`, роутер подключён в `api_urls.py`
- 11 тестов: `test_models.py` (3) + `test_api_mappings.py` (8)

Запуск: `python manage.py test supplier_feed --keepdb`
