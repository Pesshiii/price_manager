from django.db.models import Prefetch

from supplier_feed.models import FeedMarkupRule, FeedMarkupSet, SupplierFeedEntry


def apply_markups(feed):
    """
    Write calculated prices into SupplierFeedEntry.data for all matched entries.
    Called once when a SupplierFeed transitions to 'done'.

    For each FeedMarkupSet on the feed's mapping:
      - read entry.data[price_column] as a float
      - find the first FeedMarkupRule (by order ASC) whose [price_from, price_to] covers the price
      - compute: output = price * (1 + markup/100) + increase  (no rounding)
      - write result to entry.data[output_column]

    If price_column is absent/non-numeric, or no rule matches — output_column is not written.
    Only matched entries (product is set) are processed.
    """
    markup_sets = list(
        FeedMarkupSet.objects
        .prefetch_related(
            Prefetch('rules', queryset=FeedMarkupRule.objects.order_by('order'))
        )
        .filter(feed_mapping=feed.feed_mapping)
    )
    if not markup_sets:
        return

    entries = list(
        SupplierFeedEntry.objects
        .filter(feed=feed, product__isnull=False)
        .only('id', 'data')
    )
    if not entries:
        return

    to_update = []
    for entry in entries:
        changed = False
        for mset in markup_sets:
            raw = entry.data.get(mset.price_column)
            if raw is None:
                continue
            try:
                price = float(raw)
            except (TypeError, ValueError):
                continue

            matched = None
            for rule in mset.rules.all():
                lo_ok = rule.price_from is None or price >= float(rule.price_from)
                hi_ok = rule.price_to is None or price <= float(rule.price_to)
                if lo_ok and hi_ok:
                    matched = rule
                    break

            if matched is None:
                continue

            result = price * (1 + float(matched.markup) / 100) + float(matched.increase)
            entry.data[mset.output_column] = result
            changed = True

        if changed:
            to_update.append(entry)

    if to_update:
        SupplierFeedEntry.objects.bulk_update(to_update, ['data'])
