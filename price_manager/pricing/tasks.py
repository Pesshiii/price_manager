import logging

from celery import shared_task
from django.db import models as db_models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def apply_feed_pricing(feed_id: int) -> None:
    """
    Called when SupplierFeed transitions to 'done'.
    1. For each matched SupplierFeedEntry: extract price-role columns → upsert ProductPrice(rule=None)
    2. Extract stock-role column → collect quantities
    3. Upsert Stock for products present in feed; zero out Stock for products of this supplier NOT in feed
    4. Apply PricingRules for this supplier (filter: category, price range, date) → upsert ProductPrice(rule=R)
    """
    from supplier_feed.models import SupplierFeed, SupplierFeedEntry
    try:
        from supplier_feed.models import FeedColumnMapping
    except ImportError:
        FeedColumnMapping = None

    from .models import PriceType, PricingRule, ProductPrice, Stock

    try:
        feed = SupplierFeed.objects.select_related('supplier', 'feed_mapping').get(pk=feed_id)
    except SupplierFeed.DoesNotExist:
        return

    supplier = feed.supplier

    column_mappings = []
    if FeedColumnMapping is not None:
        try:
            column_mappings = list(
                FeedColumnMapping.objects.filter(feed_mapping=feed.feed_mapping)
                .select_related('price_type')
            )
        except Exception as exc:
            logger.warning('FeedColumnMapping query failed: %s', exc)
            column_mappings = []

    price_columns = {cm.column_name: cm.price_type for cm in column_mappings if cm.role == 'price' and cm.price_type}
    stock_columns = [cm.column_name for cm in column_mappings if cm.role == 'stock']
    stock_column = stock_columns[0] if stock_columns else None

    entries = list(
        SupplierFeedEntry.objects
        .filter(feed=feed, product__isnull=False)
        .select_related('product')
        .only('id', 'product_id', 'data')
    )

    if not entries:
        return

    present_product_ids = {e.product_id for e in entries}

    prices_to_upsert = []
    stocks_to_upsert = []

    for entry in entries:
        for col_name, price_type in price_columns.items():
            raw = entry.data.get(col_name)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            prices_to_upsert.append({
                'product_id': entry.product_id,
                'supplier': supplier,
                'price_type': price_type,
                'value': value,
                'rule': None,
            })

        if stock_column:
            raw_qty = entry.data.get(stock_column)
            try:
                qty = int(float(raw_qty)) if raw_qty is not None else 0
            except (TypeError, ValueError):
                qty = 0
            stocks_to_upsert.append({'product_id': entry.product_id, 'supplier': supplier, 'quantity': qty})

    with transaction.atomic():
        for p in prices_to_upsert:
            ProductPrice.objects.update_or_create(
                product_id=p['product_id'],
                supplier=p['supplier'],
                price_type=p['price_type'],
                defaults={'value': p['value'], 'rule': None},
            )

        for s in stocks_to_upsert:
            Stock.objects.update_or_create(
                product_id=s['product_id'],
                supplier=s['supplier'],
                defaults={'quantity': s['quantity']},
            )

        # Zero out stock for products of this supplier not present in this feed.
        # Always do this when we have data for this supplier's products.
        if present_product_ids:
            Stock.objects.filter(supplier=supplier).exclude(
                product_id__in=present_product_ids
            ).update(quantity=0)

    now = timezone.now()
    rules = list(
        PricingRule.objects.filter(supplier=supplier)
        .filter(
            db_models.Q(date_from__isnull=True) | db_models.Q(date_from__lte=now)
        )
        .filter(
            db_models.Q(date_to__isnull=True) | db_models.Q(date_to__gte=now)
        )
        .select_related('source_price_type', 'dest_price_type', 'category')
        .order_by('priority')
    )

    for rule in rules:
        source_prices = ProductPrice.objects.filter(
            supplier=supplier,
            price_type=rule.source_price_type,
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

            if rule.mode == 'formula':
                markup = float(rule.params.get('markup', 0))
                increase = float(rule.params.get('increase', 0))
                dest_val = source_val * (1 + markup / 100) + increase
            elif rule.mode == 'fixed':
                dest_val = float(rule.params.get('value', 0))
            else:
                continue

            ProductPrice.objects.update_or_create(
                product=sp.product,
                supplier=supplier,
                price_type=rule.dest_price_type,
                defaults={'value': dest_val, 'rule': rule},
            )
