# PRD: SupplierFeed — Выгрузки поставщика

## Problem Statement

Поставщики регулярно (еженедельно, ежедневно) присылают файлы с **изменяемыми** данными о товарах: ценами, остатками, складами, акциями. Эти данные поступают в разных форматах, с разными названиями колонок, и нередко одна выгрузка разбита на несколько файлов (отдельно цены, отдельно остатки).

На сегодня в системе нет способа принять такой файл, сопоставить его строки с товарами в каталоге и сохранить историю. Менеджер либо вводит данные вручную, либо использует неприспособленный для этого механизм `ImportJob`, который затирает постоянные характеристики товара вместо того, чтобы обновить только цену или остаток.

## Solution

Новое Django-приложение `supplier_feed` реализует полный pipeline приёма выгрузок:

1. **FeedMapping** — пользователь один раз настраивает конфигурацию для каждого поставщика: какая колонка является артикулом поставщика, какие колонки — дополнительными идентификаторами для матчинга, какие — переменными полями (цена, остаток и т.д.).
2. **SupplierFeed (сессия)** — при получении очередной выгрузки пользователь открывает сессию, загружает один или несколько файлов, затем нажимает «Обработать».
3. **Celery-задача матчинга** — система автоматически сопоставляет строки выгрузки с товарами каталога: сначала по кэшированным `SupplierLink`-связям (мгновенно), затем по векторному сходству эмбеддингов (для новых артикулов). Строки с высоким сходством коммитятся автоматически; сомнительные попадают в MatchQueue.
4. **MatchQueue** — менеджер разбирает нераспознанные строки вручную: выбирает товар из предложенных кандидатов или назначает вручную; подтверждённая связь сохраняется как `SupplierLink` и автоматически используется в следующих выгрузках.

Исторические данные каждой выгрузки сохраняются в `SupplierFeedEntry` и доступны для последующего анализа.

## User Stories

### FeedMapping — конфигурация поставщика

1. Как менеджер, я хочу создать конфигурацию выгрузки для поставщика, чтобы не перенастраивать маппинг колонок при каждой новой выгрузке.
2. Как менеджер, я хочу указать, какая колонка в файле является артикулом поставщика (`supplier_sku_column`), чтобы система могла использовать его как ключ для SupplierLink.
3. Как менеджер, я хочу указать дополнительные identity-колонки (например, «Название у поставщика»), чтобы система строила более точный эмбеддинг при первичном матчинге.
4. Как менеджер, я хочу указать переменные колонки (цена, остаток, склад и т.д.), чтобы эти данные сохранялись в `SupplierFeedEntry.data`.
5. Как менеджер, я хочу настроить порог авто-матчинга (`auto_match_threshold`) для каждого поставщика, чтобы учитывать разное качество описаний в файлах.
6. Как менеджер, я хочу редактировать существующую конфигурацию поставщика, чтобы добавить новые переменные колонки без создания заново.
7. Как менеджер, я хочу видеть список всех конфигураций выгрузок по поставщикам, чтобы быстро найти нужный маппинг.
8. Как менеджер, я хочу удалить конфигурацию выгрузки, чтобы убрать устаревшие настройки поставщика.

### SupplierFeed — жизненный цикл сессии

9. Как менеджер, я хочу открыть новую сессию выгрузки для поставщика, чтобы начать приём файлов текущего периода.
10. Как менеджер, я хочу загрузить один или несколько файлов в сессию, чтобы объединить все данные периода (например, отдельный файл с ценами и отдельный с остатками) перед обработкой.
11. Как менеджер, я хочу удалить ошибочно загруженный файл из сессии (пока она в статусе `draft`), чтобы исправить ошибку до запуска матчинга.
12. Как менеджер, я хочу нажать кнопку «Обработать», чтобы запустить матчинг и зафиксировать сессию (перевести в `processing`).
13. Как менеджер, я хочу видеть текущий статус сессии (`draft / processing / matched / partial / error`), чтобы понимать, на каком этапе находится обработка.
14. Как менеджер, я хочу видеть счётчики строк сессии (всего / сматчено / в MatchQueue / ошибок), чтобы быстро оценить результат матчинга.
15. Как менеджер, я хочу видеть список всех сессий выгрузок с фильтрацией по поставщику и статусу, чтобы отслеживать историю приёма данных.
16. Как менеджер, я хочу, чтобы сессия автоматически переходила из `partial` в `done`, когда я разобрал все строки MatchQueue, чтобы не закрывать её вручную.

