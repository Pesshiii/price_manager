# ADR-0001: Архитектура SupplierFeed (Выгрузки поставщика)

**Статус:** Принято  
**Дата:** 2026-05-25

---

## Контекст

В `product` app реализован импорт **постоянных** характеристик товара (`Product.characteristics`, SKU, название и т.д.) через `ImportJob`. Необходим второй pipeline для **изменяемых** данных: цены, остатки, акции, склад — данные, которые поставщики присылают регулярно (еженедельно, ежедневно) в одном или нескольких файлах разного формата.

---

## Решение

### 1. Новое приложение `supplier_feed`

Весь функционал выгрузок выносится в отдельное Django-приложение. Альтернатива — расширить `product` или `supplier_manager` — отклонена: `product` уже несёт ответственность за каталог и импорт, `supplier_manager` — за мастер-данные поставщиков. `supplier_feed` — принципиально новая концепция (матчинг + хранение истории) достаточной сложности.

### 2. SupplierFeed = сессия, не один файл

Один поставщик может присылать несколько файлов за период (например, отдельно цены и остатки). `SupplierFeed` объединяет их в одну сессию. Сессия закрывается **явно** пользователем (кнопка «Обработать»), после чего запускается матчинг. Альтернатива — автозакрытие по таймауту — отклонена: матчинг через эмбеддинг дорогой, запускать его дважды на половинчатых данных нежелательно.

### 3. SupplierFeedEntry с историей, без денормализации на Product

Каждая строка каждой выгрузки хранится как `SupplierFeedEntry` — отдельная запись в БД. Снэпшот «только последнее состояние» на `Product` отклонён: данные о динамике цен и периодах наличия теряются безвозвратно, а восстановить их потом дорого. Денормализованное поле на `Product` (агрегат от всех поставщиков) отклонено: логика агрегации усложняется (чья цена «главная»?), это зона ответственности `PriceManager`, а не каталога.

### 4. Переменные поля — только JSONB

`SupplierFeedEntry.data = JSONField`. Фиксированные типизированные колонки для «стандартных» полей (цена, остаток) отклонены: разные поставщики шлют разные наборы полей с разными названиями. Жёсткая схема потребует миграции при каждом новом типе данных. JSONB с GIN-индексом достаточно для фильтрации; тот же паттерн уже используется в `Product.characteristics`.

### 5. SupplierLink как отдельная таблица постоянных связей

`SupplierLink(supplier, supplier_sku) → Product` — персистентная карта. Ключ — пара `(Supplier FK, supplier_sku CharField)`, где `supplier_sku` — обязательный primary identity-столбец, маркируемый пользователем в `FeedMapping`. После однократного подтверждения связи все последующие выгрузки того же поставщика сопоставляются мгновенно, без повторного эмбеддинга. Альтернатива — переиспользовать прошлые `SupplierFeedEntry` — отклонена: зависимость от объёма хранимой истории, хрупкость при удалении старых записей.

### 6. FeedMapping — постоянная конфигурация на поставщика

`FeedMapping` создаётся один раз и переиспользуется для всех сессий поставщика. Конфигурация-per-сессия (как `ImportJob.mapping`) отклонена: выгрузка — регулярный процесс, а не разовая операция. Перенастраивать маппинг каждую неделю — неприемлемая UX-нагрузка.

Содержит `auto_match_threshold` (порог косинусного сходства для авто-матча, настраивается на поставщика), т.к. качество описаний у разных поставщиков сильно разнится.

### 7. MatchQueue — не модель, а фильтр

`MatchQueue` = `SupplierFeedEntry.objects.filter(product=None)`. Отдельная модель очереди отклонена: дублирование состояния. Кандидаты матча (Top-3..5 с косинусными скорами) хранятся в `SupplierFeedEntry.match_candidates: JSONField`. При подтверждении пользователем: `product` заполняется, создаётся `SupplierLink`. `SupplierFeed` переходит в `done` автоматически когда очередь пуста.

