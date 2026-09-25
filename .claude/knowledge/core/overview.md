---
title: core — overview
summary: What core holds (the UI hub, 81 of 123 templates) and the dead code to avoid.
code: price_manager/core/
---
# core — overview

The UI hub and shared infrastructure. Largest, most template-heavy app:
**81 of the repo's 123 templates** live here, including templates owned by
*other* apps' views (`supplier/`, `currency/`, `main/`, `upload/`,
`registration/`). The `category/` and `manufacturer/` folders went with Phase
2b-3 — they had had no routes for a while. If you are looking for a template and it
isn't under the app that renders it, look here first.

## Dead code

`core/viewmixins.py` → `HtmxMixin` is **unused**. Don't reach for it.
