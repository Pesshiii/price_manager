---
title: Detail page, PIM errors and photos
summary: The detail page's three PIM states, maybe_notify_pim_error, get_file_url vs pim_image_url.
code: price_manager/main_product_manager/templates/mainproduct/, price_manager/main_product_manager/utils.py
---
# Detail page, PIM errors and photos

## Detail page — three PIM states (`templates/mainproduct/partials/detail.html:65-84`)

No `product` → «Не привязан». `product` set, no `pim_id` → «Не отправлен в
PIM». `pim_id` set, `pim_data` empty → «Нет данных» (PMP exists with no
`productId` yet, or PIM unreachable). Only the third state is a live call.

## `maybe_notify_pim_error` deliberately not gated on `settings.DEBUG` (`utils.py:109-139`)

DEBUG defaults false, so gating on it meant production — the environment a
PIM outage actually costs something — got no signal. Throttled per user
instead (`_PIM_NOTIF_THROTTLE_TTL`, 30 min).
`test_notifies_even_though_debug_is_false` (`tests.py:1006`) guards it.

## PIM photos — `get_file_url` vs `pim_image_url` (`utils.py:341-405`)

`get_file_url()` (`:341-372`) loops `(f'{size}ThumbnailUrl', 'url',
'downloadUrl')` through `_absolute_pim_url` (`:314-338`). Live PIM: thumbnail
keys/`url` don't exist on File records; `downloadUrl` is the only populated
key, always scheme-less, so `size` has no observable effect. It returns the
**PIM-side** URL — server use only, and every PIM image URL answers
anonymous with 401, so this must never reach a template.

Templates get `pim_image_url(file_id, size)` (`:400-405`) instead — our
proxy path (`product.views.PimImageView`, behind `LoginRequiredMiddleware`),
no network touched. `fetch_pim_image()` (`:408-453`) does the actual fetch:
token only to `settings.PIM_HOST`, redirects followed **by hand** with the
same host check each hop (httpx's own redirect-follow would carry the token
to any host off a relative 302), bytes cached a day, failures not cached.
Callers of `get_file_url` render full-size, not thumbnail: `render_photo` in
[[product]]'s `ProductTable` (`product/tables.py:176-188`, imports
`pim_image_url` from here) and `mainproduct/partials/detail.html`.
`GetFileUrlTests` (`tests.py:311`) still describes the older
`downloadUrl`-only shape, which also remains handled.