### 8. Частичный коммит: сматченные записи коммитятся сразу

Строки с высоким сходством записываются немедленно. Несматченные строки (`product=NULL`) ждут ручного разбора — их данные уже сохранены в `data`, только FK на продукт отсутствует. Это позволяет не блокировать работу с данными пока пользователь разбирает очередь.

### 9. ~~Загрузка файлов через существующий dataframe/sessions.py~~ *(superseded ADR-0004)*

~~Механизм загрузки файлов, Redis-кэш и cleanup переиспользуются из `dataframe` app. Pipeline-трансформации опциональны. Маппинг колонок (identity/variable) — своя структура в `FeedMapping`, независимо от `Dataframe.instructions`.~~

> **Пересмотрено в ADR-0004.** `FeedMapping` теперь имеет обязательный FK на `Dataframe`. Сырые файлы никогда не читаются напрямую — только через `dataframe.services.apply()`. Колонки маппинга работают против выхода pipeline.

---

## Алгоритм матчинга

Для каждой строки выгрузки при обработке сессии:

1. **SupplierLink lookup**: есть `SupplierLink(supplier=…, supplier_sku=row[supplier_sku_column])`? → авто-матч, немедленно.
2. **Embedding comparison**: строится эмбеддинг из identity-полей строки → косинусное сравнение с `Product.embedding` (существующий HNSW-индекс).
3. Лучший скор ≥ `FeedMapping.auto_match_threshold` → авто-матч + создать `SupplierLink`.
4. Скор < порога → `product=NULL`, топ-N кандидатов → `match_candidates` → MatchQueue.

---

## Границы текущего скоупа

Интеграция `SupplierFeedEntry.data` с `PriceManager` (пересчёт `MainProductPrice` на основе цен из выгрузок) — **вне скоупа** данного ADR. Это отдельная задача, требующая маппинга произвольных JSONB-ключей на поля правил `PriceManager`.

---

## Схема моделей (набросок)

```python
# supplier_feed/models.py

class FeedMapping(models.Model):
    supplier = models.ForeignKey('supplier_manager.Supplier', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)           # «Прайс Рога», «Остатки Рога»
    supplier_sku_column = models.CharField(max_length=128)
    identity_columns = models.JSONField(default=list)  # доп. колонки для эмбеддинга
    variable_columns = models.JSONField(default=list)  # переменные поля → data
    auto_match_threshold = models.FloatField(default=0.92)

class SupplierFeed(models.Model):
    STATUS_DRAFT = 'draft'; STATUS_PROCESSING = 'processing'
    STATUS_MATCHED = 'matched'; STATUS_PARTIAL = 'partial'
    STATUS_DONE = 'done'; STATUS_ERROR = 'error'

    supplier = models.ForeignKey('supplier_manager.Supplier', on_delete=models.PROTECT)
    feed_mapping = models.ForeignKey(FeedMapping, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, ...)
    session_ids = models.JSONField(default=list)  # dataframe session ids загруженных файлов
    created_at = models.DateTimeField(auto_now_add=True)

class SupplierFeedEntry(models.Model):
    feed = models.ForeignKey(SupplierFeed, on_delete=models.CASCADE)
    product = models.ForeignKey('product.Product', null=True, blank=True, on_delete=models.SET_NULL)
    supplier_sku = models.CharField(max_length=128)
    data = models.JSONField(default=dict)            # переменные поля
    match_candidates = models.JSONField(default=list) # [{product_id, score, name}]
    created_at = models.DateTimeField(auto_now_add=True)

class SupplierLink(models.Model):
    supplier = models.ForeignKey('supplier_manager.Supplier', on_delete=models.CASCADE)
    supplier_sku = models.CharField(max_length=128)
    product = models.ForeignKey('product.Product', on_delete=models.CASCADE)

    class Meta:
        unique_together = [('supplier', 'supplier_sku')]
```
