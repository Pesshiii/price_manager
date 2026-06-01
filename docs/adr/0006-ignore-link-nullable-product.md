# ADR-0006: Игнор-линк — SupplierLink с product = NULL

**Статус:** Принято  
**Дата:** 2026-05-31

---

## Контекст

При ручной разборке MatchQueue пользователю нужна возможность постоянно игнорировать строки от конкретного поставщика (например, сервисные позиции, упаковку, строки без реального товара). «Постоянно» означает: в следующих выгрузках эти артикулы не должны появляться в MatchQueue и не должны тратить ресурсы на эмбеддинг.

---

## Решение

`SupplierLink.product` делается nullable. `SupplierLink` с `product = NULL` называется **игнор-линком** и означает постоянный игнор артикула поставщика. Матчинг на шаге 1 проверяет наличие SupplierLink; если `product = NULL` — помечает `SupplierFeedEntry.skipped = True` и не идёт дальше. Создаётся действием «Игнорировать» в MatchQueue (`POST .../queue/{entry_id}/ignore/`). Может быть переназначен на реальный товар через PATCH `/api/supplier-feed/links/{id}/`.

---

## Рассмотренные альтернативы

**Отдельная таблица `IgnoreLink(supplier, supplier_sku)`** — отклонена. Дублирует структуру `SupplierLink`; матчинг должен смотреть в две таблицы вместо одной. При переводе игнор-линка в реальный матч нужно удалить `IgnoreLink` и создать `SupplierLink` — два шага вместо одного PATCH.

**Поле `is_ignored: BooleanField` на `SupplierLink`** с nullable `product` — отклонено. Создаёт невалидное состояние `(is_ignored=False, product=NULL)`, которое схема не запрещает. `product = NULL` как единственный допустимый игнор-маркер устраняет этот invalid state на уровне БД.

---

## Последствия

- Миграция: `SupplierLink.product` меняется с `NOT NULL` на nullable FK.
- Матчинг (`matcher.py`): шаг 1 разбивается на два случая — игнор-линк (skipped) и обычный линк (auto-match). `cached_links: dict[str, int | None]`; `None` → пропустить без эмбеддинга.
- Сериализатор: `SupplierLinkSerializer._ProductMiniSerializer` должен допускать `null` (поле `product` может отсутствовать).
- `SupplierLinkPatchSerializer`: `product_id` остаётся обязательным — PATCH всегда назначает реальный товар (нельзя PATCH в игнор-линк, для этого есть отдельный `ignore/` эндпоинт).
