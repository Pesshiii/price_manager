from __future__ import annotations

import logging

from pim_api import Entity

from .. import pim_client
from ..models import Category, Product

logger = logging.getLogger(__name__)


def _fetch_pim_link(pim_id: str) -> dict:
    """Raw GET PriceManagerProduct/{pim_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='PriceManagerProduct', id=pim_id))


def _fetch_pim_product(product_id: str) -> dict:
    """Raw GET Product/{product_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='Product', id=product_id))


def _fetch_pim_category(pim_category_id: str) -> dict:
    return pim_client.site.get(Entity(name='Category', id=pim_category_id))


def _ensure_pim_category(pim_category_id: str) -> Category | None:
    """Find or create the local Category matching a PIM category id.

    Walks up `parentsIds[0]` (the immediate parent — the local Category tree only
    supports a single parent) creating any missing ancestors too, so the full
    branch ends up marked in the tree. Returns None if the category can't be
    resolved (PIM error) rather than risk misplacing it under the wrong parent,
    so one bad id in a product's categoriesIds doesn't abort the whole sync.
    """
    if not pim_category_id:
        return None
    category = Category.objects.filter(pim_id=pim_category_id).first()
    if category:
        return category

    try:
        data = _fetch_pim_category(pim_category_id)
    except Exception:
        logger.warning('pim_sync: failed to fetch PIM category %s', pim_category_id, exc_info=True)
        return None

    parent_ids = data.get('parentsIds') or []
    parent = None
    if parent_ids:
        parent = _ensure_pim_category(parent_ids[0])
        if parent is None:
            return None

    category, created = Category.objects.get_or_create(
        parent=parent, name=data.get('name') or pim_category_id,
        defaults={'pim_id': pim_category_id},
    )
    if not created and not category.pim_id:
        category.pim_id = pim_category_id
        category.save(update_fields=['pim_id'])
    return category


def sync_product_from_pim(pim_id: str, data: dict | None = None) -> Product:
    """Persist PIM data onto the local Product whose PriceManagerProduct is `pim_id`.

    pim_id is a PriceManagerProduct id. The local Product is the one already
    holding it; failing that, the Product whose number is the PMP's number
    and which has no pim_id yet adopts it; failing that, a new Product is
    created with both.

    `data` is the PIM Product that PMP points at, fetched through the PMP's
    productId unless given. It supplies name, raw_data and categoriesIds ->
    M2M. number is never taken from it: number is the local sku match key,
    and PIM staff may link the PMP to a Product numbered differently. A PMP
    not linked to a PIM Product yet leaves name/raw_data/categories as they are.

    Lets IntegrityError (a new Product whose number another Product already
    holds under a different pim_id) and any PIM-fetch error propagate — it's
    the caller's job to decide how to surface them. Fetches happen before the
    first write, so a failed fetch leaves no half-made row behind.
    """
    link = None
    product = Product.objects.filter(pim_id=pim_id).first()
    if product is None:
        link = _fetch_pim_link(pim_id)
        # `or None`, not `or ''`: number is unique, and Postgres treats NULLs
        # as distinct in a unique index but '' as equal.
        number = link.get('number') or None
        product = (
            Product.objects.filter(number=number, pim_id__isnull=True).first() if number else None
        ) or Product(number=number)
        product.pim_id = pim_id
    if data is None:
        if link is None:
            link = _fetch_pim_link(pim_id)
        product_id = link.get('productId')
        data = _fetch_pim_product(product_id) if product_id else None
    if data is None:
        product.save()
        return product

    product.name = data.get('name') or None
    product.raw_data = data

    category_ids = data.get('categoriesIds') or []
    categories = [c for c in (_ensure_pim_category(cid) for cid in category_ids) if c]
    product.save()
    product.categories.set(categories)
    return product
