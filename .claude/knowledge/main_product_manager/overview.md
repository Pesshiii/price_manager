---
title: main_product_manager — overview
summary: MainProduct as the per-supplier stock and price row; how fast this app's notes rot.
code: price_manager/main_product_manager/
---
# main_product_manager — overview

`MainProduct` — the canonical product record: a per-supplier stock+price row
hanging off `product.Product`. Owns the PIM integration. The PMP through-link
design (originally PR #184) is simply how the code reads now — not a recent
change. PR #231 reworked the `MainProduct` detail card into separate price
cards plus a stock card and removed «Привязать из ГП» (see
[[main_product_manager/detail-page-and-photos]] and
[[main_product_manager/filters-and-columns]]).

Line refs across this app's topics rot fast even between audits — a 2026-09-24
pass found several that had drifted, some by 30+ lines, from ordinary edits
elsewhere in the same file shifting later definitions down. Re-verify any
`file:line` before trusting it, especially in `utils.py`, which is the
largest file in the app and where most of the PIM logic lives.

The app's own Python files are: `models.py`, `utils.py` (PIM layer),
`tasks.py`, `pim_client.py` (module-level `SiteAPI`), `views.py`, `tables.py`
(now tiny — one table), `filters.py`, `forms.py`, `resources.py`, `funcai.py`,
`admin.py`, and `management/commands/` (`run_task` — runs this app's tasks
by name, `check_pim`, `export_main_products`). There is no `columns.py` — it
went with the old main page in Phase 2b; the column picker is
`product/columns.py`.
