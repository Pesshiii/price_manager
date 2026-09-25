---
title: supplier_product_manager — overview
summary: SupplierProduct and the Excel import pipeline that produces it.
code: price_manager/supplier_product_manager/
---
# supplier_product_manager — overview

`SupplierProduct` is the supplier's raw price row; the rest of the app is the
**Excel import pipeline** that produces those rows. Most of the complexity is
in the pipeline, not the model.
