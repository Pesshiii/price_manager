"""Supplier feed matching module.

Deep module with a single public function:
    run_matching(feed, rows) -> {'matched': int, 'queued': int, 'skipped': int}

Algorithm:
  1. Load all SupplierLink records for the supplier into a dict (one DB query).
  2. For rows with a cached link → create SupplierFeedEntry immediately
     (product set, or skipped=True for an ignore-link).
  3. For the rest → create SupplierFeedEntry with product=None, skipped=False,
     match_candidates=[], best_score=None. These land in the manual-review
     queue with zero auto-suggestions — no embedding-based candidate search.
  4. Bulk-write all entries.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import SupplierFeedEntry, SupplierLink

logger = logging.getLogger(__name__)


def run_matching(feed, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Match feed rows against cached SupplierLink records only.

    Creates a SupplierFeedEntry for every row. Rows with a cached SupplierLink
    are matched (or skipped, for ignore-links) immediately; everything else is
    queued for manual review with no auto-suggested candidates.

    Returns ``{'matched': int, 'queued': int, 'skipped': int}``.
    """
    mapping = feed.feed_mapping
    sku_col: str = mapping.supplier_sku_column
    id_cols: list[str] = list(mapping.identity_columns or [])
    var_cols: list[str] = list(mapping.variable_columns or [])

    # ── Step 1: load all SupplierLink records for this supplier (one query) ──
    # product_id=None means ignore-link (permanent skip marker).
    cached_links: dict[str, int | None] = {
        sl.supplier_sku: sl.product_id
        for sl in SupplierLink.objects.filter(supplier=feed.supplier)
    }

    entries_to_create: list[SupplierFeedEntry] = []

    matched = 0
    queued = 0
    skipped = 0

    # ── Step 2: partition rows into linked / ignore-linked / unlinked ─────────
    for row in rows:
        supplier_sku = str(row.get(sku_col) or '').strip()
        if not supplier_sku:
            continue
        data = {
            **{col: row.get(col) for col in id_cols if col in row},
            **{col: row.get(col) for col in var_cols if col in row},
        }

        if supplier_sku in cached_links:
            product_id = cached_links[supplier_sku]
            if product_id is None:
                entries_to_create.append(SupplierFeedEntry(
                    feed=feed,
                    supplier_sku=supplier_sku,
                    data=data,
                    skipped=True,
                ))
                skipped += 1
            else:
                entries_to_create.append(SupplierFeedEntry(
                    feed=feed,
                    supplier_sku=supplier_sku,
                    product_id=product_id,
                    data=data,
                ))
                matched += 1
        else:
            # No cached link: queue with zero auto-suggestions.
            entries_to_create.append(SupplierFeedEntry(
                feed=feed,
                supplier_sku=supplier_sku,
                product_id=None,
                data=data,
                match_candidates=[],
                best_score=None,
            ))
            queued += 1

    # ── Step 3: bulk-write entries ──────────────────────────────────────────
    if entries_to_create:
        SupplierFeedEntry.objects.bulk_create(entries_to_create, batch_size=500)

    logger.info(
        'run_matching feed=%s matched=%d queued=%d skipped=%d', feed.pk, matched, queued, skipped
    )
    return {'matched': matched, 'queued': queued, 'skipped': skipped}