### Celery-задача матчинга

17. Как система, я хочу при нажатии «Обработать» читать все загруженные файлы сессии через `dataframe/sessions.py`, чтобы не дублировать механизм загрузки файлов.
18. Как система, я хочу для каждой строки выгрузки сначала проверить наличие `SupplierLink(supplier, supplier_sku)`, чтобы мгновенно сматчить уже известные артикулы без запроса к эмбеддингам.
19. Как система, я хочу для строк без `SupplierLink` строить эмбеддинг из identity-полей и сравнивать с `Product.embedding` через косинусное сходство (HNSW-индекс), чтобы автоматически находить соответствие для новых артикулов.
20. Как система, я хочу автоматически создавать `SupplierLink` и заполнять `SupplierFeedEntry.product` для строк с косинусным сходством ≥ `auto_match_threshold`, чтобы не требовать ручного подтверждения для очевидных совпадений.
21. Как система, я хочу для строк с косинусным сходством < порога сохранять топ-N кандидатов в `SupplierFeedEntry.match_candidates` и оставлять `product = NULL`, чтобы пользователь мог разобрать их вручную.
22. Как система, я хочу записывать сматченные `SupplierFeedEntry` немедленно (частичный коммит), не дожидаясь разбора MatchQueue, чтобы данные были доступны для уже известных товаров.
23. Как система, я хочу использовать `execute_locked_task()` для задачи матчинга, чтобы предотвратить параллельный запуск для одной и той же сессии.
24. Как система, я хочу устанавливать статус `SupplierFeed.status = 'error'` и сохранять сообщение ошибки при падении задачи, чтобы пользователь видел, что пошло не так.
25. Как система, я хочу логировать прогресс и результат задачи матчинга в `TaskRunHistory`, чтобы иметь историю выполнения для отладки.

### MatchQueue — ручной разбор

26. Как менеджер, я хочу видеть список нераспознанных строк выгрузки (MatchQueue), чтобы знать, сколько строк требуют моего внимания.
27. Как менеджер, я хочу видеть для каждой нераспознанной строки данные identity-полей (артикул поставщика, название у поставщика и т.д.), чтобы понимать, что это за товар.
28. Как менеджер, я хочу видеть топ-N кандидатов из каталога с их косинусными скорами для каждой строки MatchQueue, чтобы быстро принять решение о сопоставлении.
29. Как менеджер, я хочу одним кликом подтвердить предложенный кандидат, чтобы сопоставить строку с товаром и создать `SupplierLink`.
30. Как менеджер, я хочу найти и выбрать товар вручную (если ни один кандидат не подходит), чтобы сопоставить строку с нужным продуктом из каталога.
31. Как менеджер, я хочу пометить строку как «не найден» (skipped), чтобы она не висела в MatchQueue бесконечно, если соответствующего товара в каталоге нет.
32. Как менеджер, я хочу видеть прогресс разбора MatchQueue (N из M), чтобы понимать, сколько осталось.
33. Как менеджер, я хочу после подтверждения последней строки MatchQueue видеть, что сессия перешла в статус `done`, чтобы убедиться в завершении обработки.

### SupplierLink — управление связями

34. Как менеджер, я хочу видеть список всех `SupplierLink` для поставщика, чтобы проверить, какие артикулы уже сопоставлены.
35. Как менеджер, я хочу удалить `SupplierLink`, чтобы сбросить неверное сопоставление и вернуть артикул в MatchQueue при следующей выгрузке.
36. Как менеджер, я хочу переназначить `SupplierLink` на другой товар, чтобы исправить ошибочное сопоставление без удаления и повторного создания.
37. Как менеджер, я хочу фильтровать SupplierLink по поставщику, артикулу поставщика и названию товара, чтобы быстро найти нужную связь.

