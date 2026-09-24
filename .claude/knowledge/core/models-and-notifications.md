---
title: Models and PersistentNotification lifetimes
summary: core models and how long each kind of persistent notification lives.
code: price_manager/core/models.py
---
# Models and PersistentNotification lifetimes

## Models (`core/models.py`)

- `CartItem:9` — `search_query`, M2M `products`, FK `confirmed_product`,
  `quantity`. `confirmed_price`/`line_total` are properties (`:43`, `:50`).
  `source_set:31` — nullable FK to `product.Product`, `SET_NULL`,
  `related_name='exploded_cart_items'` (migration `0012_cartitem_source_set`,
  depends on `product.0011`). Set only by `add_set_to_cart` (see
  [[core/cart-sets]]); it is purely a label — deleting the source set does not
  touch the cart item.
- `ShoppingTab:57` — named tab, `file`, M2M `items`, `open` flag.
- `ShoppingTabExport:78` — generated export file + `rows_count`.
- `PersistentNotification:154` — user-facing notification with `level`
  (`LevelChoices:106`), optional `link`/`link_text`, `kind`
  (`NotificationKind:112`), `ref`, `seen_at`, `expires_at`. Lifetimes, see
  below.
- `TaskRunHistory:205` — written by `execute_locked_task`
  ([[core/task-runner]]), never by hand. `status` from `StatusChoices:200`.

## `PersistentNotification` lifetimes

- **`regular`**: the countdown starts at the *first showing* (`seen_at`), not
  at `created_at`. After that it lives `NOTIFICATION_TTL_AFTER_SEEN`:
  `success`/`info` 10 s, `warning`/`danger` 10 min. A level not in the table
  (for example `debug` from `contrib.messages`) gets 10 s. A notification that
  is never shown is dropped by `core.cleanup_persistent_notifications` after
  `PERSISTENT_NOTIFICATION_TTL_HOURS` from `created_at`.
- **`export`** and **`release`**: deleted only by hand. `_notify(..., kind=)`
  in `core/tasks.py` sets `export` for the shopping-tab and product exports.
- **`confirmation`**: deleted by `dismiss_confirmations` in
  [[supplier_product_manager]] through `ref='import_run:<pk>'`. It is also
  swept by `cleanup_supplier_files_task` once the run is no longer pending.
- **What counts as "shown"**: a panel poll with `seen=true`. The script in
  `notifications_sidebar.html` sends that only while the offcanvas is open in
  a visible tab. It refreshes on `shown.bs.offcanvas` and on
  `visibilitychange`. The panel also polls every 15 s while closed, and those
  polls mark nothing. A Django message is already seen at creation:
  `persist_notification` stores the toast's copy with `seen_at=now`.
- **Removal without a reload**: the panel view renders
  `data-expires-in-ms` (server-computed, so no clock skew). JS removes the
  element when it runs out and refreshes the panel so the badge follows.
- **Every read goes through `.visible()`**: the context processor, the panel
  and both delete views. Rows that have expired but are not yet swept stay in
  the DB until the hourly cleanup.
- **`mark_seen` gotcha**: it takes pks, not the sliced queryset, because
  `.update()` on a slice raises.
