---
title: supplier_manager — overview
summary: The reference-data app, and not to be confused with the retiring supplier app.
code: price_manager/supplier_manager/
---
# supplier_manager — overview

The reference-data app: who supplies, in what currency, with which discount
groups. Small, but nearly everything else imports `Supplier`. Three models
remain (`Currency`, `Supplier`, `Discount`) — see Phase 2b-3 below for what
was removed.

## Note

There is a *separate, retiring* `supplier` app — similarly named, not this
one. This app is the live one for suppliers; categories and brands are
[[product]]'s. See [[retiring_stack]].
