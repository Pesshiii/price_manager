---
title: Detail page, PIM errors and photos
summary: The detail page's three PIM states, maybe_notify_pim_error, and the three PIM-image paths - get_file_url (server only), pim_image_url (proxy), pim_public_url (anonymous Sharing link).
code: price_manager/main_product_manager/templates/mainproduct/, price_manager/main_product_manager/utils.py, price_manager/main_product_manager/views.py
---
# Detail page, PIM errors and photos

## Detail page — three PIM states (`templates/mainproduct/partials/detail.html:58-77`)

No `product` → «Не привязан». `product` set, no `pim_id` → «Не отправлен в
PIM». `pim_id` set, `pim_data` empty → «Нет данных» (PMP exists with no
`productId` yet, or PIM unreachable). Only the third state is a live call.
PR #231 also added a fourth «Остаток» stat card next to the price cards on
the same detail page, and split the card's «Наценки» panel into fixed vs.
rule-driven price tags — see [[main_product_manager/filters-and-columns]].

## `maybe_notify_pim_error` deliberately not gated on `settings.DEBUG` (`utils.py:149-179`)

DEBUG defaults false, so gating on it meant production — the environment a
PIM outage actually costs something — got no signal. Throttled per user
instead (`_PIM_NOTIF_THROTTLE_TTL`, 30 min).
`test_notifies_even_though_debug_is_false` (`tests.py:1105`) guards it.

## PIM photos — three URL kinds, only two may reach a template

Anonymous requests to PIM answer 401 for everything **except a public link**
(the `Sharing` entity, `pim.tirado.kz/sharings/<id>.<ext>`, verified live
2026-10-12). So:

- **`get_file_url(file_id, size)`** (`utils.py:381-412`) — the PIM-side
  File URL (`{size}ThumbnailUrl` → `url` → `downloadUrl`, each through
  `_absolute_pim_url`, `:354-378`). Needs the token, 401 anonymously: server
  use only, **never in a template**. Its only caller now is `fetch_pim_image`
  (`:489`). The code's own docstrings disagree on whether thumbnail keys
  exist: `:384-386` and `fetch_pim_image` (`:474-478`, thumbnails 302 to
  `/upload/thumbnails/…`) say the live PIM sends them (2026-09-21), while the
  `_absolute_pim_url` docstring (`:354-366`) and `GetFileUrlTests`
  (`tests.py:297`, the `downloadUrl`-only case at `:326-330`) still describe
  the older `downloadUrl`-only shape, which stays handled.
- **`pim_image_url(file_id, size)`** (`:444-449`) — our proxy path
  (`product.views.PimImageView`, `product/views.py:314`, behind
  `LoginRequiredMiddleware`), no network touched. `fetch_pim_image()`
  (`:466-511`) does the fetch: token only to `settings.PIM_HOST`, redirects
  followed **by hand** with the same host check each hop (httpx's own
  follow would carry the token to any host off a relative 302), bytes cached
  a day, failures not cached.
- **`pim_public_url(link)`** (`:452-463`) — a Sharing `link` made fit for
  `<img src>`. PIM sends it scheme-less like `downloadUrl`, so it goes through
  `_absolute_pim_url`, then is accepted only if https on `settings.PIM_HOST`
  (`_on_pim_host`, `:435`) and ≤500 chars (`ProductPhoto.public_url` is
  `max_length=500`): the value lands in the markup verbatim, a foreign host
  would be an image from someone else's server in our UI. The comment block
  above `PIM_IMAGE_SIZES` (`:415-427`) states the 401 rule and this exception.

Which path a page uses:

- **`/products/` photo column and the product card** — public link first, the
  proxy as `data-fallback-src` (swapped in once by
  `static/js/pim-photo-fallback.js`, loaded from `base.html`); a photo with no
  public link uses the proxy as its primary `src`. Built by
  `product.services.photos.photo_sources`/`product_photos` from the
  `product.ProductPhoto` mirror; `ProductTable.render_photo`
  (`product/tables.py:360`) no longer imports `pim_image_url`. A public link
  has no thumbnail, so `src` and `zoom` are the same original
  (`photos.py:63-64`). The mirror itself: [[product/photos]].
- **MainProduct detail card** (`mainproduct/partials/detail.html:80-86`,
  `views.py:97` and `:118`) — still the old single-photo path: one
  `pim_image_url(mainImageId or imageId)` proxy `src`, no public link, no
  fallback.
