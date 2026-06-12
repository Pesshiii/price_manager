"""Supplier feed matching module.

Deep module with a single public function:
    run_matching(feed, rows) -> {'matched': int, 'queued': int}

Algorithm:
  1. Load all SupplierLink records for the supplier into a dict (one DB query).
  2. For rows with a cached link → create SupplierFeedEntry immediately.
  3. For the rest → call embed_query() per row (asymmetric query mode).
  4. For each embedding, find the nearest Product via CosineDistance HNSW index.
     - score >= threshold  → auto-match: create SupplierFeedEntry + SupplierLink.
     - score <  threshold  → queue:      create SupplierFeedEntry with
                                          product=None and top-N candidates.
  5. Bulk-write all entries; bulk-create new links with update_conflicts.

Mocking point for tests:  patch 'supplier_feed.matcher.embed_query'.
"""
from __future__ import annotations

import logging
from typing import Any

from pgvector.django import CosineDistance

from product.models import Product
from product.services.embeddings import embed_query
from .models import SupplierFeedEntry, SupplierLink

logger = logging.getLogger(__name__)

TOP_N_CANDIDATES = 5


def run_matching(feed, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Match feed rows against the Product catalogue.

    Creates ``SupplierFeedEntry`` records for every row and ``SupplierLink``
    records for every automatic match (either via cached link or high-score
    vector similarity).

    Returns ``{'matched': int, 'queued': int, 'skipped': int}``.
    """
    mapping = feed.feed_mapping
    sku_col: str = mapping.supplier_sku_column
    id_cols: list[str] = list(mapping.identity_columns or [])
    var_cols: list[str] = list(mapping.variable_columns or [])
    threshold: float = float(mapping.auto_match_threshold)

    # ── Step 1: load all SupplierLink records for this supplier (one query) ──
    # product_id=None means ignore-link (permanent skip marker).
    cached_links: dict[str, int | None] = {
        sl.supplier_sku: sl.product_id
        for sl in SupplierLink.objects.filter(supplier=feed.supplier)
    }

    entries_to_create: list[SupplierFeedEntry] = []
    links_to_create: list[SupplierLink] = []
    need_embed: list[tuple[dict, str, dict]] = []

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
            need_embed.append((row, supplier_sku, data))

    # ── Steps 3–4: embed unlinked rows and find nearest product ───────────────
    for row, supplier_sku, data in need_embed:
        identity_text = ' '.join(
            str(row.get(col, '')) for col in id_cols if col in row
        ).strip() or supplier_sku

        vec = embed_query(identity_text)

        candidates = list(
            Product.objects
            .filter(embedding__isnull=False)
            .select_related('category', 'brand')
            .annotate(distance=CosineDistance('embedding', vec))
            .order_by('distance')[:TOP_N_CANDIDATES]
        )

        if candidates:
            best = candidates[0]
            best_dist = float(best.distance) if best.distance is not None else 2.0
            similarity = 1.0 - best_dist
        else:
            best = None
            similarity = -1.0

        if best is not None and similarity >= threshold:
            # Auto-match
            entries_to_create.append(SupplierFeedEntry(
                feed=feed,
                supplier_sku=supplier_sku,
                product_id=best.pk,
                data=data,
                best_score=round(similarity, 4),
            ))
            links_to_create.append(SupplierLink(
                supplier=feed.supplier,
                supplier_sku=supplier_sku,
                product_id=best.pk,
            ))
            matched += 1
        else:
            # Queue with top-N candidates for manual review
            candidate_list = [
                {
                    'product_id': p.pk,
                    'score': round(1.0 - float(p.distance), 4),
                    'name': p.name,
                    'sku': p.sku,
                    'category': p.category.name if p.category_id else None,
                    'brand': p.brand.name if p.brand_id else None,
                }
                for p in candidates
            ]
            queued_score = round(similarity, 4) if best is not None else None
            entries_to_create.append(SupplierFeedEntry(
                feed=feed,
                supplier_sku=supplier_sku,
                product_id=None,
                data=data,
                match_candidates=candidate_list,
                best_score=queued_score,
            ))
            queued += 1

    # ── Step 5: bulk-write entries and new links ───────────────────────────────
    if entries_to_create:
        SupplierFeedEntry.objects.bulk_create(entries_to_create, batch_size=500)

    if links_to_create:
        SupplierLink.objects.bulk_create(
            links_to_create,
            update_conflicts=True,
            update_fields=['product'],
            unique_fields=['supplier', 'supplier_sku'],
        )

    logger.info(
        'run_matching feed=%s matched=%d queued=%d skipped=%d', feed.pk, matched, queued, skipped
    )
    return {'matched': matched, 'queued': queued, 'skipped': skipped}
