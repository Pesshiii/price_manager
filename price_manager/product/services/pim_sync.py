from __future__ import annotations

import logging

from pim_api import Entity

from .. import pim_client
from ..models import Category, Product

logger = logging.getLogger(__name__)


def _fetch_pim_product(pim_id: str) -> dict:
    """Raw GET Product/{pim_id}. Raises on failure — callers decide how to handle it."""
    return pim_client.site.get(Entity(name='Product', id=pim_id))


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


def _compute_category_path(categories) -> str:
    """Build category_path from the locally resolved Category rows' MPTT ancestry —
    PIM's payload has no path string (only categoriesIds/categoriesNames), so the
    path is built from the local tree, not parsed out of the raw response.
    """
    paths = [
        ' > '.join(c.name for c in category.get_ancestors(include_self=True))
        for category in categories
    ]
    return '; '.join(paths)


def sync_product_from_pim(pim_id: str, data: dict | None = None) -> Product:
    """Fetch (unless `data` is already given) and persist one PIM Product as a
    local Product row: get_or_create by pim_id, set number/name/raw_data, resolve
    categoriesIds -> M2M, recompute category_path. Returns the Product instance.

    Lets IntegrityError (a `number` collision under a different pim_id) and any
    PIM-fetch error propagate — it's the caller's job to decide how to surface them.
    """
    if data is None:
        data = _fetch_pim_product(pim_id)

    product, _ = Product.objects.get_or_create(pim_id=pim_id)
    product.number = data.get('number') or ''
    product.name = data.get('name') or ''
    product.raw_data = data

    category_ids = data.get('categoriesIds') or []
    categories = [c for c in (_ensure_pim_category(cid) for cid in category_ids) if c]
    product.category_path = _compute_category_path(categories)
    product.save()
    product.categories.set(categories)
    return product
