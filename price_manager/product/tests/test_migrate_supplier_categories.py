"""Sanity-check for the one-shot data migration that copies
``supplier_manager.Category`` into ``product.Category``.

We don't try to exercise the migration through the migration runner here —
that requires `MigratorTestCase` / django-test-migrations, which the project
doesn't currently use. Instead, we call the migration's ``forward()``
function directly against live models. This is enough to catch the
common breakages (missing parent rows, non-idempotent re-runs, MPTT
bookkeeping left in a torn state).
"""
from __future__ import annotations

from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from product.models import Category as NewCategory
from supplier_manager.models import Category as LegacyCategory


def _run_forward():
    """Invoke the migration's forward function with the live app registry.

    Migration module names start with a digit, so they can't be imported via
    normal ``from … import …`` syntax — we route through ``importlib``.
    """
    mod = import_module('product.migrations.0006_migrate_supplier_categories')
    mod.forward(django_apps, schema_editor=None)


class MigrateSupplierCategoriesTests(TestCase):
    def test_copies_simple_tree(self):
        root = LegacyCategory.objects.create(name='Электроника')
        child = LegacyCategory.objects.create(name='Дрели', parent=root)
        LegacyCategory.objects.create(name='Аккумуляторные', parent=child)

        _run_forward()

        # Every legacy node now has a sibling in the new tree.
        self.assertEqual(NewCategory.objects.count(), 3)
        new_root = NewCategory.objects.get(name='Электроника', parent=None)
        new_child = NewCategory.objects.get(name='Дрели', parent=new_root)
        new_grand = NewCategory.objects.get(name='Аккумуляторные', parent=new_child)

        # MPTT bookkeeping is sane (the rebuild() call at the end of forward()
        # guarantees this even if save() above left tree_id/lft/rght fuzzy).
        self.assertEqual(new_root.level, 0)
        self.assertEqual(new_child.level, 1)
        self.assertEqual(new_grand.level, 2)

    def test_idempotent_when_target_already_has_node(self):
        """Re-running must not duplicate rows; get_or_create matches on
        (parent, name) per the model's UniqueConstraint."""
        # Pre-seed the destination with one of the categories we're about to
        # migrate — this simulates a real cluster where someone already
        # created the new node by hand or via the UI.
        NewCategory.objects.create(name='Электроника', parent=None)

        LegacyCategory.objects.create(name='Электроника')

        _run_forward()
        self.assertEqual(
            NewCategory.objects.filter(name='Электроника', parent=None).count(),
            1,
        )

        # Second pass must also be a no-op.
        _run_forward()
        self.assertEqual(
            NewCategory.objects.filter(name='Электроника', parent=None).count(),
            1,
        )

    def test_empty_legacy_tree_is_a_noop(self):
        self.assertEqual(LegacyCategory.objects.count(), 0)
        _run_forward()
        self.assertEqual(NewCategory.objects.count(), 0)

    def test_same_name_under_different_parents_kept_distinct(self):
        a = LegacyCategory.objects.create(name='A')
        b = LegacyCategory.objects.create(name='B')
        LegacyCategory.objects.create(name='Дрели', parent=a)
        LegacyCategory.objects.create(name='Дрели', parent=b)

        _run_forward()

        # Two roots + two leaves with the same name under different parents.
        self.assertEqual(NewCategory.objects.count(), 4)
        drilly = NewCategory.objects.filter(name='Дрели')
        self.assertEqual(drilly.count(), 2)
        parents = {c.parent.name for c in drilly}
        self.assertEqual(parents, {'A', 'B'})