## Implementation Decisions

### Новое приложение `supplier_feed`

- Создаётся отдельное Django-приложение `supplier_feed`. Не расширяет `product` (ответственность за каталог) и `supplier_manager` (мастер-данные поставщиков) — это принципиально новая концепция с собственной логикой матчинга и историей выгрузок.
- FK-связи: `supplier_manager.Supplier` и `product.Product`.

### Модели

Схема зафиксирована в ADR-0001:

```python
# supplier_feed/models.py (из ADR-0001 — decision-rich части)

class FeedMapping(models.Model):
    supplier = ForeignKey('supplier_manager.Supplier', on_delete=CASCADE)
    name = CharField(max_length=255)
    supplier_sku_column = CharField(max_length=128)
    identity_columns = JSONField(default=list)   # доп. колонки для эмбеддинга
    variable_columns = JSONField(default=list)   # переменные поля → data
    auto_match_threshold = FloatField(default=0.92)

class SupplierFeed(models.Model):
    # Статусы: draft → processing → matched | partial → done | error
    supplier = ForeignKey('supplier_manager.Supplier', on_delete=PROTECT)
    feed_mapping = ForeignKey(FeedMapping, on_delete=PROTECT)
    status = CharField(max_length=16, choices=STATUS_CHOICES, default='draft')
    session_ids = JSONField(default=list)        # dataframe session ids
    error = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

class SupplierFeedEntry(models.Model):
    feed = ForeignKey(SupplierFeed, on_delete=CASCADE)
    product = ForeignKey('product.Product', null=True, blank=True, on_delete=SET_NULL)
    supplier_sku = CharField(max_length=128, db_index=True)
    data = JSONField(default=dict)               # переменные поля
    match_candidates = JSONField(default=list)   # [{product_id, score, name}]
    skipped = BooleanField(default=False)        # помечена менеджером как «не найден»
    created_at = DateTimeField(auto_now_add=True)

class SupplierLink(models.Model):
    supplier = ForeignKey('supplier_manager.Supplier', on_delete=CASCADE)
    supplier_sku = CharField(max_length=128)
    product = ForeignKey('product.Product', on_delete=CASCADE)

    class Meta:
        unique_together = [('supplier', 'supplier_sku')]
```

Индексы:
- `SupplierFeedEntry(feed, product)` — для быстрого подсчёта MatchQueue.
- `SupplierFeedEntry(feed, supplier_sku)` — дедупликация при повторном матчинге.
- `SupplierLink(supplier, supplier_sku)` — уникальное ограничение (lookup по ключу O(log n)).

### Модуль матчинга `supplier_feed/matcher.py`

Глубокий модуль с простым интерфейсом. Принимает `SupplierFeed` + список строк (DataFrame или список словарей), возвращает статистику `{matched, queued, skipped}`. Внутри:

1. Batch-загрузка всех `SupplierLink` для поставщика в словарь `{supplier_sku: product_id}` — один запрос в БД.
2. Для строк без SupplierLink — batch-вызов `embed_query()` для identity-текстов (один HTTP-запрос к embedder на батч).
3. Векторный поиск через `Product.objects.annotate(score=CosineDistance('embedding', vec)).order_by('score')[:N]` — для каждой строки отдельно, но после получения эмбеддинга.
4. Создание `SupplierFeedEntry` и `SupplierLink` батчами (`bulk_create`/`bulk_update` с `update_conflicts`).

Примечание из прототипа: использовать `embed_query()`, а не `embed_texts()` — асимметричный режим критичен для качества retrieval.

### Celery-задача `supplier_feed/tasks.py`

