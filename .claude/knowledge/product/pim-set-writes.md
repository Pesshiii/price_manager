---
title: Writing set compositions to PIM — AtroCore API traps
summary: Facts verified live against pim.tirado.kz (AtroCore 2.3.15) while bulk-writing ~900 rack set compositions with pim_api.upsert_async — none of this is exercised by repo code, which only reads set_components.
code: price_manager/pim_api/__init__.py, price_manager/product/services/sets.py
---
# Writing set compositions to PIM — AtroCore API traps

`services/sets.py`'s `sync_product_sets` only **reads** the `set_components`
association (see [[product/sets]]) — nothing in the repo writes
`AssociatedProduct` rows or creates PIM `Product`s. These facts came from a
one-off script (not repo code) that used `pim_api.upsert_async` to write
composition for ~770 «Пакс-металл» rack sets directly against
`pim.tirado.kz`, verified live on 2026-09-28. Keep them here in case a future
write-path (bulk PIM authoring, a "create set in PIM" admin action) is built
against the same API.

- **Writing an `AssociatedProduct` without `reverseAssociationId` creates only
  the direct link.** The payload needs both directions explicitly:
  `{associationId: <set_components id>, reverseAssociationId: <part_of_set
  id>, associatingItemId: <set>, associatedItemId: <component>, amount,
  sorting}`. Without `reverseAssociationId`, `reverseAssociatedProductId`
  stays `null` and no «Part of set» row appears on the component's PIM card —
  PIM does not backfill it later. With it, PIM creates the reverse row itself
  (its `amount` is `NULL`, matching what `services/sets.py:66-72` already
  assumes when reading `set_components`). Sets authored in the PIM UI (e.g.
  PS11035) have the reverse row; API-created ones only get it if the writer
  asks. **This has no effect on `sync_product_sets`**, which reads only the
  direct association — a missing reverse only breaks the PIM card's own
  display, not our sync.
- **A `Failed` item from `upsert_async` does not mean nothing was written.**
  Creating a `Product` with `mainImageId` set returned per-item status
  `Failed`, code 400, `"Your are not allow to link a file of type '' with
  'Product'. The only types allowed are ''"` — yet the `Product` row **was**
  created (`name`, `brandId`, `categoriesIds`, `description` all saved;
  `mainImageId` left `null`). Retrying a `Failed` create blindly hits the
  existing `number` and either duplicates it (if the check spells the number
  in a different case, see below) or 409s. **Check by number before retrying** a failed create.
- **PIM's `number` filter (`where type=equals/in`) is case-sensitive**, and
  PIM allows numbers that differ only in case: `ps74003221` and `PS74003221`
  were two distinct `Product` rows in the live catalogue. `equals PS10864`
  finds the set, `equals ps10864` finds nothing; `PSPROMO_2.0` misses the
  real `PSpromo_2.0`. Our side is the opposite — local `Product.number` is
  unique on `Lower(number)` and matched with `number__iexact`
  ([[product/overview]], [[product/pim-sync]], [[product/sets]]) — so two
  PIM case-twins collapse onto one local `Product`. **Query PIM with the
  number exactly as PIM stores it**; upper-casing numbers before a `where`
  (e.g. to key a dict) silently turns hits into misses — a verification pass
  that did this reported a correctly-written set as empty.
- **`DELETE /api/Product/{id}` and `DELETE /api/AssociatedProduct/{id}` both
  return 200** with the API token — useful for cleaning up duplicates or
  mis-created rows from a botched bulk write.

## Why the rack-set data had duplicate components

A 2026-09-24 supplier article change (unrelated to Price Manager code) left
up to three PIM `Product` rows per physical rack component: the old article
(`PS10xxx`), a new lowercase one with no suffix (`ps74xxxxxx`), and a new
uppercase one named "…, шт" (`PS74xxxxxx`, e.g. «Полка МС-100 300x700 , шт»,
often with a **Latin** `x` in the dimensions where the canonical name uses a
**Cyrillic** `х`). Matching these by name requires normalizing the ", шт"
suffix, Latin-x → Cyrillic-х, and whitespace — plain string equality misses
all three. On 2026-09-28, 49 unused duplicates (no `PriceManagerProduct`, no
associations) were deleted from PIM directly; the canonical row per component
is the `ps74…` one, else the sole `PS74…, шт` if no lowercase copy exists.

## Rack composition rules (from the owner, checked against supplier prices)

Per set: 4 uprights. Per shelf:

- **МС-Т**: 1 deck «Полка МС-Т W×D» + 2 big beams («Балка МС-Т 151/182» by
  width 1525/1830) + 2 small beams («Балка МС-Т 50/60/75» by depth
  506/608/760) + 1 «Стяжка 50/60/75».
- **МС-ТМ**: the МС-Т beams, the tie is «Стяжка МС-ТМ 500/600/750» instead,
  no deck, plus 10 (width 1525) or 12 (width 1830) «Полка МС-ТМ» — that PIM
  item is **one mini-shelf**, which is why it carries no width.

With the supplier's prices the МС-ТМ shelf reproduces the rack sheet's shelf
price to the rouble; the МС-Т sheet price leaves the tie out, so a МС-Т set's
cost from components is higher than the sheet by one tie per shelf — the owner
confirmed the tie belongs in the set. The sheet's «Кол-во балок» column
counts only the big beams. A 1830-wide МС-Т rack is named «…х608» but uses
the «1830х610» deck.
