# ADR-0004: Dataframe Pipeline как единственный источник данных в SupplierFeed

**Статус:** Принято  
**Дата:** 2026-05-31  
**Supersedes:** ADR-0001 §9 («Pipeline-трансформации опциональны»)

---

## Контекст

ADR-0001 §9 определил, что `FeedMapping` хранит маппинг колонок независимо от `Dataframe.instructions`, а pipeline-трансформации опциональны. На практике это привело к тому, что `supplier_feed/tasks.py` читал файлы напрямую через `pd.read_excel` / `pd.read_csv`, минуя инфраструктуру `dataframe` app. Это означало:

- невозможность использовать альтернативные readers (только Excel/CSV по расширению);
- никаких трансформаций до матчинга (rename, select, drop_na и т.д.);
- дублирование логики чтения файлов, которая уже реализована в `dataframe/services.py`;
- отсутствие кэша reader-стадии для сессий SupplierFeed.

`ImportJob` (в `product` app) уже использует `Dataframe` pipeline как единственный источник. SupplierFeed оставался единственным исключением.

---

## Решение

### 1. `FeedMapping.dataframe` — обязательный FK

`FeedMapping` получает поле `dataframe = ForeignKey(Dataframe, on_delete=PROTECT)` — **обязательное**, не nullable. Это упраздняет прямое чтение файлов в задаче матчинга.

Nullable FK отклонён: два режима работы (с pipeline и без) — это скрытая сложность. Принцип «сырые файлы никогда не читаются напрямую» должен быть инвариантом, а не опцией.

### 2. Колонки FeedMapping работают против выхода pipeline

`supplier_sku_column`, `identity_columns`, `variable_columns` интерпретируются как имена колонок **после** применения всех трансформаций. Pipeline — это ETL-контракт: пользователь настраивает его так, чтобы выход имел стабильные предсказуемые имена. FeedMapping работает с этим чистым выходом.

Интерпретация против сырого файла отклонена: это создаёт два уровня маппинга с неочевидным порядком применения.

### 3. Один pipeline на весь FeedMapping, для всех сессий

`FeedMapping.dataframe` применяется одинаково к каждому файлу в `SupplierFeed.session_ids`. Файлы разного формата от одного поставщика — это разные `FeedMapping`, каждый со своим `Dataframe`.

Pipeline per-session отклонён: усложняет модель данных (`session_ids` превратился бы в `[{session_id, dataframe_id}]`) и противоречит принципу «FeedMapping создаётся один раз».

### 4. `apply()`, не `apply_partial()`

В задаче матчинга используется `dataframe.services.apply()` — полный pipeline или исключение. `apply_partial()` предназначен для preview: он возвращает данные до сломанного шага, чей статус неизвестен и которым нельзя доверять. Для production-обработки данные либо полностью валидны, либо фид переходит в `STATUS_ERROR`.

### 5. Preview через существующий эндпоинт

Отдельный preview-шаг в SupplierFeed не добавляется. Пользователь тестирует pipeline через `POST /api/dataframe/preview/` с тем же `session_id` ещё до нажатия «Обработать». Дублировать этот эндпоинт в SupplierFeed не нужно.

---

## Следствия

- `supplier_feed/tasks.py`: `_read_rows_from_sessions` заменяется на `dataframe.services.apply(feed.feed_mapping.dataframe, file, session_id=session_id)` per session.
- Reader-кэш (`session_id + SHA1(reader_cfg)` в Redis) теперь работает и для сессий SupplierFeed — бесплатный бонус от переиспользования инфраструктуры.
- Все существующие `FeedMapping` требуют назначения `Dataframe` до применения миграции (nullable → NOT NULL после backfill).
- `FeedMappingSerializer` должен принимать `dataframe_id` и возвращать базовые поля Dataframe (id, name).