- `run_feed_matching_task(feed_id)` — обёртка над `matcher.run_matching(feed)`.
- Читает файлы из `dataframe/sessions.py` по `feed.session_ids`.
- Вызывает `delete_session()` после успешного матчинга для каждого session_id.
- Использует `execute_locked_task()` из `core/task_runner.py` с lock_key = `supplier-feed-matching:{feed_id}`.
- Коммит по батчам размером `IMPORT_COMMIT_BATCH_SIZE` (env var, default 500) — та же константа, что в `product/importer.py`.
- Переходы статусов: `draft` → устанавливается `processing` до запуска задачи (в API-вью); задача пишет `matched`/`partial`/`error` по результату.

### REST API `supplier_feed/api/`

Структура аналогична `product/api/`:

| Метод | URL | Описание |
|-------|-----|----------|
| GET/POST | `/api/supplier-feed/mappings/` | Список и создание FeedMapping |
| GET/PUT/PATCH/DELETE | `/api/supplier-feed/mappings/{id}/` | Детали, редактирование, удаление FeedMapping |
| GET/POST | `/api/supplier-feed/feeds/` | Список и создание SupplierFeed |
| GET | `/api/supplier-feed/feeds/{id}/` | Детали сессии (статус, счётчики) |
| POST | `/api/supplier-feed/feeds/{id}/upload/` | Загрузить файл в сессию (через dataframe/sessions) |
| DELETE | `/api/supplier-feed/feeds/{id}/files/{session_id}/` | Удалить файл из сессии (только draft) |
| POST | `/api/supplier-feed/feeds/{id}/process/` | Нажать «Обработать» — запустить задачу матчинга |
| GET | `/api/supplier-feed/feeds/{id}/queue/` | MatchQueue для сессии (paginated) |
| POST | `/api/supplier-feed/feeds/{id}/queue/{entry_id}/resolve/` | Подтвердить матч / пометить как skipped |
| GET/DELETE/PATCH | `/api/supplier-feed/links/` | Список, удаление, переназначение SupplierLink |

`resolve` принимает `{product_id: int | null, skipped: bool}`. Если `product_id` задан — создаёт `SupplierLink` и заполняет `entry.product`. Если `skipped: true` — помечает запись. После каждого resolve проверяет, пуста ли очередь (`filter(feed=feed, product=None, skipped=False).count() == 0`) и автоматически переводит `feed.status` в `done`.

### Жизненный цикл сессии

```
draft ──upload files──► draft
draft ──/process──►  processing ──matcher OK, queue>0──► partial
                                ──matcher OK, queue==0──► matched
                                ──matcher error──►         error
partial ──resolve last entry──►  done
```

### Счётчики сессии (вычисляемые, не хранимые)

API-детали `/feeds/{id}/` возвращают аннотации:
- `total` = `SupplierFeedEntry.objects.filter(feed=id).count()`
- `matched` = `filter(feed=id).exclude(product=None).count()`
- `queued` = `filter(feed=id, product=None, skipped=False).count()`
- `skipped` = `filter(feed=id, skipped=True).count()`

Не хранятся в модели — вычисляются в одном запросе с `annotate`/`aggregate`.

## Testing Decisions

### Что считается хорошим тестом

Тест проверяет **внешнее поведение** модуля через его публичный интерфейс, а не детали реализации (конкретные SQL-запросы, внутренние вызовы методов). Для API — проверяется HTTP-статус, тело ответа и изменения в БД. Для matcher — проверяется итоговое состояние `SupplierFeedEntry` и `SupplierLink` после вызова. Для Celery-задачи — итоговый `SupplierFeed.status`.

### Модули под тесты

**`supplier_feed/tests/test_models.py`**
- Ограничения модели: `unique_together` на `SupplierLink`, nullable `product` у `SupplierFeedEntry`.
- Дефолтные значения: `FeedMapping.auto_match_threshold`, `SupplierFeed.status`.

