# ADR-0010: Приложение `pricing` заменяет `FeedMarkupSet`/`FeedMarkupRule`

**Статус:** Принято

## Контекст

`FeedMarkupSet`/`FeedMarkupRule` рассчитывают цены при завершении `SupplierFeed` и записывают результат обратно в `SupplierFeedEntry.data`. Цены остаются эфемерными (живут внутри сессии), не имеют истории, не пригодны для ценообразования прайса.

## Решение

Создать приложение `pricing` с моделями `PriceType`, `ProductPrice`, `PricingRule`, `Stock`. При завершении `SupplierFeed` Celery-задача (`transaction.on_commit → task.delay(feed_id)`) извлекает цены и остатки из `SupplierFeedEntry.data` в постоянные `ProductPrice` и `Stock` записи, затем применяет `PricingRule` поставщика. `FeedMarkupSet` и `FeedMarkupRule` упраздняются.

## Следствия

- `FeedMarkupSet`/`FeedMarkupRule` удаляются вместе с их миграциями (необходима data-миграция если есть данные).
- `FeedMapping.variable_columns` заменяется `FeedColumnMapping` — реляционной моделью с явными ролями колонок.
- `ProductPrice` становится единственным источником истины для текущих цен товара.
