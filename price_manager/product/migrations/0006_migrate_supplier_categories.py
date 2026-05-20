"""Data migration: copy the MPTT tree from ``supplier_manager.Category`` into
the new ``product.Category`` model.

Why a one-shot data migration:
The legacy `supplier_manager` app has its own MPTT-based ``Category`` tree
that the old catalog (`main_product_manager`) was built around. The new
`product` app introduced its own ``Category`` with the same shape but a
different table. Users are expected to migrate to the new catalog, so this
migration seeds the new tree from the old one. Idempotent — re-running is
safe because we use ``get_or_create(parent=…, name=…)``.

Mapping rules:
* Parent first, children after — we iterate in pre-order so the new parent
  exists by the time we create a child.
* Key is ``(parent, name)`` — matches the uniqueness constraint on
  ``product.Category`` (``product_category_parent_name_uniq``).
* ``slug`` and MPTT lft/rght/tree_id/level are not copied — the new
  ``Category.save()`` generates the slug, and ``Category.objects.rebuild()``
  rebuilds the MPTT bookkeeping after all rows are inserted.

Important note about importing the real model:
The standard advice is to use ``apps.get_model``, but the historical model
doesn't expose ``Category.save()`` (slug auto-gen) nor the MPTT manager's
``rebuild()`` method. For a one-off seed where the live model schema is
known and stable, importing the real model is acceptable — the migration
will break loudly if the model is later restructured incompatibly, which is
exactly the signal we want.

Reverse: no-op. We do not delete migrated rows on reverse; that would risk
clobbering hand-edited data in the new catalog. To roll back, drop the
``product_category`` table contents manually.
"""
from __future__ import annotations

from django.db import migrations


def forward(apps, schema_editor):
    # Historical model only — used to iterate the legacy tree read-only.
    LegacyCategory = apps.get_model('supplier_manager', 'Category')

    # Importing the live model to get `save()` (slug auto-gen) + MPTT manager.
    from product.models import Category as NewCategory  # noqa: PLC0415

    # Pre-order traversal: parents before children. MPTT exposes lft/rght
    # which we can use without touching the live tree.
    legacy_qs = LegacyCategory.objects.all().order_by('tree_id', 'lft')

    # old_id -> new Category instance
    id_map: dict[int, object] = {}

    for legacy in legacy_qs:
        parent_new = id_map.get(legacy.parent_id) if legacy.parent_id else None
        node, _created = NewCategory.objects.get_or_create(
            parent=parent_new,
            name=legacy.name,
        )
        id_map[legacy.id] = node

    # MPTT lft/rght/tree_id were updated incrementally by save() above, but
    # rebuild() is cheap and guarantees a clean state across mixed inserts
    # (e.g. when this migration runs against a catalog that already had a
    # few hand-created categories).
    NewCategory.objects.rebuild()


def reverse(apps, schema_editor):
    # Intentionally a no-op — see module docstring.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0005_characteristicmutationjob'),
        ('supplier_manager', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
