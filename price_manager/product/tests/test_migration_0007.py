import contextlib
import importlib
import io

from django.apps import apps
from django.test import TestCase

from main_product_manager.models import MainProduct
from product.models import Product
from supplier.models import Supplier as FeedSupplier
from supplier_feed.models import SupplierLink
from supplier_manager.models import Currency, Supplier

migration = importlib.import_module('product.migrations.0007_product_pim_id_is_price_manager_product')


class ResetPimIdsTests(TestCase):
    """The data step of product.0007, run against the live registry.

    CI migrates an empty database, where the step has nothing to touch; this
    is the only place its filters meet rows.
    """

    def setUp(self):
        currency = Currency.objects.get_or_create(name='KZT', value=1)[0]
        self.supplier = Supplier.objects.create(
            name='Migration supplier',
            currency=currency,
            delivery_days_available=1,
            delivery_days_navailable=2,
        )

    def test_nulls_every_pim_id_and_deletes_only_unreferenced_placeholders(self):
        numbered = Product.objects.create(pim_id='old-1', number='N-1')
        linked_placeholder = Product.objects.create(pim_id='old-2')
        MainProduct.objects.create(supplier=self.supplier, article='A', name='A', product=linked_placeholder)
        # SupplierLink.product is on_delete=CASCADE: deleting this "orphan"
        # would silently take the supplier link with it.
        feed_placeholder = Product.objects.create(pim_id='old-3')
        SupplierLink.objects.create(
            supplier=FeedSupplier.objects.create(name='Feed supplier'),
            supplier_sku='FEED-1',
            product=feed_placeholder,
        )
        orphan = Product.objects.create(pim_id='old-4')

        with contextlib.redirect_stdout(io.StringIO()):
            migration.reset_pim_ids(apps, None)

        self.assertFalse(Product.objects.exclude(pim_id__isnull=True).exists())
        self.assertEqual(
            set(Product.objects.values_list('pk', flat=True)),
            {numbered.pk, linked_placeholder.pk, feed_placeholder.pk},
        )
        self.assertFalse(Product.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(SupplierLink.objects.filter(supplier_sku='FEED-1').exists())
