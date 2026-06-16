"""Supplier feed matching module.

Algorithm:
  1. Load all SupplierLink records for the supplier (one DB query).
  2. Rows with a cached link → create SupplierFeedEntry immediately.
  3. Rows without a link → text matching against Product.name:
     a. pg_trgm pre-filter (GIN index) returns top-10 candidates.
     b. rapidfuzz.token_sort_ratio re-ranks them (word-order-insensitive).
     c. best_score >= auto_match_threshold → auto-match + SupplierLink.
     d. low_match_threshold <= best_score < auto_match_threshold → MatchQueue with candidates.
     e. best_score < low_match_threshold (or no candidates) → MatchQueue without candidates.
  4. Bulk-write all entries; bulk-create new links.

Mocking point for tests: patch 'supplier_feed.matcher._find_candidates'.
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.postgres.search import TrigramSimilarity
from rapidfuzz import fuzz

from product.models import Product
from .models import SupplierFeedEntry, SupplierLink

logger = logging.getLogger(__name__)

TOP_N_CANDIDATES = 5
TRGM_PREFILTER_MULTIPLIER = 0.7  # looser than low_thresh to allow re-rank headroom


def run_matching(feed, rows: list[dict[str, Any]], *, finder=None) -> dict[str, int]:
    if finder is None:
        finder = _find_candidates
    mapping = feed.feed_mapping
    sku_col: str = mapping.supplier_sku_column
    name_col: str = mapping.name_column
    var_cols: list[str] = list(mapping.variable_columns or [])
    high_thresh: float = float(mapping.auto_match_threshold)
    low_thresh: float = float(mapping.low_match_threshold)

    cached_links: dict[str, int | None] = {
        sl.supplier_sku: sl.product_id
        for sl in SupplierLink.objects.filter(supplier=feed.supplier)
    }

    entries_to_create: list[SupplierFeedEntry] = []
    links_to_create: list[SupplierLink] = []
    need_text: list[tuple[str, str, dict]] = []  # (supplier_sku, entry_name, data)

    matched = queued = skipped = 0

    for row in rows:
        supplier_sku = str(row.get(sku_col) or '').strip()
        if not supplier_sku:
            continue
        data = {
            col: row.get(col)
            for col in ([name_col] + var_cols)
            if col in row
        }

        if supplier_sku in cached_links:
            product_id = cached_links[supplier_sku]
            if product_id is None:
                entries_to_create.append(SupplierFeedEntry(
                    feed=feed, supplier_sku=supplier_sku, data=data, skipped=True,
                ))
                skipped += 1
            else:
                entries_to_create.append(SupplierFeedEntry(
                    feed=feed, supplier_sku=supplier_sku, product_id=product_id, data=data,
                ))
                matched += 1
        else:
            entry_name = str(row.get(name_col) or supplier_sku).strip()
            need_text.append((supplier_sku, entry_name, data))

    name_to_candidates: dict[str, list[dict]] = {}
    for supplier_sku, entry_name, data in need_text:
        if entry_name not in name_to_candidates:
            name_to_candidates[entry_name] = finder(entry_name, low_thresh)

    for supplier_sku, entry_name, data in need_text:
        candidates = name_to_candidates[entry_name]

        if candidates and candidates[0]['score'] >= high_thresh:
            best = candidates[0]
            entries_to_create.append(SupplierFeedEntry(
                feed=feed, supplier_sku=supplier_sku, product_id=best['product_id'],
                data=data, best_score=best['score'],
            ))
            links_to_create.append(SupplierLink(
                supplier=feed.supplier, supplier_sku=supplier_sku,
                product_id=best['product_id'],
            ))
            matched += 1
        else:
            entries_to_create.append(SupplierFeedEntry(
                feed=feed, supplier_sku=supplier_sku, product_id=None,
                data=data,
                match_candidates=candidates,
                best_score=candidates[0]['score'] if candidates else None,
            ))
            queued += 1

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
        'run_matching feed=%s matched=%d queued=%d skipped=%d',
        feed.pk, matched, queued, skipped,
    )
    return {'matched': matched, 'queued': queued, 'skipped': skipped}


def _find_candidates(name: str, low_thresh: float) -> list[dict]:
    if not name:
        return []

    trgm_min = low_thresh * TRGM_PREFILTER_MULTIPLIER
    qs = (
        Product.objects
        .filter(name__trigram_similar=name)      # activates GIN index via % operator
        .annotate(trgm=TrigramSimilarity('name', name))
        .filter(trgm__gt=trgm_min)
        .select_related('category', 'brand')
        .order_by('-trgm')[:10]
    )

    results = []
    for p in qs:
        score = fuzz.token_sort_ratio(name.lower(), p.name.lower()) / 100.0
        if score >= low_thresh:
            results.append({
                'product_id': p.pk,
                'score': round(score, 4),
                'name': p.name,
                'sku': p.sku,
                'category': p.category.name if p.category_id else None,
                'brand': p.brand.name if p.brand_id else None,
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:TOP_N_CANDIDATES]