**`supplier_feed/tests/test_matcher.py`** — главный deep module, изолированно тестируемый
- Ветка 1: SupplierLink lookup — строка сматчивается без обращения к embedder.
- Ветка 2: высокое косинусное сходство → авто-матч + SupplierLink создан.
- Ветка 3: низкое сходство → `product=NULL`, кандидаты в `match_candidates`.
- Ветка 4: смешанный батч (часть SupplierLink, часть авто-матч, часть MatchQueue).
- Embedder мокируется через `unittest.mock.patch` на `embed_query` — не нужен живой Ollama.
- Косинусное сравнение мокируется или тестируется на in-memory Product-записях с заранее заданными векторами.

**`supplier_feed/tests/test_tasks.py`**
- Переход статусов при успехе (→ `matched`, → `partial`).
- Переход в `error` при исключении в matcher.
- Lock: второй вызов задачи с тем же `feed_id` — skipped.
- `CELERY_TASK_ALWAYS_EAGER=True` — аналог `test_import_async.py`.

**`supplier_feed/tests/test_api_mappings.py`**
- CRUD FeedMapping: создание, список, редактирование, удаление.
- Проверка, что нельзя удалить FeedMapping у которого есть SupplierFeed.

**`supplier_feed/tests/test_api_feeds.py`**
- Создание сессии, загрузка файла, попытка удалить файл после `processing`.
- POST `/process/` меняет статус на `processing` и ставит задачу.
- Счётчики `total/matched/queued` в ответе детального view.

**`supplier_feed/tests/test_api_queue.py`**
- Список MatchQueue — только записи с `product=None, skipped=False`.
- Resolve: подтверждение кандидата → `product` заполнен, `SupplierLink` создан.
- Resolve: skipped → запись помечена, не появляется в queue.
- Auto-done: после последнего resolve сессия переходит в `done`.

**`supplier_feed/tests/test_api_links.py`**
- Список, удаление, переназначение SupplierLink.

### Аналоги в кодовой базе

- `product/tests/test_import_async.py` — паттерн тестирования Celery-задачи с `CELERY_TASK_ALWAYS_EAGER=True` и `@override_settings`.
- `product/tests/fixtures.py` — паттерн shared helpers (file builders, factory функции).
- `product/tests/test_api_crud.py` — паттерн DRF API тестов с `force_login`.
- `product/tests/test_embeddings.py` — паттерн мокирования embedder (`patch('product.services.embeddings.embed_texts')`).

Новые тесты следуют тому же `tests/` package layout с `__init__.py` и `fixtures.py`.

## Out of Scope

- **Интеграция с PriceManager**: использование `SupplierFeedEntry.data` (цен, остатков) для пересчёта `MainProductPrice` через правила `PriceManager` — это отдельная задача, требующая маппинга произвольных JSONB-ключей на поля правил.
- **Автозагрузка (pull)**: автоматическое скачивание файлов с FTP/HTTP поставщика по расписанию.
- **Дедупликация записей**: обнаружение дублирующихся строк внутри одной сессии (один и тот же `supplier_sku` в двух файлах).
- **Уведомления**: push-уведомления менеджеру когда сессия перешла в `partial` и требует ручного разбора.
- **Экспорт MatchQueue**: выгрузка нераспознанных строк в файл для разбора вне системы.
- **Версионирование FeedMapping**: история изменений конфигурации маппинга.

## Further Notes

- Использовать `embed_query()`, а **не** `embed_texts()` для identity-текстов строк выгрузки — асимметричный режим критичен для качества retrieval. Ошибка здесь не вызовет исключение, но заметно снизит точность матчинга.
- `dataframe/` app содержит и `models.py` и `models/` package — не добавлять туда модели (см. предупреждение в CLAUDE.md).
- Все `verbose_name` полей моделей — на русском языке.
- Команды запуска — из `price_manager/` поддиректории, не из корня репозитория.
- При batch-embedding важно учитывать лимиты Ollama (по умолчанию нет лимита токенов на запрос, но крупные батчи могут вызвать OOM на embedder-контейнере). Рекомендуемый размер батча для embed-запросов — до 64 строк за раз.
- `SupplierFeed.status` — свободная строка с фиксированными константами (аналогично `ImportJob.status`), а не `choices`-перечисление. Это упрощает introspection в shell.
