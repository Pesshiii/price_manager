"""Pricing engine — plain (Celery-free) functions implementing the three
phases of feed pricing: raw price extraction, stock reconciliation, and
rule application. The ``apply_feed_pricing`` Celery task is a thin adapter
over these (see ``pricing/tasks.py``).
"""
import logging

logger = logging.getLogger(__name__)


def _matched_entries(feed) -> list:
    """Feed entries that resolved to a product (the only ones pricing acts on)."""
    from supplier_feed.models import SupplierFeedEntry

    return list(
        SupplierFeedEntry.objects
        .filter(feed=feed, product__isnull=False)
        .only('id', 'product_id', 'data')
    )


def apply_raw_prices(feed) -> int:
    """Extract price-role columns from a finished feed into raw ``ProductPrice``
    rows (``rule=None``). Returns the count of present-but-unparseable price
    cells skipped (missing cells are not counted)."""
    from supplier_feed.models import FeedColumnMapping
    from .models import ProductPrice

    supplier = feed.supplier

    price_columns = {
        cm.column_name: cm.price_type
        for cm in (
            FeedColumnMapping.objects
            .filter(feed_mapping=feed.feed_mapping)
            .select_related('price_type')
        )
        if cm.role == 'price' and cm.price_type
    }
    if not price_columns:
        return 0

    entries = _matched_entries(feed)

    skipped = 0
    for entry in entries:
        for col_name, price_type in price_columns.items():
            raw = entry.data.get(col_name)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                skipped += 1
                continue
            ProductPrice.objects.update_or_create(
                product_id=entry.product_id,
                supplier=supplier,
                price_type=price_type,
                defaults={'value': value, 'rule': None},
            )

    if feed.feed_mapping.is_full_inventory:
        # price_columns is non-empty here (early return above guards it).
        # A full-inventory feed asserts the supplier's complete catalogue:
        # products absent from the feed no longer exist for this supplier,
        # so all their prices (raw and derived) must be removed.
        present_product_ids = {e.product_id for e in entries}
        deleted, _ = ProductPrice.objects.filter(supplier=supplier).exclude(
            product_id__in=present_product_ids
        ).delete()
        if deleted:
            logger.info(
                'apply_raw_prices feed=%s deleted %d stale price(s) for absent products',
                feed.id, deleted,
            )

    return skipped


def reconcile_stock(feed) -> None:
    """Sync ``Stock`` from a finished feed.

    Products present in the feed are upserted (unparseable stock cells are
    skipped, leaving any prior quantity untouched). Products of this supplier
    *absent* from the feed are zeroed **only** when the mapping is marked as a
    full-inventory snapshot (``FeedMapping.is_full_inventory`` — see ADR-0014).
    """
    from supplier_feed.models import FeedColumnMapping
    from .models import Stock

    supplier = feed.supplier

    stock_columns = [
        cm.column_name
        for cm in FeedColumnMapping.objects.filter(feed_mapping=feed.feed_mapping)
        if cm.role == 'stock'
    ]
    stock_column = stock_columns[0] if stock_columns else None

    entries = _matched_entries(feed)
    if not entries:
        return

    present_product_ids = {e.product_id for e in entries}

    if not stock_column:
        # No stock data in this feed — nothing to upsert, and nothing to
        # justify zeroing absent products (a full-inventory snapshot still
        # needs a stock column to express "in stock"). See ADR-0014.
        return

    for entry in entries:
        raw_qty = entry.data.get(stock_column)
        if raw_qty is None:
            continue
        try:
            qty = int(float(raw_qty))
        except (TypeError, ValueError):
            # Unparseable cell: leave any prior quantity untouched.
            continue
        Stock.objects.update_or_create(
            product_id=entry.product_id,
            supplier=supplier,
            defaults={'quantity': qty},
        )

    if feed.feed_mapping.is_full_inventory:
        Stock.objects.filter(supplier=supplier).exclude(
            product_id__in=present_product_ids
        ).update(quantity=0)


def apply_rules(supplier, *, now=None) -> None:
    """Apply this supplier's ``PricingRule``s to existing source prices,
    producing calculated ``ProductPrice`` rows (``rule`` set). ``now`` is
    injectable so date-window filtering is deterministic in tests."""
    from django.db import models as db_models
    from django.utils import timezone

    from .models import PricingRule, ProductPrice

    if now is None:
        now = timezone.now()

    rules = list(
        PricingRule.objects.filter(supplier=supplier)
        .filter(db_models.Q(date_from__isnull=True) | db_models.Q(date_from__lte=now))
        .filter(db_models.Q(date_to__isnull=True) | db_models.Q(date_to__gte=now))
        .select_related('source_price_type', 'dest_price_type', 'category')
        .order_by('priority')
    )

    for rule in rules:
        source_prices = ProductPrice.objects.filter(
            supplier=supplier, price_type=rule.source_price_type,
        ).select_related('product__category')

        if rule.category_id:
            source_prices = source_prices.filter(
                product__category__in=rule.category.get_descendants(include_self=True)
            )

        for sp in source_prices:
            source_val = float(sp.value)

            if rule.price_from is not None and source_val < float(rule.price_from):
                continue
            if rule.price_to is not None and source_val > float(rule.price_to):
                continue

            dest_val = compute_dest_value(rule, source_val)
            if dest_val is None:
                logger.warning(
                    'PricingRule %s has malformed mode %r; skipping',
                    rule.pk, rule.mode,
                )
                break  # a malformed rule never produces values for any product

            ProductPrice.objects.update_or_create(
                product=sp.product,
                supplier=supplier,
                price_type=rule.dest_price_type,
                defaults={'value': dest_val, 'rule': rule},
            )


def compute_dest_value(rule, source_val: float):
    """Pure rule arithmetic. Returns the destination value, or ``None`` for a
    malformed ``mode`` (caller decides how to surface that)."""
    if rule.mode == 'formula':
        markup = float(rule.params.get('markup', 0))
        increase = float(rule.params.get('increase', 0))
        return source_val * (1 + markup / 100) + increase
    if rule.mode == 'fixed':
        return float(rule.params.get('value', 0))
    return None
