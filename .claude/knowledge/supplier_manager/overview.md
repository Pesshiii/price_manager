---
title: supplier_manager — overview
summary: The reference-data app — suppliers, currencies, discount groups.
code: price_manager/supplier_manager/
---
# supplier_manager — overview

The reference-data app: who supplies, in what currency, with which discount
groups. Small, but nearly everything else imports `Supplier`. Three models
remain (`Currency`, `Supplier`, `Discount`) — see
[[supplier_manager/retired-models]] for what was removed and where it went.

## Note

This is the only supplier app: the similarly named API-era `supplier` app was
removed with the rest of the API stack (`product.0018`). Categories and brands
are [[product]]'s.
