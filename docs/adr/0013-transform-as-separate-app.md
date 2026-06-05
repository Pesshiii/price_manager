# transform — отдельное Django-приложение, не расширение supplier_feed

Логика трансформации выгрузок (`SnapshotField`, `TransformRule`, `ProductSnapshot`) вынесена в отдельное приложение `transform`, а не добавлена в `supplier_feed`.

## Рассмотренные варианты

- **Расширить `supplier_feed`** — все модели в одном месте, `TransformRule` рядом с `FeedMapping`. Но `SnapshotField` — системный справочник без привязки к поставщику, он концептуально не принадлежит `supplier_feed`. Добавление ещё трёх моделей + API раздует и без того крупное приложение.
- **Новый app `transform`** — чёткая граница: `supplier_feed` отвечает за матчинг, `transform` — за нормализацию. FK из `transform` в `supplier_feed` (`TransformRule → FeedMapping`) — штатный паттерн, уже используется в проекте (`supplier_feed → product`, `supplier_feed → supplier`).

## Решение

Новый app `transform`. Прецедент: `dataframe` — тоже отдельный app с FK из других приложений.
